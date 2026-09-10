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
