"""Applanix SBET trajectory files.

Fixed little-endian records of 17 doubles (136 bytes): time, latitude,
longitude, altitude, three velocities, roll, pitch, platform heading,
wander angle, three body accelerations, three body angular rates.
Angles are radians, positions are radians/meters on the ellipsoid.

The reader refuses malformed files and the interpolator refuses times
outside the trajectory -- extrapolated attitude reads as meaningful and
is not.
"""

import numpy as np

RECORD_DTYPE = np.dtype([
    ("time", "<f8"), ("lat", "<f8"), ("lon", "<f8"), ("alt", "<f8"),
    ("vx", "<f8"), ("vy", "<f8"), ("vz", "<f8"),
    ("roll", "<f8"), ("pitch", "<f8"), ("heading", "<f8"), ("wander", "<f8"),
    ("fx", "<f8"), ("fy", "<f8"), ("fz", "<f8"),
    ("wx", "<f8"), ("wy", "<f8"), ("wz", "<f8"),
])

# Fields that are angles wrapping at +/-pi and must be unwrapped before
# linear interpolation. Roll and pitch stay small on a fixed-wing or
# multirotor survey and never wrap in practice, but heading crosses
# +/-pi on every other flight line.
_WRAPPING = {"heading"}


def read_sbet(path):
    """Read an SBET file into a structured array, one row per record."""
    data = np.fromfile(path, dtype=RECORD_DTYPE)
    if data.size == 0:
        raise ValueError(f"{path}: no complete 136-byte SBET records")
    import os
    remainder = os.path.getsize(path) % RECORD_DTYPE.itemsize
    if remainder:
        raise ValueError(
            f"{path}: size is not a multiple of 136 bytes "
            f"({remainder} bytes over) -- not an SBET, or truncated")
    if data.size > 1 and np.any(np.diff(data["time"]) <= 0):
        raise ValueError(f"{path}: time is not strictly increasing")
    return data


def interpolate(sbet, times, fields=("lat", "lon", "alt", "roll", "pitch", "heading")):
    """Linearly interpolate trajectory fields at GPS ``times``.

    Returns a dict of arrays, one per requested field. Wrapping angle
    fields are unwrapped before interpolation and re-wrapped to
    [-pi, pi) after. Times outside the trajectory raise.
    """
    times = np.asarray(times, dtype=float)
    t = sbet["time"]
    if times.min() < t[0] or times.max() > t[-1]:
        raise ValueError(
            f"requested times [{times.min():.3f}, {times.max():.3f}] fall outside "
            f"the trajectory [{t[0]:.3f}, {t[-1]:.3f}]; refusing to extrapolate")
    out = {}
    for name in fields:
        values = sbet[name]
        if name in _WRAPPING:
            values = np.unwrap(values)
        interped = np.interp(times, t, values)
        if name in _WRAPPING:
            interped = np.mod(interped + np.pi, 2.0 * np.pi) - np.pi
        out[name] = interped
    return out
