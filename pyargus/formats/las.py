"""LAS/LAZ point clouds, through laspy.

A thin wrapper: the rest of the suite works on plain numpy arrays and
never sees a laspy object, so the dependency stays optional and swaps
out cleanly if PDAL takes over ingest later.

Three ways in, and the choice is about memory, not taste:

* ``read_points`` materializes the whole cloud. Simple, and right for
  anything that needs global state (a Delaunay triangulation, a
  solve). Budget ~39 bytes per point for the default fields, plus
  laspy's own packed record while the read is in flight.
* ``iter_points`` streams it in chunks and never holds more than one.
  Right for every accumulator: counting, gridding, per-cell medians,
  culling to a region. This is what makes a 350M-point delivery
  openable at all.
* ``copc_query`` asks a COPC file for a bounding box or a resolution
  and gets back only those points -- when the file is COPC, which is
  a property of how it was written, not something laspy can add.

WHY read_points COPIES. laspy hands back several fields as VIEWS into
its packed point record (measured on point format 6: gps_time,
intensity, classification and point_source_id are views; x/y/z are
not). A dict holding one of those keeps the entire record alive, so
the real cost of a "39 bytes per point" read was 56, and no caller
could see why. Every array here is a copy and the record is released
when the read returns.

WHY NOT DecompressionSelection. laspy can skip decompressing fields
it is told not to need, and it is roughly twice as fast. It also does
not zero what it skips: a skipped field comes back filled with the
chunk's first point's value, repeated. A field requested through the
wrong mask therefore reads as plausible, constant, wrong data rather
than as an error -- measured, on a real file, as a mean Z of 45.99
against a true 50.01. Not worth it here.
"""

import copy
import os
from pathlib import Path

import numpy as np

FIELDS = ("x", "y", "z", "gps_time", "intensity", "classification",
          "point_source_id", "return_number", "number_of_returns")

DEFAULT_CHUNK = 1_000_000
"""Points per streaming chunk. Below ~250k, lazrs's parallel
decompressor is re-driven often enough that wall time rises several
fold for very little further memory saving (measured)."""

BYTES_PER_POINT = 39
"""Array bytes for the default FIELDS. laspy's packed record costs
another ~30 on top while a whole read is in flight."""


def _laspy():
    try:
        import laspy
    except ImportError as exc:
        raise ImportError(
            "reading LAS/LAZ needs laspy: uv pip install -e \".[lidar]\""
        ) from exc
    return laspy


def _check_fields(header, fields, path):
    """Refuse unknown fields against the HEADER, before any points.

    Checking per record would let a zero-point file accept anything,
    because the loop that would have raised never runs -- and then a
    streaming consumer and a whole-file consumer disagree about the
    same file.
    """
    known = set(header.point_format.dimension_names)
    # the header lists the RAW integer dimensions X/Y/Z; x/y/z are
    # laspy's scaled accessors over them, and are what callers ask for
    scaled = {"x": "X", "y": "Y", "z": "Z"}
    for name in fields:
        if scaled.get(name, name) not in known:
            raise ValueError(
                f"{path}: point format has no field {name!r}")


def _extract(record, fields, path):
    """Fields out of one laspy record, as arrays that own their data."""
    out = {}
    for name in fields:
        try:
            out[name] = np.array(record[name])
        except (KeyError, AttributeError, ValueError) as exc:
            raise ValueError(
                f"{path}: point format has no field {name!r}") from exc
    return out


def cloud_info(path):
    """Everything the header knows, without reading a single point.

    Returns a dict: ``point_count``, ``point_format``, ``version``,
    ``mins``/``maxs`` (3,) arrays, ``scales``, ``offsets``,
    ``extra_dims`` (names), ``is_copc``, and ``crs`` (a pyproj CRS or
    None -- parsing it needs pyproj, and a missing pyproj reports None
    rather than failing a header read).
    """
    laspy = _laspy()
    with laspy.open(path) as reader:
        header = reader.header
        try:
            crs = header.parse_crs()
        except Exception:
            crs = None
        return {
            "point_count": int(header.point_count),
            "point_format": int(header.point_format.id),
            "version": str(header.version),
            "mins": np.array(header.mins, dtype=float),
            "maxs": np.array(header.maxs, dtype=float),
            "scales": np.array(header.scales, dtype=float),
            "offsets": np.array(header.offsets, dtype=float),
            "extra_dims": [d.name for d in
                           header.point_format.extra_dimensions],
            "is_copc": any(v.user_id == "copc" for v in header.vlrs),
            "crs": crs,
        }


def iter_points(path, fields=FIELDS, chunk_size=DEFAULT_CHUNK):
    """Stream a cloud in chunks, yielding a dict of arrays per chunk.

    The dicts are independent copies, so a caller may keep one; peak
    memory is one chunk, not one cloud. Field names and the refusal on
    a missing field match read_points exactly, which is what lets a
    consumer switch between them without changing anything else.
    """
    laspy = _laspy()
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    with laspy.open(path) as reader:
        _check_fields(reader.header, fields, path)
        for chunk in reader.chunk_iterator(chunk_size):
            yield _extract(chunk, fields, path)


def read_points(path, fields=FIELDS):
    """Read a whole LAS/LAZ file into a dict of numpy arrays.

    x/y/z arrive scaled (real coordinates, float64). A requested field
    the file does not carry raises rather than returning zeros. For a
    cloud large enough to matter, prefer ``iter_points``.
    """
    laspy = _laspy()
    with laspy.open(path) as reader:
        _check_fields(reader.header, fields, path)
        las = reader.read()
        return _extract(las, fields, path)


def drop_copc_records(header):
    """Strip COPC's records from a header read off a .copc.laz, in place.

    COPC keeps its octree in two records -- an info VLR and a hierarchy
    EVLR -- that describe the file's own byte layout. laspy reads them
    and cannot write them ("Writing COPC is not supported"), and a
    cloud rewritten from memory is a plain LAS/LAZ whatever it is named,
    so a header that still claimed the octree would be wrong even if it
    could be written. ``stream_update`` does the same for its copies.

    A header with no COPC record is left exactly as it was. That is not
    tidiness: laspy's ``vlrs`` setter re-syncs the extra-bytes VLR and
    moves it to the end, so even an unchanged list, reassigned, writes
    different bytes -- and this runs on every whole-cloud write.
    """
    laspy = _laspy()
    if any(v.user_id == "copc" for v in header.vlrs):
        header.vlrs = laspy.vlrs.vlrlist.VLRList(
            [v for v in header.vlrs if v.user_id != "copc"])
    if header.evlrs is not None and any(v.user_id == "copc"
                                        for v in header.evlrs):
        header.evlrs = laspy.vlrs.vlrlist.VLRList(
            [v for v in header.evlrs if v.user_id != "copc"])
    return header


def _output_header(laspy, src_header, point_format):
    """The header a chunked copy should be written with.

    Built from the source header, so the point format, extra bytes,
    scales, offsets and CRS VLRs all come across; laspy deepcopies it
    again at the writer, resets the counters and regrows the bounds
    per chunk. Two adjustments the source cannot carry:

    * the COPC VLRs are DROPPED. A copy written point-by-point is a
      plain LAZ, and laspy refuses outright ("Writing COPC is not
      supported") if the header still claims an octree -- which used
      to leave a 0-byte file where the delivery should be.
    * the point format is converted here rather than per chunk, so a
      zero-point source still produces the format that was asked for.
    """
    header = copy.deepcopy(src_header)
    if any(v.user_id == "copc" for v in header.vlrs):
        header.vlrs = laspy.vlrs.vlrlist.VLRList(
            [v for v in header.vlrs if v.user_id != "copc"])
    if point_format is None or point_format == header.point_format.id:
        return header
    empty = laspy.LasData(
        header=header,
        points=laspy.ScaleAwarePointRecord.zeros(0, header=header))
    return laspy.convert(empty, point_format_id=point_format).header


def stream_update(src, dst, update, *, fields=("x", "y", "z"),
                  chunk_size=DEFAULT_CHUNK, point_format=None,
                  progress=None):
    """Copy a cloud chunk by chunk, letting ``update`` rewrite fields.

    ``update(points, start)`` receives a dict of the requested
    ``fields`` for one chunk and that chunk's index in the file, and
    returns a dict of the fields to write back (``{}`` or None to
    leave the chunk alone). ``start`` is what lets a caller apply a
    per-point array it computed earlier without re-reading anything:
    ``values[start:start + n]``. Only the named fields change;
    everything else -- point format, extra bytes, scales, offsets, CRS
    records, EVLRs -- is carried across, because the output header IS
    the input header. Building a header by hand instead silently
    writes a DUPLICATE ExtraBytesVlr, which laspy reads back happily
    and other software may not.

    ``point_format`` converts on the way through (pf6 -> pf7 to gain
    RGB, say); the conversion happens per chunk, so it costs no extra
    memory.

    The write goes to a temporary file beside ``dst`` and is renamed
    into place only after the last chunk. A failure partway therefore
    leaves no output at all, rather than a truncated cloud that opens
    perfectly and is quietly missing its tail. Returns the number of
    points written.
    """
    laspy = _laspy()
    src_path, dst_path = Path(src), Path(dst)
    try:
        same = src_path.resolve() == dst_path.resolve()
    except OSError:
        same = False
    if same:
        raise ValueError(
            f"refusing to stream {src_path.name} onto itself: the source is "
            f"read chunk by chunk while the destination is being written, "
            f"so this would destroy the cloud it is reading")

    written = 0
    partial = dst_path.with_name(dst_path.name + ".partial")
    try:
        with laspy.open(src_path) as reader:
            _check_fields(reader.header, fields, src_path)
            total = int(reader.header.point_count)
            header = _output_header(laspy, reader.header, point_format)
            converting = header.point_format.id != reader.header.point_format.id
            evlrs = [v for v in (reader.evlrs or []) if v.user_id != "copc"]
            # laspy infers compression from the EXTENSION, and the temp
            # file's is ".partial" -- so without this a .laz output is
            # written as plain LAS bytes and renamed to the .laz name:
            # readable, but several times the size and not what the name
            # says. Say what is meant rather than letting a temporary
            # name decide the delivery's format.
            with laspy.open(partial, mode="w", header=header,
                            do_compress=dst_path.suffix.lower() == ".laz"
                            ) as writer:
                for chunk in reader.chunk_iterator(chunk_size):
                    size = len(chunk)
                    if converting:
                        holder = laspy.LasData(header=reader.header,
                                               points=chunk)
                        chunk = laspy.convert(
                            holder, point_format_id=header.point_format.id
                        ).points
                    changes = update(_extract(chunk, fields, src_path),
                                     written) or {}
                    for name, values in changes.items():
                        values = np.asarray(values)
                        if values.shape[0] != size:
                            raise ValueError(
                                f"update returned {values.shape[0]} values "
                                f"for {name!r} on a chunk of {size} points")
                        try:
                            chunk[name] = values
                        except (KeyError, AttributeError, ValueError) as exc:
                            raise ValueError(
                                f"{dst_path}: cannot write field {name!r} to "
                                f"point format {header.point_format.id}"
                            ) from exc
                    writer.write_points(chunk)
                    written += size
                    if progress is not None:
                        progress(written, total)
                # EVLRs hold the OGC WKT on many LAS 1.4 files, so
                # dropping them strips the delivery's georeferencing.
                # This must follow the last write_points: it finalizes
                # the point writer.
                if evlrs and header.version.minor >= 4:
                    writer.write_evlrs(laspy.vlrs.vlrlist.VLRList(evlrs))
        os.replace(partial, dst_path)
    except BaseException:
        Path(partial).unlink(missing_ok=True)
        raise
    return written


def copc_query(path, fields=FIELDS, *, bounds=None, resolution=None):
    """Points from a COPC file inside ``bounds``, at ``resolution``.

    ``bounds`` is ((min_e, min_n), (max_e, max_n)) or full 3D triples,
    and is CLAMPED to the file's own extent first: laspy converts the
    request into the file's scaled integer system with an unchecked
    int32 cast, so a box merely larger than the cloud can overflow and
    come back with zero points rather than everything.

    ``resolution`` (map units) reads only the octree levels at least
    that coarse -- an overview, for a preview or a first pass. It is
    not a sampling fraction: it maps to whole octree LEVELS, so a
    shallow tree offers few distinct answers and several different
    resolutions can return exactly the same points.

    MEMORY WARNING, and it is not a small one: a COPC query
    decompresses every octree NODE that overlaps the box and masks
    afterwards, so its cost tracks the nodes touched rather than the
    points returned. The coarse levels span the whole tile, so they
    are always touched. Measured on a 5M-point file, a query over 1%
    of the area decompressed 4.07M points to hand back 50k. Use
    ``resolution`` when full density is not needed, and do not assume
    a small box means a small read.
    """
    laspy = _laspy()
    info = cloud_info(path)
    if not info["is_copc"]:
        raise ValueError(
            f"{path} is not a COPC file (no copc VLR), so it carries no "
            f"octree to query. Read it with iter_points, or write a COPC "
            f"copy first -- laspy cannot: that needs pdal or untwine.")
    kwargs = {}
    if bounds is not None:
        mins = np.asarray(bounds[0], dtype=float)
        maxs = np.asarray(bounds[1], dtype=float)
        if mins.size == 2:
            mins = np.append(mins, info["mins"][2])
            maxs = np.append(maxs, info["maxs"][2])
        if np.any(maxs < mins):
            raise ValueError(f"bounds are inverted: {mins} .. {maxs}")
        mins = np.maximum(mins, info["mins"])
        maxs = np.minimum(maxs, info["maxs"])
        if np.any(maxs < mins):
            raise ValueError(
                f"the requested box does not overlap {Path(path).name} "
                f"(file extent {info['mins']} .. {info['maxs']})")
        kwargs["bounds"] = laspy.copc.Bounds(mins=mins, maxs=maxs)
    if resolution is not None:
        resolution = float(resolution)
        if not resolution > 0:
            raise ValueError(f"resolution must be positive map units, "
                             f"got {resolution}")
        kwargs["resolution"] = resolution
    with laspy.CopcReader.open(path) as reader:
        record = reader.query(**kwargs)
    return _extract(record, fields, path)


def split_by_strip(points):
    """Split a points dict into {point_source_id: points dict}.

    Strip identity rides on point_source_id per the LAS spec; a file
    where every point carries id 0 was never assigned strips, and this
    raises so the caller finds out now rather than in the overlap QA.
    """
    ids = points["point_source_id"]
    unique = np.unique(ids)
    if unique.size == 1 and unique[0] == 0:
        raise ValueError("every point has point_source_id 0: strips were never assigned")
    return {int(u): {k: v[ids == u] for k, v in points.items()} for u in unique}
