import numpy as np
import pytest

from pyargus.core import georef, rotation


def test_identity_attitude_adds_scan_and_lever():
    nav = np.array([[100.0, 200.0, 300.0]])
    rpy = np.zeros((1, 3))
    scan = np.array([[0.0, 0.0, -50.0]])
    ground = georef.ground_points(nav, rpy, scan, lever_arm=(0.1, 0.2, 0.3))
    assert np.allclose(ground, [[100.1, 200.2, 250.3]])


def test_yaw_rotates_scan_vector():
    nav = np.array([[0.0, 0.0, 100.0]])
    rpy = np.array([[0.0, 0.0, np.pi / 2]])
    scan = np.array([[1.0, 0.0, 0.0]])
    ground = georef.ground_points(nav, rpy, scan)
    assert np.allclose(ground, [[0.0, 1.0, 100.0]], atol=1e-12)


def test_boresight_composes_before_nav_attitude():
    nav = np.zeros((1, 3))
    rpy = np.array([[0.2, -0.1, 0.5]])
    scan = np.array([[3.0, -1.0, -40.0]])
    bore = (0.01, -0.02, 0.005)
    expected = (rotation.matrix(*rpy[0]) @ (rotation.matrix(*bore) @ scan[0]))
    ground = georef.ground_points(nav, rpy, scan, boresight_rpy=bore)
    assert np.allclose(ground[0], expected)


def test_shape_mismatch_refuses():
    with pytest.raises(ValueError):
        georef.ground_points(np.zeros((2, 3)), np.zeros((3, 3)), np.zeros((2, 3)))


def test_vectorized_over_many_returns():
    rng = np.random.default_rng(5)
    n = 500
    nav = rng.normal(0, 100, (n, 3))
    rpy = np.column_stack([
        rng.uniform(-0.1, 0.1, n), rng.uniform(-0.1, 0.1, n),
        rng.uniform(-np.pi, np.pi, n)])
    scan = rng.normal(0, 30, (n, 3))
    ground = georef.ground_points(nav, rpy, scan)
    i = 137
    expected = nav[i] + rotation.matrix(*rpy[i]) @ scan[i]
    assert np.allclose(ground[i], expected)
