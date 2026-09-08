import numpy as np
import pytest

from pyargus.qa import checkpoints
from tests.synthetic import planar_strip


def _as_xyz(strip):
    return np.column_stack([strip["x"], strip["y"], strip["z"]])


def test_plane_offset_appears_in_residuals():
    surface = _as_xyz(planar_strip(2000, (0, 100), (0, 100),
                                   plane=(0.01, -0.02, 50.0), seed=1))
    cx = np.array([25.0, 50.0, 75.0])
    cy = np.array([25.0, 50.0, 75.0])
    # Checkpoints sit 0.04 BELOW the lidar plane => surface - check = +0.04
    cz = 0.01 * cx - 0.02 * cy + 50.0 - 0.04
    dz = checkpoints.vertical_residuals(surface, np.column_stack([cx, cy, cz]))
    assert np.allclose(dz, 0.04, atol=1e-6)


def test_checkpoint_outside_hull_is_nan():
    surface = _as_xyz(planar_strip(500, (0, 10), (0, 10), seed=2))
    check = np.array([[50.0, 50.0, 100.0]])
    dz = checkpoints.vertical_residuals(surface, check)
    assert np.isnan(dz[0])


def test_asprs_statistics_on_known_residuals():
    dz = np.array([0.03, -0.03, 0.04, -0.04, 0.05, -0.05])
    acc = checkpoints.asprs_vertical(dz)
    expected_rmse = np.sqrt(np.mean(dz ** 2))
    assert acc.n == 6
    assert np.isclose(acc.mean, 0.0)
    assert np.isclose(acc.rmse_z, expected_rmse)
    assert np.isclose(acc.nva, 1.96 * expected_rmse)
    assert np.isclose(acc.p95_abs, np.percentile(np.abs(dz), 95))


def test_asprs_refuses_nan():
    with pytest.raises(ValueError, match="untestable"):
        checkpoints.asprs_vertical(np.array([0.01, np.nan]))


def test_asprs_refuses_empty():
    with pytest.raises(ValueError):
        checkpoints.asprs_vertical(np.array([]))
