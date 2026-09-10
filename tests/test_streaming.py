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
