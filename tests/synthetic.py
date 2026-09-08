"""Synthetic strips and trajectories with known answers.

Until the reference TrueView 660 dataset is chosen (Phase 0), these are
the only fixtures -- and even after it lands, every mathematical claim
still gets proven here first, where the truth is constructed rather
than measured.
"""

import numpy as np

from pyargus.formats.sbet import RECORD_DTYPE


def planar_strip(n, x_range, y_range, plane=(0.0, 0.0, 100.0), noise=0.0, seed=0):
    """Points on the plane z = a*x + b*y + c inside a rectangle.

    Returns a dict with x, y, z arrays, the same shape formats.las uses.
    """
    a, b, c = plane
    rng = np.random.default_rng(seed)
    x = rng.uniform(*x_range, n)
    y = rng.uniform(*y_range, n)
    z = a * x + b * y + c
    if noise:
        z = z + rng.normal(0.0, noise, n)
    return {"x": x, "y": y, "z": z}


def linear_sbet(n=100, t0=1000.0, dt=0.005, heading0=0.0, heading_rate=0.0):
    """An SBET record array with linear motion and attitude."""
    data = np.zeros(n, dtype=RECORD_DTYPE)
    t = t0 + np.arange(n) * dt
    data["time"] = t
    data["lat"] = 0.594 + 1e-9 * np.arange(n)
    data["lon"] = -1.472 + 1e-9 * np.arange(n)
    data["alt"] = 300.0 + 0.01 * np.arange(n)
    data["roll"] = 0.001 * np.arange(n)
    data["pitch"] = -0.0005 * np.arange(n)
    heading = heading0 + heading_rate * (t - t0)
    data["heading"] = np.mod(heading + np.pi, 2.0 * np.pi) - np.pi
    return data


def write_sbet(path, data):
    data.tofile(path)
    return path
