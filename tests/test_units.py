import numpy as np

from pyargus.core import units


def test_us_survey_foot_exact_definition():
    assert units.usft_to_m(3937.0) == 1200.0


def test_international_foot():
    assert units.ift_to_m(1.0) == 0.3048


def test_the_two_feet_differ():
    # ~2 ppm: invisible on a lot, feet of error on state-plane eastings.
    assert units.usft_to_m(1.0) != units.ift_to_m(1.0)
    assert abs(units.usft_to_m(1.0) - 0.3048006096) < 1e-9


def test_round_trips():
    values = np.array([0.0, 1.0, 1234.5678])
    assert np.allclose(units.m_to_usft(units.usft_to_m(values)), values)
    assert np.allclose(units.m_to_ift(units.ift_to_m(values)), values)
