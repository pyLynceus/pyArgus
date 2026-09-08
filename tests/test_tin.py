import numpy as np
import pytest

from pyargus.surfaces import tin
from tests.synthetic import planar_strip


def test_tin_interpolates_a_plane_exactly():
    strip = planar_strip(2000, (0, 50), (0, 50), plane=(0.05, -0.02, 80.0),
                         seed=1)
    surface = tin.build_tin(np.column_stack([strip["x"], strip["y"],
                                             strip["z"]]))
    xq = np.array([10.0, 25.0, 40.0])
    yq = np.array([30.0, 25.0, 10.0])
    got = surface.z_at(xq, yq)
    assert np.allclose(got, 0.05 * xq - 0.02 * yq + 80.0, atol=1e-9)
    assert np.isnan(surface.z_at(np.array([500.0]), np.array([500.0]))[0])


def test_densify_polyline():
    line = np.array([[0.0, 0.0, 10.0], [10.0, 0.0, 20.0]])
    dense = tin.densify_polyline(line, spacing=2.5)
    assert dense.shape[0] == 5
    assert np.allclose(dense[:, 0], [0, 2.5, 5, 7.5, 10])
    assert np.allclose(dense[:, 2], [10, 12.5, 15, 17.5, 20])  # z rides along
    with pytest.raises(ValueError, match="two vertices"):
        tin.densify_polyline(line[:1], spacing=1.0)
    with pytest.raises(ValueError, match="positive"):
        tin.densify_polyline(line, spacing=0.0)


def test_soft_breakline_pulls_the_surface_down():
    # Coarse flat ground at z=10; a surveyed ditch line at z=8 along
    # x=25. Without the breakline the TIN reads ~10 there; with it,
    # the densified vertices force the surface down to the survey.
    rng = np.random.default_rng(2)
    gx = rng.uniform(0, 50, 400)
    gy = rng.uniform(0, 50, 400)
    keep = np.abs(gx - 25.0) > 4.0        # no ground shots in the ditch
    ground = np.column_stack([gx[keep], gy[keep],
                              np.full(keep.sum(), 10.0)])
    ditch = np.array([[25.0, 0.0, 8.0], [25.0, 50.0, 8.0]])

    bare = tin.build_tin(ground)
    with_line = tin.build_tin(ground, breaklines=[ditch], spacing=1.0)
    assert with_line.n_breakline_points >= 50

    xq = np.full(20, 25.0)
    yq = np.linspace(5.0, 45.0, 20)
    assert np.allclose(bare.z_at(xq, yq), 10.0, atol=1e-6)
    assert np.allclose(with_line.z_at(xq, yq), 8.0, atol=1e-6)


def test_tin_grid_matches_point_interpolation():
    strip = planar_strip(1500, (0, 30), (0, 30), plane=(0.1, 0.0, 5.0),
                         seed=3)
    surface = tin.build_tin(np.column_stack([strip["x"], strip["y"],
                                             strip["z"]]))
    grid, xe, ye = surface.grid(cell=2.0)
    cx = (xe[:-1] + 1.0)[:, None]
    inside = np.isfinite(grid)
    assert inside.mean() > 0.8
    expected = np.broadcast_to(0.1 * cx + 5.0, grid.shape)
    assert np.abs((grid - expected)[inside]).max() < 1e-9


def test_refusals():
    with pytest.raises(ValueError, match="at least 3"):
        tin.build_tin(np.zeros((2, 3)))
    with pytest.raises(ValueError, match="N, 3"):
        tin.build_tin(np.zeros((5, 2)))
