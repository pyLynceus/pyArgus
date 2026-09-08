import numpy as np
import pytest

from pyargus.qa import density


def test_uniform_lattice_gives_exact_density():
    # 4 points per 1x1 cell on a regular lattice, offset off the edges.
    xs, ys = np.meshgrid(np.arange(0.25, 4.0, 0.5), np.arange(0.25, 2.0, 0.5))
    dens, x_edges, y_edges = density.density_grid(xs.ravel(), ys.ravel(), cell=1.0)
    assert dens.shape == (4, 2)
    assert np.allclose(dens, 4.0)
    assert x_edges[0] == 0.0 and y_edges[0] == 0.0


def test_empty_cells_are_zero():
    x = np.array([0.5, 3.5])
    y = np.array([0.5, 0.5])
    dens, _, _ = density.density_grid(x, y, cell=1.0)
    assert dens[0, 0] == 1.0
    assert dens[3, 0] == 1.0
    assert dens[1, 0] == 0.0 and dens[2, 0] == 0.0


def test_cell_size_scales_density():
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 10, 5000)
    y = rng.uniform(0, 10, 5000)
    d1, _, _ = density.density_grid(x, y, cell=1.0)
    d2, _, _ = density.density_grid(x, y, cell=2.0)
    # Density is per unit area regardless of cell size, ~50 pts/unit^2.
    assert abs(np.mean(d1) - 50.0) < 5.0
    assert abs(np.mean(d2) - 50.0) < 5.0


def test_no_points_refuses():
    with pytest.raises(ValueError):
        density.density_grid(np.array([]), np.array([]))
