"""Streaming reads: identical answers, one chunk of memory.

The contract that matters is EQUALITY -- a streamed pass must return
what the whole-file read returns, bit for bit, or the two paths are
two different programs and the fast one is untrustworthy. Everything
else here guards a specific trap the laspy recon measured.
"""

import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from pyargus.formats import las as las_mod  # noqa: E402
from pyargus.qa import density as density_mod  # noqa: E402


def make_cloud(path, n=5000, point_format=6, seed=0, extra=True,
               psid=True):
    """A small cloud with the awkward parts: extra bytes, non-unit
    scales, a nonzero offset, real gps times."""
    rng = np.random.default_rng(seed)
    header = laspy.LasHeader(version="1.4", point_format=point_format)
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([600000.0, 3300000.0, 0.0])
    if extra:
        header.add_extra_dim(
            laspy.ExtraBytesParams(name="Amplitude", type=np.float32))
    las = laspy.LasData(header)
    las.x = 600000 + rng.uniform(0.0, 100.0, n)
    las.y = 3300000 + rng.uniform(0.0, 60.0, n)
    las.z = rng.uniform(0.0, 25.0, n)
    las.gps_time = rng.uniform(1e5, 2e5, n)
    las.intensity = rng.integers(0, 65535, n).astype(np.uint16)
    las.classification = rng.integers(1, 6, n).astype(np.uint8)
    if psid:
        las.point_source_id = rng.integers(1, 4, n).astype(np.uint16)
    if extra:
        las.Amplitude = rng.uniform(0, 10, n).astype(np.float32)
    las.write(str(path))
    return las


def test_cloud_info_reads_no_points(tmp_path):
    path = tmp_path / "c.las"
    make_cloud(path, n=1234)
    info = las_mod.cloud_info(path)
    assert info["point_count"] == 1234
    assert info["point_format"] == 6
    assert info["version"] == "1.4"
    assert info["extra_dims"] == ["Amplitude"]
    assert not info["is_copc"]
    assert np.allclose(info["scales"], 0.001)
    # the header's own bounds, not something recomputed from points
    pts = las_mod.read_points(path, fields=("x", "y", "z"))
    assert np.allclose(info["mins"][0], pts["x"].min(), atol=1e-3)
    assert np.allclose(info["maxs"][2], pts["z"].max(), atol=1e-3)


@pytest.mark.parametrize("chunk_size", [1, 7, 999, 5000, 100000])
def test_streamed_read_equals_whole_read_exactly(tmp_path, chunk_size):
    """Any chunk size, including one that does not divide the count
    and one larger than the file, must reassemble the same arrays."""
    path = tmp_path / "c.las"
    make_cloud(path, n=5000)
    fields = ("x", "y", "z", "gps_time", "intensity", "classification",
              "point_source_id")
    whole = las_mod.read_points(path, fields=fields)
    parts = list(las_mod.iter_points(path, fields=fields,
                                     chunk_size=chunk_size))
    assert sum(p["x"].size for p in parts) == 5000
    joined = {k: np.concatenate([p[k] for p in parts]) for k in fields}
    for name in fields:
        assert np.array_equal(whole[name], joined[name]), name
        assert whole[name].dtype == joined[name].dtype, name


def test_chunks_are_independent_copies(tmp_path):
    """laspy hands several fields back as views into its packed
    record; a chunk that aliased it would mutate under the next read
    and would pin the record besides."""
    path = tmp_path / "c.las"
    make_cloud(path, n=3000)
    chunks = list(las_mod.iter_points(path, fields=("gps_time", "z"),
                                      chunk_size=500))
    first = chunks[0]["gps_time"].copy()
    # holding every chunk at once must not have disturbed the earliest
    assert np.array_equal(chunks[0]["gps_time"], first)
    for chunk in chunks:
        for arr in chunk.values():
            assert arr.base is None, "chunk field aliases laspy's record"
    whole = las_mod.read_points(path, fields=("gps_time",))
    assert whole["gps_time"].base is None


def test_missing_field_refuses_the_same_way_in_both_paths(tmp_path):
    path = tmp_path / "c.las"
    make_cloud(path, n=100, point_format=6)     # pf6 has no red
    with pytest.raises(ValueError, match="no field 'red'"):
        las_mod.read_points(path, fields=("x", "red"))
    with pytest.raises(ValueError, match="no field 'red'"):
        list(las_mod.iter_points(path, fields=("x", "red")))
    with pytest.raises(ValueError, match="chunk_size"):
        list(las_mod.iter_points(path, fields=("x",), chunk_size=0))


def test_streamed_density_equals_whole_cloud_density(tmp_path):
    """The reason streaming is allowed to exist: same numbers."""
    path = tmp_path / "c.las"
    make_cloud(path, n=20000, seed=3)
    whole = las_mod.read_points(path, fields=("x", "y"))
    want, wx, wy = density_mod.density_grid(whole["x"], whole["y"], cell=5.0)
    info = las_mod.cloud_info(path)
    got, gx, gy = density_mod.density_grid_streamed(
        las_mod.iter_points(path, fields=("x", "y"), chunk_size=1000),
        info["mins"][:2], info["maxs"][:2], cell=5.0)
    assert np.array_equal(wx, gx) and np.array_equal(wy, gy)
    assert np.array_equal(want, got)
    assert got.sum() * 25.0 == 20000                  # every point counted


def test_streamed_density_grid_is_not_axis_folded(tmp_path):
    """A deliberately non-square extent: passing corners where
    grid_edges wants coordinates folds the two axes together, which a
    square test cannot see."""
    path = tmp_path / "c.las"
    make_cloud(path, n=4000, seed=9)              # 100 wide x 60 tall
    info = las_mod.cloud_info(path)
    got, gx, gy = density_mod.density_grid_streamed(
        las_mod.iter_points(path, fields=("x", "y"), chunk_size=500),
        info["mins"][:2], info["maxs"][:2], cell=10.0)
    assert gx.size != gy.size, (gx.size, gy.size)
    assert gx[0] <= info["mins"][0] and gx[-1] >= info["maxs"][0]
    assert gy[0] <= info["mins"][1] and gy[-1] >= info["maxs"][1]
    assert got.shape == (gx.size - 1, gy.size - 1)


def test_stream_update_preserves_everything_it_did_not_touch(tmp_path):
    src = tmp_path / "src.las"
    dst = tmp_path / "dst.las"
    make_cloud(src, n=4000, seed=5)
    before = las_mod.read_points(src, fields=("x", "y", "z", "gps_time",
                                              "intensity", "Amplitude"))
    n = las_mod.stream_update(src, dst, lambda p, _s: {"z": p["z"] + 2.5},
                              fields=("z",), chunk_size=700)
    assert n == 4000
    after = las_mod.read_points(dst, fields=("x", "y", "z", "gps_time",
                                             "intensity", "Amplitude"))
    for name in ("x", "y", "gps_time", "intensity", "Amplitude"):
        assert np.array_equal(before[name], after[name]), name
    assert np.allclose(after["z"] - before["z"], 2.5, atol=1e-3)
    src_info, dst_info = las_mod.cloud_info(src), las_mod.cloud_info(dst)
    assert dst_info["extra_dims"] == src_info["extra_dims"]
    assert np.allclose(dst_info["scales"], src_info["scales"])
    assert np.allclose(dst_info["offsets"], src_info["offsets"])
    # bounds are regrown from what was written, not copied
    assert np.isclose(dst_info["mins"][2], src_info["mins"][2] + 2.5,
                      atol=1e-3)
    # exactly ONE ExtraBytesVlr: a hand-built header writes two, which
    # laspy reads back happily and other software may not
    with laspy.open(dst) as reader:
        assert sum(1 for v in reader.header.vlrs if v.record_id == 4) == 1


def test_stream_update_start_index_addresses_the_whole_file(tmp_path):
    """The start index is what lets a caller apply a precomputed
    per-point array; off-by-one there would scramble the cloud."""
    src = tmp_path / "src.las"
    dst = tmp_path / "dst.las"
    make_cloud(src, n=2500, seed=11)
    marks = np.arange(2500, dtype=float) / 1000.0

    def place(points, start):
        assert points["z"].size <= 400
        return {"z": marks[start:start + points["z"].size]}

    las_mod.stream_update(src, dst, place, fields=("z",), chunk_size=400)
    got = las_mod.read_points(dst, fields=("z",))["z"]
    assert np.allclose(got, marks, atol=1e-3)


def test_stream_update_converts_point_format_in_flight(tmp_path):
    src = tmp_path / "src.las"
    dst = tmp_path / "dst.las"
    make_cloud(src, n=3000, point_format=6, seed=7)   # pf6: no RGB
    before = las_mod.read_points(src, fields=("gps_time", "Amplitude"))

    def paint(points, start):
        n = points["x"].size
        return {"red": np.full(n, 111, dtype=np.uint16),
                "green": np.full(n, 222, dtype=np.uint16),
                "blue": np.full(n, 333, dtype=np.uint16)}

    las_mod.stream_update(src, dst, paint, fields=("x",), point_format=7,
                          chunk_size=512)
    info = las_mod.cloud_info(dst)
    assert info["point_format"] == 7
    assert info["extra_dims"] == ["Amplitude"]
    after = las_mod.read_points(dst, fields=("red", "green", "blue",
                                             "gps_time", "Amplitude"))
    assert np.all(after["red"] == 111) and np.all(after["blue"] == 333)
    for name in ("gps_time", "Amplitude"):
        assert np.array_equal(before[name], after[name]), name


def test_stream_update_refuses_a_field_the_format_lacks(tmp_path):
    src = tmp_path / "src.las"
    make_cloud(src, n=200, point_format=6)
    with pytest.raises(ValueError, match="cannot write field 'red'"):
        las_mod.stream_update(
            src, tmp_path / "d.las",
            lambda p, _s: {"red": np.zeros(p["x"].size, dtype=np.uint16)},
            fields=("x",))


def test_copc_query_refuses_a_plain_las(tmp_path):
    """laspy cannot add an octree to a file that has none, and saying
    so is better than a confusing failure inside CopcReader."""
    path = tmp_path / "c.las"
    make_cloud(path, n=100)
    assert las_mod.cloud_info(path)["is_copc"] is False
    with pytest.raises(ValueError, match="not a COPC file"):
        las_mod.copc_query(path, bounds=((0, 0), (1, 1)))


# --- what the ninth review panel found, pinned -----------------------

def test_stale_header_refuses_instead_of_dropping_points(tmp_path):
    """np.histogram2d DISCARDS samples outside its explicit bins. With
    the edges fixed from a header that no longer describes its own
    points -- a clip or a reproject that never rewrote min/max -- the
    streamed grid would be computed from a subset while printing a
    perfectly believable density on the suite's own QA metric."""
    import struct

    path = tmp_path / "c.las"
    make_cloud(path, n=20000, seed=21)
    raw = bytearray(path.read_bytes())
    struct.pack_into("<d", raw, 179, 600050.0)   # max_x: half the true span
    path.write_bytes(bytes(raw))

    info = las_mod.cloud_info(path)
    assert info["maxs"][0] == 600050.0
    with pytest.raises(ValueError, match="fall outside the declared extent"):
        density_mod.density_grid_streamed(
            las_mod.iter_points(path, fields=("x", "y")),
            info["mins"][:2], info["maxs"][:2], cell=5.0)

    # and the way out: take the extent from the points themselves
    lo, hi = density_mod.scan_extent(
        las_mod.iter_points(path, fields=("x", "y")))
    grid, _, _ = density_mod.density_grid_streamed(
        las_mod.iter_points(path, fields=("x", "y")), lo, hi, cell=5.0)
    assert round(grid.sum() * 25) == 20000


def test_scan_extent_matches_the_points(tmp_path):
    path = tmp_path / "c.las"
    make_cloud(path, n=5000, seed=22)
    pts = las_mod.read_points(path, fields=("x", "y"))
    lo, hi = density_mod.scan_extent(
        las_mod.iter_points(path, fields=("x", "y"), chunk_size=321))
    assert np.isclose(lo[0], pts["x"].min()) and np.isclose(hi[0], pts["x"].max())
    assert np.isclose(lo[1], pts["y"].min()) and np.isclose(hi[1], pts["y"].max())


def test_evlrs_survive_a_streamed_copy(tmp_path):
    """LAS 1.4 allows the OGC WKT in an EVLR, and many writers put it
    there. Dropping EVLRs strips the georeferencing off the delivery
    that align --write and colorize --out produce."""
    pyproj = pytest.importorskip("pyproj")
    src = tmp_path / "src.las"
    make_cloud(src, n=2000, seed=23)
    las = laspy.read(str(src))
    las.header.global_encoding.wkt = True
    las.evlrs = laspy.vlrs.vlrlist.VLRList(
        [laspy.vlrs.known.WktCoordinateSystemVlr(
            pyproj.CRS.from_epsg(6447).to_wkt())])
    las.write(str(src))
    assert las_mod.cloud_info(src)["crs"] is not None

    dst = tmp_path / "dst.las"
    las_mod.stream_update(src, dst, lambda p, _s: {"z": p["z"]},
                          fields=("z",), chunk_size=500)
    crs = las_mod.cloud_info(dst)["crs"]
    assert crs is not None and "Georgia West" in crs.name


def test_stream_update_refuses_to_overwrite_its_own_source(tmp_path):
    """The source is read chunk by chunk WHILE the destination is
    written; the same path destroys the cloud mid-read and reports
    success."""
    path = tmp_path / "c.las"
    make_cloud(path, n=1000, seed=24)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="onto itself"):
        las_mod.stream_update(path, path, lambda p, _s: {"z": p["z"]},
                              fields=("z",))
    assert path.read_bytes() == before


def test_a_failed_write_leaves_nothing_at_the_destination(tmp_path):
    """A truncated cloud opens perfectly and is quietly missing its
    tail, which is worse than no file at all."""
    src = tmp_path / "src.las"
    make_cloud(src, n=5000, seed=25)
    dst = tmp_path / "dst.las"

    def explode(points, start):
        if start >= 2000:
            raise RuntimeError("deliberate mid-stream failure")
        return {"z": points["z"]}

    with pytest.raises(RuntimeError, match="deliberate"):
        las_mod.stream_update(src, dst, explode, fields=("z",),
                              chunk_size=1000)
    assert not dst.exists()
    assert list(tmp_path.glob("dst.las*")) == []


def test_empty_source_still_honours_the_requested_format(tmp_path):
    src = tmp_path / "empty.las"
    laspy.LasData(laspy.LasHeader(version="1.4", point_format=6)).write(
        str(src))
    dst = tmp_path / "dst.las"
    written = las_mod.stream_update(src, dst, lambda p, _s: {},
                                    fields=("x",), point_format=7)
    assert written == 0
    assert las_mod.cloud_info(dst)["point_format"] == 7


def test_zero_point_file_still_refuses_a_missing_field(tmp_path):
    """The refusal must come from the HEADER: a per-record check never
    runs on an empty file, so streaming and whole-file consumers would
    disagree about the same cloud."""
    src = tmp_path / "empty.las"
    laspy.LasData(laspy.LasHeader(version="1.4", point_format=6)).write(
        str(src))
    with pytest.raises(ValueError, match="no field 'red'"):
        list(las_mod.iter_points(src, fields=("x", "red")))
    with pytest.raises(ValueError, match="no field 'red'"):
        las_mod.read_points(src, fields=("x", "red"))


def test_update_length_mismatch_is_named_not_broadcast(tmp_path):
    """A length-1 array would broadcast silently over a whole chunk."""
    src = tmp_path / "src.las"
    make_cloud(src, n=1000, seed=26)
    with pytest.raises(ValueError, match="returned 1 values"):
        las_mod.stream_update(src, tmp_path / "dst.las",
                              lambda p, _s: {"z": np.zeros(1)},
                              fields=("z",))


@pytest.mark.parametrize("suffix, compressed", [(".laz", True), (".las", False)])
def test_the_output_format_follows_the_name_it_was_given(tmp_path, suffix,
                                                         compressed):
    """laspy reads a compression flag from the header, so an
    uncompressed file under a .laz name round-trips perfectly and no
    equality test can see it -- while the delivery is several times the
    size it should be and its name misstates its format. The temporary
    file this writes through is named `<out>.partial`, whose suffix is
    not `.laz`, so the intent has to be stated rather than inferred."""
    src = tmp_path / "src.las"
    make_cloud(src, n=4000, seed=31)
    dst = tmp_path / ("out" + suffix)
    las_mod.stream_update(src, dst, lambda p, _s: None, fields=("z",))
    with laspy.open(dst) as reader:
        assert reader.header.are_points_compressed is compressed
    before = las_mod.read_points(src)
    after = las_mod.read_points(dst)
    for name, values in before.items():
        assert np.array_equal(after[name], values), name
