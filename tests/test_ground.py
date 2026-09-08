import numpy as np
import pytest

from pyargus.classify import ground
from tests.synthetic import classification_scene, planar_strip


def test_scene_with_buildings_and_canopy():
    points, truth = classification_scene(seed=1)
    result = ground.smrf(points["x"], points["y"], points["z"],
                         cell=1.0, slope=0.15, window=18.0, threshold=0.5)
    score = ground.confusion(result.ground, truth)
    assert score["agreement"] > 0.97
    assert score["recall"] > 0.98      # terrain survives
    assert score["precision"] > 0.97   # roofs and canopy do not sneak in
    assert score["kappa"] > 0.9
    assert result.object_cells.any()


def test_sloped_terrain_survives():
    points, truth = classification_scene(seed=2, slope_x=0.10)
    result = ground.smrf(points["x"], points["y"], points["z"],
                         cell=1.0, slope=0.15, window=18.0, threshold=0.5)
    score = ground.confusion(result.ground, truth)
    assert score["recall"] > 0.97


def test_low_outliers_are_cut_and_do_not_drag_neighbours():
    strip = planar_strip(20000, (0, 100), (0, 100), plane=(0, 0, 50.0),
                         noise=0.03, seed=3)
    rng = np.random.default_rng(4)
    n_low = 30
    lx = rng.uniform(40, 45, n_low)
    ly = rng.uniform(40, 45, n_low)
    lz = np.full(n_low, 40.0)  # 10 under the terrain
    x = np.concatenate([strip["x"], lx])
    y = np.concatenate([strip["y"], ly])
    z = np.concatenate([strip["z"], lz])
    result = ground.smrf(x, y, z, cell=1.0, window=10.0, low_cut=2.0)
    assert result.low_cells.any()
    assert not result.ground[-n_low:].any()          # the lows are not ground
    assert result.ground[:-n_low].mean() > 0.99      # the terrain still is


def test_refusals():
    with pytest.raises(ValueError, match="no points"):
        ground.smrf(np.array([]), np.array([]), np.array([]))
    with pytest.raises(ValueError, match="window"):
        ground.smrf(np.zeros(3), np.zeros(3), np.zeros(3),
                    cell=2.0, window=1.0)


def test_confusion_hand_check():
    predicted = np.array([True, True, False, False])
    reference = np.array([True, False, True, False])
    score = ground.confusion(predicted, reference)
    assert (score["tp"], score["fp"], score["fn"], score["tn"]) == (1, 1, 1, 1)
    assert score["agreement"] == 0.5
    assert score["kappa"] == 0.0
    with pytest.raises(ValueError):
        ground.confusion(predicted, reference[:2])
