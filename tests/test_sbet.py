import numpy as np
import pytest

from pyargus.formats import sbet
from tests.synthetic import linear_sbet, write_sbet


def test_round_trip(tmp_path):
    data = linear_sbet(n=200)
    path = write_sbet(tmp_path / "traj.sbet", data)
    read = sbet.read_sbet(path)
    assert read.shape == (200,)
    for name in ("time", "lat", "lon", "alt", "roll", "pitch", "heading"):
        assert np.array_equal(read[name], data[name])


def test_truncated_file_refuses(tmp_path):
    data = linear_sbet(n=10)
    path = tmp_path / "bad.sbet"
    path.write_bytes(data.tobytes()[:-8])
    with pytest.raises(ValueError, match="136"):
        sbet.read_sbet(path)


def test_nonmonotonic_time_refuses(tmp_path):
    data = linear_sbet(n=10)
    data["time"][5] = data["time"][2]
    path = write_sbet(tmp_path / "bad.sbet", data)
    with pytest.raises(ValueError, match="increasing"):
        sbet.read_sbet(path)


def test_interpolation_exact_on_linear_fields():
    data = linear_sbet(n=100, t0=1000.0, dt=0.01)
    times = np.array([1000.105, 1000.505])  # record midpoints
    out = sbet.interpolate(data, times, fields=("alt", "roll"))
    # alt climbs 0.01 per record => 1.0 per second
    assert np.allclose(out["alt"], 300.0 + (times - 1000.0) * 1.0)
    assert np.allclose(out["roll"], 0.001 * (times - 1000.0) / 0.01)


def test_heading_interpolates_through_the_wrap():
    # heading passes through +pi; naive interp would average to ~0.
    data = linear_sbet(n=101, t0=0.0, dt=0.1, heading0=np.pi - 0.05,
                       heading_rate=0.02)
    mid = 2.5  # true heading = pi - 0.05 + 0.05 = pi exactly at t=2.5
    out = sbet.interpolate(data, np.array([mid]), fields=("heading",))
    assert np.isclose(np.abs(out["heading"][0]), np.pi, atol=1e-9)


def test_extrapolation_refuses():
    data = linear_sbet(n=10, t0=1000.0, dt=0.005)
    with pytest.raises(ValueError, match="extrapolate"):
        sbet.interpolate(data, np.array([999.0]))


def test_week_alignment_recovers_the_week():
    week = 2385
    traj = linear_sbet(n=1000, t0=481000.0, dt=0.5)  # sow 481000..481499.5
    sow = np.linspace(481050.0, 481400.0, 200)
    adjusted = sow + week * 604800.0 - 1_000_000_000.0
    got_week, inside = sbet.week_alignment(adjusted, traj["time"])
    assert got_week == week
    assert inside == 1.0


def test_week_alignment_flags_wrong_trajectory():
    week = 2385
    traj = linear_sbet(n=100, t0=200000.0, dt=0.5)
    sow = np.linspace(481050.0, 481400.0, 50)
    adjusted = sow + week * 604800.0 - 1_000_000_000.0
    _, inside = sbet.week_alignment(adjusted, traj["time"])
    assert inside == 0.0


def test_week_alignment_refuses_seconds_of_week():
    traj = linear_sbet(n=100, t0=481000.0, dt=0.5)
    with pytest.raises(ValueError, match="seconds-of-week"):
        sbet.week_alignment(np.array([481200.0]), traj["time"])
