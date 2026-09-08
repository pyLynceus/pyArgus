import numpy as np
import pytest

from pyargus.core import rotation


def test_zero_angles_is_identity():
    assert np.allclose(rotation.matrix(0.0, 0.0, 0.0), np.eye(3))


def test_yaw_quarter_turn_maps_x_to_y():
    R = rotation.matrix(0.0, 0.0, np.pi / 2)
    assert np.allclose(R @ [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], atol=1e-12)


def test_orthonormal_for_random_angles():
    rng = np.random.default_rng(7)
    for _ in range(50):
        r, y = rng.uniform(-np.pi, np.pi, 2)
        p = rng.uniform(-np.pi / 2 + 0.01, np.pi / 2 - 0.01)
        R = rotation.matrix(r, p, y)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
        assert np.isclose(np.linalg.det(R), 1.0)


def test_angles_round_trip():
    rng = np.random.default_rng(11)
    for _ in range(50):
        r, y = rng.uniform(-np.pi, np.pi, 2)
        p = rng.uniform(-np.pi / 2 + 0.01, np.pi / 2 - 0.01)
        r2, p2, y2 = rotation.angles(rotation.matrix(r, p, y))
        assert np.allclose([r, p, y], [r2, p2, y2], atol=1e-10)


def test_gimbal_pole_refuses():
    with pytest.raises(ValueError):
        rotation.angles(rotation.matrix(0.3, np.pi / 2, 0.1))


def test_matrices_matches_scalar():
    rng = np.random.default_rng(3)
    r = rng.uniform(-np.pi, np.pi, 20)
    p = rng.uniform(-1.4, 1.4, 20)
    y = rng.uniform(-np.pi, np.pi, 20)
    stacked = rotation.matrices(r, p, y)
    for i in range(20):
        assert np.allclose(stacked[i], rotation.matrix(r[i], p[i], y[i]))
