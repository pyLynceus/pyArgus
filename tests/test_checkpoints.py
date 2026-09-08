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


def test_local_median_recovers_offset_and_skips_isolated_marks():
    strip = planar_strip(20000, (0, 100), (0, 100),
                         plane=(0.0, 0.0, 50.0), noise=0.02, seed=9)
    ground = _as_xyz(strip)
    ids = ["A", "B", "FAR"]
    checks = np.array([[25.0, 25.0, 49.9], [75.0, 75.0, 49.9],
                       [500.0, 500.0, 49.9]])
    cmp_ = checkpoints.local_median_residuals(ground, ids, checks, radius=3.0)
    assert set(cmp_.residuals) == {"A", "B"}
    assert np.allclose(list(cmp_.residuals.values()), 0.1, atol=0.02)
    assert "FAR" in cmp_.skipped and "nearest" in cmp_.skipped["FAR"]


def test_robust_summary_matches_hand_arithmetic():
    dz = np.array([0.1, 0.2, 0.3, 0.4, 10.0])
    s = checkpoints.robust_summary(dz)
    assert s["n"] == 5 and np.isclose(s["median"], 0.3)
    assert np.isclose(s["nmad"], 1.4826 * 0.1)
    with pytest.raises(ValueError):
        checkpoints.robust_summary(np.array([]))
