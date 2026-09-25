import numpy as np
import pytest

from pyargus.qa import overlap
from tests.synthetic import planar_strip


def test_known_vertical_offset_is_recovered():
    a = planar_strip(20000, (0, 50), (0, 30), plane=(0, 0, 100.0), seed=1)
    b = planar_strip(20000, (20, 70), (0, 30), plane=(0, 0, 100.05), seed=2)
    result = overlap.strip_dz(a, b, cell=2.0, min_points=3)
    stats = result.summary()
    assert abs(stats["median"] - 0.05) < 1e-9
    assert stats["cells"] > 50


def test_offset_survives_measurement_noise():
    a = planar_strip(40000, (0, 50), (0, 30), plane=(0.02, -0.01, 100.0),
                     noise=0.03, seed=3)
    b = planar_strip(40000, (20, 70), (0, 30), plane=(0.02, -0.01, 99.93),
                     noise=0.03, seed=4)
    stats = overlap.strip_dz(a, b, cell=2.0).summary()
    assert abs(stats["median"] - (-0.07)) < 0.01


def test_non_overlap_cells_are_nan():
    a = planar_strip(5000, (0, 20), (0, 10), seed=5)
    b = planar_strip(5000, (30, 50), (0, 10), seed=6)
    result = overlap.strip_dz(a, b, cell=2.0)
    assert result.overlap_cells == 0
    with pytest.raises(ValueError, match="overlap"):
        result.summary()


def test_sign_convention_is_b_minus_a():
    a = planar_strip(10000, (0, 10), (0, 10), plane=(0, 0, 100.0), seed=7)
    b = planar_strip(10000, (0, 10), (0, 10), plane=(0, 0, 101.0), seed=8)
    stats = overlap.strip_dz(a, b, cell=2.0).summary()
    assert stats["median"] > 0


def test_an_empty_strip_reports_no_overlap_rather_than_dying():
    """Selecting ground returns on an UNCLASSIFIED cloud yields empty
    strips. That used to reach grid_edges and raise 'zero-size array to
    reduction operation minimum', naming neither the strip nor the
    cause -- it surfaced as a failed QA job on a real project. An empty
    strip cannot overlap anything; say so."""
    a = planar_strip(5000, (0, 50), (0, 30), plane=(0, 0, 100.0), seed=1)
    empty = {k: np.zeros(0) for k in ("x", "y", "z")}

    for pair in ((a, empty), (empty, a), (empty, empty)):
        result = overlap.strip_dz(*pair, cell=2.0, min_points=3)
        assert result.overlap_cells == 0
