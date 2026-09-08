import numpy as np
import pytest

pytest.importorskip("pyproj")

from pyargus.formats import crs
from tests.synthetic import linear_sbet


def summerville_sbet():
    data = linear_sbet(n=3)
    data["lat"] = np.deg2rad(34.47)
    data["lon"] = np.deg2rad(-85.33)
    data["alt"] = 200.0
    return data


def test_geoid_shift_path_pinned_values():
    # Regression pin measured 2026-09-08 with pyproj 3.7 / EPSG:6447.
    e, n, z = crs.sbet_to_map(summerville_sbet(), "EPSG:6447", vertical=-29.077)
    assert abs(e[0] - 1945958.24) < 0.1
    assert abs(n[0] - 1628107.31) < 0.1
    assert abs(z[0] - (200.0 + 29.077) / (1200.0 / 3937.0) * 1.0) < 0.1
    # explicitly: 229.077 m ellipsoid-to-orthometric, in survey feet
    assert abs(z[0] - 751.56) < 0.1


def test_horizontal_only_crs_refuses_without_vertical():
    with pytest.raises(ValueError, match="vertical"):
        crs.sbet_to_map(summerville_sbet(), "EPSG:6447")


def test_geographic_map_crs_refuses():
    with pytest.raises(ValueError, match="projected"):
        crs.sbet_to_map(summerville_sbet(), "EPSG:6318", vertical=-29.0)


def test_shift_is_meters_regardless_of_map_units():
    # Same shift, meter-based UTM zone 16N (EPSG:26916-ish NAD83):
    _, _, z_ft = crs.sbet_to_map(summerville_sbet(), "EPSG:6447",
                                 vertical=-29.077)
    _, _, z_m = crs.sbet_to_map(summerville_sbet(), "EPSG:6345",
                                vertical=-29.077)
    assert abs(z_m[0] - 229.077) < 1e-6
    assert abs(z_ft[0] * (1200.0 / 3937.0) - z_m[0]) < 1e-6


def test_compound_target_uses_the_vertical_units_for_the_shift():
    # Metric horizontal + ftUS heights (a real DOT convention): the
    # shift arithmetic must convert into the VERTICAL unit, not the
    # horizontal one.
    _, _, z_ft = crs.sbet_to_map(summerville_sbet(), "EPSG:6345+6360",
                                 vertical=-29.077)
    assert abs(z_ft[0] - 751.56) < 0.1          # ftUS despite metric E/N
    # ftUS horizontal + metric heights, the reverse
    _, _, z_m = crs.sbet_to_map(summerville_sbet(), "EPSG:6447+5703",
                                vertical=-29.077)
    assert abs(z_m[0] - 229.077) < 1e-6


def test_grid_vertical_never_returns_ballpark_heights():
    # With the geoid grid available this returns the true orthometric
    # height; without it, only_best makes PROJ refuse and we raise.
    # What must NEVER happen is the silent middle: a finite height that
    # is just the ellipsoidal value unit-converted (~656 ft here).
    try:
        _, _, z = crs.sbet_to_map(summerville_sbet(), "EPSG:6447",
                                  vertical="EPSG:6360")
    except ValueError as exc:
        assert "geoid grid" in str(exc)
    else:
        assert abs(z[0] - 751.56) < 0.5
