import numpy as np
import pytest

from pyargus.surfaces import dtm
from tests.synthetic import planar_strip


def test_dtm_reproduces_a_plane():
    strip = planar_strip(30000, (0, 50), (0, 50), plane=(0.05, -0.02, 80.0),
                         noise=0.01, seed=1)
    grid, x_edges, y_edges = dtm.dtm_grid(strip["x"], strip["y"], strip["z"],
                                          cell=2.0)
    cx = (x_edges[:-1] + 1.0)[:, None]
    cy = (y_edges[:-1] + 1.0)[None, :]
    expected = 0.05 * cx - 0.02 * cy + 80.0
    finite = np.isfinite(grid)
    assert finite.all()
    assert np.abs(grid - expected).max() < 0.05


def test_max_fill_leaves_distant_gaps_nodata():
    strip = planar_strip(5000, (0, 10), (0, 10), seed=2)
    far = planar_strip(5000, (90, 100), (0, 10), seed=3)
    x = np.concatenate([strip["x"], far["x"]])
    y = np.concatenate([strip["y"], far["y"]])
    z = np.concatenate([strip["z"], far["z"]])
    grid, _, _ = dtm.dtm_grid(x, y, z, cell=1.0, max_fill=5)
    assert np.isfinite(grid[:10, :10]).all()
    assert np.isnan(grid[45:55, :10]).all()   # mid-gap, far from both patches


def test_esri_ascii_round_trip(tmp_path):
    grid = np.array([[1.0, 3.0], [2.0, np.nan]])  # [ix, iy]
    x_edges = np.array([100.0, 102.0, 104.0])
    y_edges = np.array([500.0, 502.0, 504.0])
    path = tmp_path / "dtm.asc"
    dtm.write_esri_ascii(path, grid, x_edges, y_edges)
    lines = path.read_text().splitlines()
    header = dict(line.split() for line in lines[:6])
    assert header["ncols"] == "2" and header["nrows"] == "2"
    assert float(header["xllcorner"]) == 100.0
    assert float(header["yllcorner"]) == 500.0
    assert float(header["cellsize"]) == 2.0
    rows = [[float(v) for v in line.split()] for line in lines[6:]]
    # north row first: iy=1 -> [grid[0,1], grid[1,1]] with NaN as nodata
    assert rows[0] == [3.0, -9999.0]
    assert rows[1] == [1.0, 2.0]


def test_esri_ascii_refuses_rectangular_cells(tmp_path):
    with pytest.raises(ValueError, match="square"):
        dtm.write_esri_ascii(tmp_path / "bad.asc", np.zeros((2, 2)),
                             np.array([0.0, 1.0, 2.0]),
                             np.array([0.0, 2.0, 4.0]))


def test_no_points_refuses():
    with pytest.raises(ValueError):
        dtm.dtm_grid(np.array([]), np.array([]), np.array([]), cell=1.0)


def test_dsm_rides_the_roofs():
    from tests.synthetic import classification_scene

    points, truth = classification_scene(seed=4)
    dsm_g, xe, ye = dtm.dsm_grid(points["x"], points["y"], points["z"],
                                 cell=2.0)
    dtm_g, xe_d, ye_d = dtm.dtm_grid(points["x"][truth], points["y"][truth],
                                     points["z"][truth], cell=2.0)
    # comparing by index is only honest when the origins agree -- the
    # review panel caught a referee that skipped this check
    assert xe[0] == xe_d[0] and ye[0] == ye_d[0]
    n = min(dsm_g.shape[0], dtm_g.shape[0]), min(dsm_g.shape[1], dtm_g.shape[1])
    both = np.isfinite(dsm_g[:n[0], :n[1]]) & np.isfinite(dtm_g[:n[0], :n[1]])
    # the highest surface never dips below the ground surface
    assert (dsm_g[:n[0], :n[1]][both] >= dtm_g[:n[0], :n[1]][both] - 0.2).all()
    # over the first building footprint (15..29, 15..29) the DSM sits
    # ~8 above the ground surface
    ix = slice(int(17 // 2), int(27 // 2))
    diff = dsm_g[ix, ix] - dtm_g[ix, ix]
    assert np.nanmedian(diff) > 7.0
