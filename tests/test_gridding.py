import numpy as np
import pytest

from pyargus.core import gridding


def test_cell_indices_fold_max_edge_in():
    x_edges = np.array([0.0, 1.0, 2.0])
    y_edges = np.array([0.0, 1.0])
    ix, iy = gridding.cell_indices(np.array([0.5, 2.0]), np.array([0.5, 1.0]),
                                   x_edges, y_edges)
    assert ix.tolist() == [0, 1]
    assert iy.tolist() == [0, 0]


def test_min_and_mean_grids():
    x = np.array([0.5, 0.6, 1.5])
    y = np.array([0.5, 0.5, 0.5])
    z = np.array([10.0, 20.0, 5.0])
    x_edges = np.array([0.0, 1.0, 2.0, 3.0])
    y_edges = np.array([0.0, 1.0])
    zmin = gridding.min_grid(x, y, z, x_edges, y_edges)
    zmean = gridding.mean_grid(x, y, z, x_edges, y_edges)
    assert zmin[0, 0] == 10.0 and zmin[1, 0] == 5.0 and np.isnan(zmin[2, 0])
    assert zmean[0, 0] == 15.0 and zmean[1, 0] == 5.0 and np.isnan(zmean[2, 0])


def test_inpaint_nearest_and_max_distance():
    grid = np.full((1, 6), np.nan)
    grid[0, 0] = 7.0
    filled = gridding.inpaint_nearest(grid)
    assert np.allclose(filled, 7.0)
    limited = gridding.inpaint_nearest(grid, max_distance=2)
    assert np.allclose(limited[0, :3], 7.0)
    assert np.isnan(limited[0, 3:]).all()
    with pytest.raises(ValueError):
        gridding.inpaint_nearest(np.full((2, 2), np.nan))


def test_bilinear_sample_is_exact_on_a_linear_field():
    x_edges = np.arange(0.0, 11.0)
    y_edges = np.arange(0.0, 11.0)
    cx = (x_edges[:-1] + 0.5)[:, None]
    cy = (y_edges[:-1] + 0.5)[None, :]
    grid = 2.0 * cx + 3.0 * cy
    xs = np.array([2.5, 5.0, 7.25])
    ys = np.array([3.5, 5.0, 1.75])
    got = gridding.bilinear_sample(grid, xs, ys, x_edges, y_edges)
    assert np.allclose(got, 2.0 * xs + 3.0 * ys)
