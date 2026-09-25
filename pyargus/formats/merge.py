"""Join clouds into one, or refuse: the concatenation a surface needs.

`dtm`, `contours` and `qa-report` each take ONE cloud, and a delivery
arrives as one file per flight line, so a site surface begins with a
join. The join is where a delivery can be quietly ruined. Two files
whose scales, offsets, point format or extra dimensions differ do not
describe their points in the same terms: writing one file's records
under the other's header reinterprets the bytes, and the result opens
perfectly and is wrong. Every one of those is a refusal here, decided
from the headers before a byte is written.

Point source ids are the other trap, and a quieter one. Strip-to-strip
QA reads them to tell the strips apart, so two files that both number
their points 1 become a single strip the moment they are joined, and
the overlap check silently compares a strip with itself. So the ids
are scanned first -- one pass over that field alone -- and a collision
refuses unless the caller says ``psid_from_file``, which renumbers by
file order and records what each file used to carry. The collision is
checked between every PAIR: the first version took the intersection of
all inputs, which two colliding lines and one innocent third reduce to
nothing, so a three-line delivery disabled the check that exists for
it.

Three more things must agree and each was found missing by review, all
of them silent. The GPS time base: week time and adjusted standard GPS
time differ by about a billion seconds, and one cloud declaring one of
them over points holding both is read as consistent by every later
tool. The extra dimensions, by TYPE and not only by name, because
under ``reframe`` the records are rebuilt against the first file's
header and numpy casts a float32 into a uint8 slot without a word. And
the point count: a truncated cloud, or one whose header went stale,
used to merge short and exit 0.

Scales and offsets are the subtle one. LAS stores each coordinate as
a 32-bit integer and recovers it as ``value * scale + offset``, so two
files written with different offsets use the SAME integer for two
different places -- the vendor gives each flight line its own offset
as a matter of course. Copying one file's records under the other's
header would move it bodily (more than 2,000 ft on the delivery this
was written for). That refuses by default. ``reframe`` is the way
through: it restates every point in one frame, which preserves the
real-world coordinate to within half a scale unit and changes only the
integers used to store it. The largest change is measured and recorded rather
than assumed.

Extended records are the third trap. An EVLR is where a vendor puts
PER-FILE quality statistics -- both lines of a real two-line delivery
arrived with a 100 KB ``QCS/157`` record of their own -- and a record
describing one flight line does not describe a merge of several. The
output carries the FIRST cloud's, to match the header it also carries,
and any input whose records differ is NAMED in the log rather than
quietly discarded.

What it does NOT do: reproject, re-order, deduplicate, or reconcile
two different CRS. Those are decisions about the data, and the command
that makes them silently is the one you find out about three
deliverables later. A COPC index cannot survive a point-by-point copy
either; the output is plain LAS/LAZ.
"""

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from pyargus.analysis_records import analysis_job, finish
from pyargus.formats import las as las_mod


def _projection_records(path):
    """A fingerprint of the raw projection records, parsed or not.

    ``cloud_info`` hands back a PARSED CRS and swallows the exception
    when it cannot make one, so an unreadable projection record and a
    file that declares no projection at all both arrive as ``None``.
    pyproj is an optional extra in this project, so on an install
    without it that is EVERY file, and comparing the parsed objects
    then says two clouds agree because neither could be read.

    The bytes can be compared without understanding them. Absent is
    still absent -- two clouds that declare nothing must still merge --
    but two clouds carrying DIFFERENT records do not pass as equal just
    because the library that reads them is missing.
    """
    laspy = las_mod._laspy()
    seen = []
    with laspy.open(path) as reader:
        records = list(reader.header.vlrs or []) + list(reader.evlrs or [])
    for record in records:
        if record.user_id != "LASF_Projection":
            continue
        try:
            payload = bytes(record.record_data_bytes())
        except Exception:                        # unserialisable: use repr
            payload = repr(record).encode("utf-8", "replace")
        seen.append((int(record.record_id), hashlib.sha256(payload).hexdigest()))
    return tuple(sorted(seen))


def _extra_dimension_types(path):
    """Extra dimensions as (name, dtype), not name alone.

    Under ``reframe`` the records are rebuilt against the first file's
    header, so a float32 written into a uint8 slot is cast by numpy
    without a word: 12.75 arrives as 12.
    """
    laspy = las_mod._laspy()
    with laspy.open(path) as reader:
        fmt = reader.header.point_format
        return tuple(sorted((dim.name, str(dim.dtype))
                            for dim in fmt.extra_dimensions))


def _signature(path):
    """What must agree between two clouds, read from the header alone."""
    info = las_mod.cloud_info(path)
    laspy = las_mod._laspy()
    with laspy.open(path) as reader:
        encoding = reader.header.global_encoding
        gps_time = int(encoding.gps_time_type)
    return {"point_format": info["point_format"], "version": info["version"],
            "scales": tuple(np.asarray(info["scales"]).tolist()),
            "offsets": tuple(np.asarray(info["offsets"]).tolist()),
            "extra_dims": _extra_dimension_types(path),
            "gps_time_type": gps_time,
            "crs": info["crs"], "crs_records": _projection_records(path)}


def _disagreement(first, other, a, b, reframe=False):
    """The one sentence that says which term they disagree on."""
    if first["gps_time_type"] != other["gps_time_type"]:
        names = {0: "GPS week time", 1: "adjusted standard GPS time"}
        unknown = "an unknown GPS time base"
        theirs = names.get(other["gps_time_type"], unknown)
        ours = names.get(first["gps_time_type"], unknown)
        return (f"{b.name} keeps {theirs} and {a.name} keeps {ours}: the two "
                f"differ by about a billion seconds, so merging them gives "
                f"one cloud whose gps_time means two different things, and "
                f"every trajectory match, drift correction and time-based "
                f"check downstream reads it as one. Nothing written.")
    for key, label in (("point_format", "point format"),
                       ("version", "LAS version"),
                       ("scales", "coordinate scale"),
                       ("offsets", "coordinate offset"),
                       ("extra_dims", "extra dimension set")):
        if first[key] != other[key]:
            way_out = (" Pass --reframe to restate every point in one "
                       "frame instead, which keeps each coordinate to "
                       "within half a scale unit."
                       if key in ("scales", "offsets") and not reframe else "")
            if key in ("scales", "offsets") and reframe:
                continue
            return (f"{b.name} has a different {label} from {a.name} "
                    f"({other[key]} against {first[key]}): the two files do "
                    f"not describe their points in the same terms, and "
                    f"writing one under the other's header would "
                    f"reinterpret its records rather than fail.{way_out} "
                    f"Nothing written.")
    one, two = first["crs"], other["crs"]
    if one is not None and two is not None:
        if not one.equals(two):
            return (f"{b.name} and {a.name} declare different CRS "
                    f"({two.name} against {one.name}): merging them would put "
                    f"two coordinate systems in one file. Reproject "
                    f"deliberately first. Nothing written.")
        return None
    # One or both could not be parsed. Absent is not a disagreement --
    # plenty of real clouds declare no projection and must still join --
    # but two DIFFERENT projection records are, whether or not the
    # library that reads them is installed. See _projection_records.
    if first["crs_records"] == other["crs_records"]:
        return None
    if one is not None or two is not None:
        named, blank = ((one.name, b.name) if one is not None
                        else (two.name, a.name))
        return (f"{blank} does not declare the CRS that the other cloud "
                f"declares ({named}): merging them would put points of "
                f"unknown provenance under a projection record that claims "
                f"to describe them. Say what {blank} is in, or reproject "
                f"deliberately first. Nothing written.")
    return (f"{a.name} and {b.name} carry DIFFERENT projection records and "
            f"neither could be read, so pyArgus cannot confirm they are the "
            f"same CRS -- and merging them would put two coordinate systems "
            f"in one file. Reading them needs pyproj: install the crs extra. "
            f"Nothing written.")


def merge_clouds(paths, out, *, psid_from_file=False, reframe=False,
                 force=False, chunk_size=las_mod.DEFAULT_CHUNK, log=print):
    """Concatenate ``paths`` into ``out``, in the order given.

    Returns a dict of what happened. The output carries the FIRST
    file's header -- its point format, extra bytes, scales, offsets and
    CRS records -- and every point of every input in order; laspy
    regrows the bounds and the count as the chunks are written.
    """
    paths = [Path(p) for p in paths]
    out = Path(out)
    if len(paths) < 2:
        raise ValueError(f"merging needs at least two clouds, got "
                         f"{len(paths)}")
    for path in paths:
        if not path.is_file():
            raise ValueError(f"{path} does not exist")
        if path.resolve() == out.resolve():
            raise ValueError(f"refusing to write the merge onto its own "
                             f"input {path.name}; --out must be a new file")
    if len(set(p.resolve() for p in paths)) != len(paths):
        raise ValueError("the same cloud was given twice; every point would "
                         "appear in the output twice")
    if out.exists() and not force:
        raise FileExistsError(f"Output already exists: {out}; pass force to "
                              f"replace it")

    first = _signature(paths[0])
    others = [_signature(p) for p in paths[1:]]
    for path, other in zip(paths[1:], others):
        problem = _disagreement(first, other, paths[0], path, reframe)
        if problem:
            raise ValueError(problem)
    frames = {(s["scales"], s["offsets"]) for s in [first] + others}
    reframe = reframe and len(frames) > 1

    settings = dict(sources=[str(p.resolve()) for p in paths],
                    psid_from_file=psid_from_file, reframe=reframe)
    with analysis_job("merge", out, settings, inputs=paths, log=log) as record:
        # --- pass 1: the strip ids, before anything is written --------
        seen, counts = [], []
        for path in paths:
            ids, n = set(), 0
            for chunk in las_mod.iter_points(path, fields=("point_source_id",),
                                             chunk_size=chunk_size):
                values = np.asarray(chunk["point_source_id"])
                ids.update(int(v) for v in np.unique(values))
                n += values.size
            seen.append(sorted(ids))
            counts.append(n)
            claimed = int(las_mod.cloud_info(path)["point_count"])
            if n != claimed:
                raise ValueError(
                    f"{path.name} holds {n:,} points but its header claims "
                    f"{claimed:,}: the file is truncated, or its header went "
                    f"stale. Merging it would put a short cloud into the "
                    f"delivery and report success. Nothing written.")
        # Every PAIR, not the intersection of all of them. Two lines both
        # numbering their points 1 and a third numbering its 3 have an
        # EMPTY intersection, so the old check saw no collision and the
        # two real strips silently became one.
        clash = []
        for i in range(len(seen)):
            for j in range(i + 1, len(seen)):
                shared = sorted(set(seen[i]) & set(seen[j]))
                if shared:
                    clash.append((paths[i].name, paths[j].name, shared))
        if clash and not psid_from_file:
            worst = "; ".join(f"{one} and {two} both use {ids}"
                              for one, two, ids in clash[:3])
            raise ValueError(
                f"these clouds share point_source_id values ({worst}): strip "
                f"QA reads that field to tell the strips apart, so merging "
                f"them as they are would silently make one strip of several "
                f"and compare a strip with itself. Pass --psid-from-file to "
                f"number the strips by file order instead. Nothing written.")
        if psid_from_file and len(paths) > 65535:
            raise ValueError("point_source_id is 16-bit; too many files")

        for path, ids, n in zip(paths, seen, counts):
            log(f"source:  {path.name}: {n:,} points, point_source_id "
                f"{ids if len(ids) <= 4 else str(ids[:4]) + '...'}")
        if psid_from_file:
            log(f"renumber: point_source_id becomes 1..{len(paths)} by file "
                f"order (the originals are in the sidecar)")

        # --- pass 2: the copy -----------------------------------------
        laspy = las_mod._laspy()
        from laspy.point.record import ScaleAwarePointRecord

        partial = out.with_name(out.name + ".partial")
        written, shift = 0, 0.0
        try:
            with laspy.open(paths[0]) as reader:
                header = las_mod._output_header(laspy, reader.header, None)
            if reframe:
                header = _one_frame(header, paths, log)
            records, dropped = _extended_records(paths, log)
            with laspy.open(partial, mode="w", header=header,
                            do_compress=out.suffix.lower() == ".laz"
                            ) as writer:
                for index, path in enumerate(paths, start=1):
                    with laspy.open(path) as reader:
                        for chunk in reader.chunk_iterator(chunk_size):
                            if reframe:
                                chunk, moved = _restate(
                                    chunk, header, ScaleAwarePointRecord)
                                shift = max(shift, moved)
                            if psid_from_file:
                                chunk.point_source_id = np.full(
                                    len(chunk), index, dtype=np.uint16)
                            writer.write_points(chunk)
                            written += len(chunk)
                if len(records) and header.version.minor >= 4:
                    writer.write_evlrs(records)
            expected = sum(counts)
            if written != expected:
                raise ValueError(f"wrote {written:,} points for {expected:,} "
                                 f"read across {len(paths)} clouds")
            os.replace(partial, out)
        except BaseException:
            Path(partial).unlink(missing_ok=True)
            raise

        sources = [{"path": str(p.resolve()), "points": n,
                    "first_index": sum(counts[:i]),
                    "point_source_ids": [i + 1] if psid_from_file else ids,
                    "original_point_source_ids": ids}
                   for i, (p, n, ids) in enumerate(zip(paths, counts, seen))]
        results = {"points": written, "clouds": len(paths),
                   "renumbered": bool(psid_from_file),
                   "reframed": bool(reframe),
                   "max_coordinate_shift": round(float(shift), 9),
                   "extended_records": len(records),
                   "extended_records_from": paths[0].name,
                   "extended_records_dropped": dropped}
        if reframe:
            log(f"reframe: every point restated in one frame; the largest "
                f"coordinate moved {shift:.6f} map units")
        sidecar = out.with_name(out.name + ".merge.json")
        sidecar.write_text(json.dumps({**results, "sources": sources},
                                      indent=1), encoding="utf-8")
        log(f"merged:  {written:,} points from {len(paths)} clouds")
        log(f"sidecar: {sidecar}")
        log(f"wrote:   {out}")
        finish(record, results, outputs=[out, sidecar])
        return {**results, "sources": sources}


def _extended_records(paths, log):
    """The first cloud's extended records, and a word about the rest.

    The output carries the first cloud's header, so it carries the
    first cloud's extended records too. The trap this closes: an EVLR
    is where a vendor puts PER-FILE quality statistics -- both lines of
    a real two-line delivery arrived with a 100 KB ``QCS/157`` record
    of their own -- and a record describing one flight line does not
    describe a merge of several. Taking one of them silently puts one
    line's QC on the whole cloud, where the next reader has no way to
    know. The ones left behind are named instead.

    COPC records go regardless: a COPC index cannot survive a
    point-by-point copy, so keeping its records would describe an index
    the output does not have.
    """
    laspy = las_mod._laspy()
    from laspy.vlrs.vlrlist import VLRList

    def read(path):
        with laspy.open(path) as reader:
            return [v for v in (reader.evlrs or []) if v.user_id != "copc"]

    def seen(records):
        return [(v.user_id, v.record_id, bytes(v.record_data_bytes()))
                for v in records]

    keep = read(paths[0])
    signature = seen(keep)
    dropped = [p.name for p in paths[1:] if seen(read(p)) != signature]
    if dropped:
        log(f"evlr:    kept {paths[0].name}'s {len(keep)} extended record(s); "
            f"{', '.join(dropped)} carries different ones, DROPPED -- a "
            f"vendor record describing one cloud does not describe a merge "
            f"of several")
    return VLRList(keep), dropped


def _one_frame(header, paths, log):
    """A scale and offset that every input fits inside.

    The finest scale among the inputs is kept, so nothing is coarsened,
    and the offset moves to the union's own minimum -- which is also
    what keeps the 32-bit integers in range, since they count scale
    units from the offset.
    """
    infos = [las_mod.cloud_info(p) for p in paths]
    # A cloud with no points has no bounds to contribute: its header
    # minima are whatever the writer left there, usually (0, 0, 0), and
    # taking the union with them drags the offset to the origin. On
    # state plane coordinates that is billions of scale units, and the
    # refusal that follows blames the extent instead of the empty file.
    empty = [p.name for p, i in zip(paths, infos)
             if int(i["point_count"]) == 0]
    if empty:
        raise ValueError(
            f"{', '.join(empty)} holds no points, so it has no bounds to "
            f"contribute to a common frame -- its header minima would drag "
            f"the offset to the origin. Leave it out of the merge. Nothing "
            f"written.")
    scales = np.min([np.asarray(i["scales"], float) for i in infos], axis=0)
    mins = np.min([np.asarray(i["mins"], float) for i in infos], axis=0)
    maxs = np.max([np.asarray(i["maxs"], float) for i in infos], axis=0)
    span = (maxs - mins) / scales
    if np.any(span >= 2 ** 31 - 1):
        axis = "xyz"[int(np.argmax(span))]
        raise ValueError(
            f"no single frame can hold these clouds: at a scale of "
            f"{scales[int(np.argmax(span))]:g} the {axis} extent needs "
            f"{span.max():,.0f} steps and a LAS coordinate is a 32-bit "
            f"integer (2,147,483,647). Write them at a coarser scale, or "
            f"keep the clouds apart. Nothing written.")
    header.scales = scales
    header.offsets = mins
    log(f"reframe: one frame for {len(paths)} clouds -- scale "
        f"{tuple(round(float(s), 9) for s in scales)}, offset "
        f"{tuple(round(float(o), 3) for o in mins)}")
    return header


def _restate(chunk, header, record_type):
    """The same points, stored against ``header``'s scale and offset.

    Every field but X, Y and Z is copied verbatim; the coordinates go
    through their real-world values, so what changes is the integer
    used to store a point, not where the point is. Returns the record
    and the largest distance any coordinate moved.
    """
    new = record_type.zeros(len(chunk), header=header)
    for name in chunk.array.dtype.names:
        if name not in ("X", "Y", "Z"):
            new.array[name] = chunk.array[name]
    for axis in ("x", "y", "z"):
        setattr(new, axis, np.asarray(getattr(chunk, axis)))
    moved = max(float(np.max(np.abs(np.asarray(getattr(new, a))
                                    - np.asarray(getattr(chunk, a)))))
                for a in ("x", "y", "z")) if len(chunk) else 0.0
    return new, moved
