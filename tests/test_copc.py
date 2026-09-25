"""COPC: written by pdal, queried by laspy.

laspy reads COPC and cannot write it, so these tests skip entirely
when no pdal is reachable -- the suite must stay green on a machine
that has never heard of it. What they pin is the part that bites:
pdal's COPC writer drops extra dimensions in SILENCE unless told
otherwise, so the delivery's Amplitude/Reflectance/Deviation would
vanish with no error at all.
"""

import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from pyargus.formats import copc as copc_mod  # noqa: E402
from pyargus.formats import las as las_mod  # noqa: E402

pdal = copc_mod.find_pdal()
needs_pdal = pytest.mark.skipif(pdal is None,
                                reason="no pdal executable found")


def make_cloud(path, n=120_000, seed=0, extra=True):
    rng = np.random.default_rng(seed)
    header = laspy.LasHeader(version="1.4", point_format=6)
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([600000.0, 3300000.0, 0.0])
    if extra:
        header.add_extra_dim(
            laspy.ExtraBytesParams(name="Amplitude", type=np.float32))
    las = laspy.LasData(header)
    las.x = 600000 + rng.uniform(0.0, 1000.0, n)
    las.y = 3300000 + rng.uniform(0.0, 1000.0, n)
    las.z = rng.uniform(0.0, 100.0, n)
    las.gps_time = rng.uniform(1e5, 2e5, n)
    las.classification = rng.integers(1, 6, n).astype(np.uint8)
    if extra:
        las.Amplitude = rng.uniform(0, 10, n).astype(np.float32)
    las.write(str(path))
    return n


def test_find_pdal_reports_absence_rather_than_guessing(tmp_path,
                                                        monkeypatch):
    monkeypatch.setenv("PDAL_EXE", str(tmp_path / "nope.exe"))
    monkeypatch.setattr(copc_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(copc_mod, "_QGIS_GLOBS", ())
    assert copc_mod.find_pdal() is None
    with pytest.raises(ValueError, match="needs pdal"):
        copc_mod.write_copc(tmp_path / "a.las", tmp_path / "b.copc.laz")


def test_copc_naming_is_enforced(tmp_path):
    src = tmp_path / "src.las"
    make_cloud(src, n=100)
    with pytest.raises(ValueError, match=r"\*.copc.laz"):
        copc_mod.write_copc(src, tmp_path / "out.laz")


def test_copc_query_refuses_a_plain_las(tmp_path):
    src = tmp_path / "src.las"
    make_cloud(src, n=100)
    with pytest.raises(ValueError, match="not a COPC file"):
        las_mod.copc_query(src, bounds=((0, 0), (1, 1)))


@needs_pdal
def test_copc_round_trip_keeps_extra_dims_and_crs(tmp_path):
    pyproj = pytest.importorskip("pyproj")
    src = tmp_path / "src.las"
    n = make_cloud(src, n=120_000, seed=2)
    # give it a CRS so the forward=all path is exercised
    las = laspy.read(str(src))
    las.header.add_crs(pyproj.CRS.from_epsg(6447))
    las.write(str(src))

    dst = tmp_path / "out.copc.laz"
    result = copc_mod.write_copc(src, dst)
    assert result["point_count"] == n
    # the silent-drop trap: without --writers.copc.extra_dims this is []
    assert result["extra_dims"] == ["Amplitude"]
    assert result["crs"] and "Georgia West" in result["crs"]

    info = las_mod.cloud_info(dst)
    assert info["is_copc"] and info["point_count"] == n
    # a COPC file is still an ordinary LAZ to a sequential reader
    total = sum(c["x"].size for c in
                las_mod.iter_points(dst, fields=("x",)))
    assert total == n


@needs_pdal
def test_copc_bbox_query_returns_only_what_it_should(tmp_path):
    src = tmp_path / "src.las"
    n = make_cloud(src, n=120_000, seed=4)
    dst = tmp_path / "out.copc.laz"
    copc_mod.write_copc(src, dst)

    box = ((600400.0, 3300400.0), (600500.0, 3300500.0))
    got = las_mod.copc_query(dst, fields=("x", "y", "Amplitude"),
                             bounds=box)
    assert got["x"].size > 0
    assert (got["x"] >= box[0][0]).all() and (got["x"] <= box[1][0]).all()
    assert (got["y"] >= box[0][1]).all() and (got["y"] <= box[1][1]).all()
    assert got["Amplitude"].size == got["x"].size
    # a hundredth of the tile area, so roughly a hundredth of the points
    expected = n / 100
    assert 0.6 * expected < got["x"].size < 1.6 * expected


@needs_pdal
def test_copc_resolution_snaps_to_octree_levels(tmp_path):
    """``resolution`` is not a continuous knob: it maps to a set of
    octree LEVELS, so a shallow tree offers few distinct answers and
    several resolutions return exactly the same points. Measured, and
    pinned so nobody reads the parameter as a sampling fraction."""
    src = tmp_path / "src.las"
    n = make_cloud(src, n=120_000, seed=6)
    dst = tmp_path / "out.copc.laz"
    copc_mod.write_copc(src, dst)

    counts = [las_mod.copc_query(dst, fields=("x",),
                                 resolution=r)["x"].size
              for r in (50.0, 20.0, 5.0, 1.0)]
    # non-increasing as the request gets coarser, and never more than
    # the cloud
    assert counts == sorted(counts), counts
    assert counts[-1] <= n
    assert counts[0] < n, "the coarsest level should drop something"
    full = las_mod.copc_query(dst, fields=("x",))["x"].size
    assert full == n


@needs_pdal
def test_streaming_out_of_a_copc_source_works(tmp_path):
    """laspy refuses to WRITE a header that still claims an octree, so
    a COPC source used to abort with a raw NotImplementedError and
    leave a 0-byte file -- meaning `pyargus copc` produced clouds the
    rest of the suite could not then process."""
    src = tmp_path / "src.las"
    n = make_cloud(src, n=120_000, seed=8)
    copc = tmp_path / "out.copc.laz"
    copc_mod.write_copc(src, copc)
    assert las_mod.cloud_info(copc)["is_copc"]

    dst = tmp_path / "shifted.laz"
    written = las_mod.stream_update(copc, dst,
                                    lambda p, _s: {"z": p["z"] + 1.0},
                                    fields=("z",))
    assert written == n
    out = las_mod.cloud_info(dst)
    # the copy is a plain LAZ: an octree cannot survive a point-by-point
    # rewrite, and claiming one it does not have would be a lie
    assert not out["is_copc"]
    assert out["extra_dims"] == ["Amplitude"]


@needs_pdal
def test_oversized_bounds_do_not_come_back_empty(tmp_path):
    """laspy converts the requested box into the file's scaled integer
    system with an unchecked int32 cast, so a box merely LARGER than
    the cloud could overflow and return zero points instead of
    everything."""
    src = tmp_path / "src.las"
    n = make_cloud(src, n=120_000, seed=9)
    dst = tmp_path / "out.copc.laz"
    copc_mod.write_copc(src, dst)

    got = las_mod.copc_query(dst, fields=("x",),
                             bounds=((-1e9, -1e9), (1e9, 1e9)))
    assert got["x"].size == n


@needs_pdal
def test_a_box_that_misses_the_cloud_refuses(tmp_path):
    src = tmp_path / "src.las"
    make_cloud(src, n=20_000, seed=10)
    dst = tmp_path / "out.copc.laz"
    copc_mod.write_copc(src, dst)
    with pytest.raises(ValueError, match="does not overlap"):
        las_mod.copc_query(dst, fields=("x",),
                           bounds=((0.0, 0.0), (10.0, 10.0)))
    with pytest.raises(ValueError, match="resolution must be positive"):
        las_mod.copc_query(dst, fields=("x",), resolution=0.0)


@pytest.mark.parametrize("suffix", [".las", ".laz"])
def test_dropping_copc_records_leaves_a_plain_cloud_byte_identical(
        tmp_path, suffix):
    """Every whole-cloud write now passes through drop_copc_records, so
    on a cloud with no COPC records it must change NOTHING. The first
    version reassigned the VLR list unconditionally, and laspy's setter
    moves the extra-bytes VLR to the end on any reassignment: same
    records, different bytes, on every classification ever written."""
    pyproj = pytest.importorskip("pyproj")
    from laspy.vlrs.vlrlist import VLRList

    header = laspy.LasHeader(version="1.4", point_format=7)
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.zeros(3)
    header.add_extra_dim(laspy.ExtraBytesParams(name="Reflectance",
                                                type=np.float32))
    header.add_crs(pyproj.CRS.from_epsg(6447))
    las = laspy.LasData(header)
    rng = np.random.default_rng(3)
    las.x, las.y, las.z = rng.uniform(0.0, 100.0, (3, 2_000))
    las.Reflectance = rng.uniform(0.0, 1.0, 2_000).astype(np.float32)
    las.evlrs = VLRList([laspy.VLR(user_id="pyargus_test", record_id=7,
                                   description="kept",
                                   record_data=b"x" * 300)])
    src = tmp_path / "src.las"
    las.write(str(src))

    plain = laspy.read(str(src))
    plain.write(str(tmp_path / f"plain{suffix}"))
    dropped = laspy.read(str(src))
    las_mod.drop_copc_records(dropped.header)
    dropped.write(str(tmp_path / f"dropped{suffix}"))
    assert ((tmp_path / f"plain{suffix}").read_bytes()
            == (tmp_path / f"dropped{suffix}").read_bytes())


@needs_pdal
@pytest.mark.parametrize("suffix", [".las", ".laz"])
def test_whole_ground_classify_takes_a_copc_input(tmp_path, suffix):
    """The whole-cloud driver read a .copc.laz like any cloud, then kept
    its octree records on the header it wrote, and laspy refuses to
    write COPC: a NotImplementedError after all the work, whatever the
    output was named. Only the tiled driver's streamed copy dropped
    them. The desktop stage and batch classification use the whole
    driver for every cloud, so one COPC in a project stopped the batch.
    """
    from pyargus.classify import job

    src = tmp_path / "src.las"
    n = make_cloud(src, n=40_000, seed=12)
    copc = tmp_path / "src.copc.laz"
    copc_mod.write_copc(src, copc)
    params = dict(cell=10.0, window=30.0, threshold=1.0,
                  log=lambda _: None)

    whole_out = tmp_path / f"whole{suffix}"
    tiled_out = tmp_path / f"tiled{suffix}"
    whole = job.classify_ground_whole(copc, whole_out, **params)
    job.classify_ground_tiled(copc, tiled_out, **params)
    # same input, same point order: the two drivers must agree exactly
    a = np.asarray(laspy.read(str(whole_out)).classification)
    b = np.asarray(laspy.read(str(tiled_out)).classification)
    assert a.size == b.size == whole["total"] == n
    assert np.array_equal(a, b), int((a != b).sum())
    # a plain cloud, honestly: no octree claimed, every point, the
    # extra dimension carried
    info = las_mod.cloud_info(whole_out)
    assert not info["is_copc"] and info["point_count"] == n
    assert "Amplitude" in laspy.read(str(whole_out)).point_format.extra_dimension_names
