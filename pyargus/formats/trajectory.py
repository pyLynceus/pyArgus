"""Shared trajectory import boundary; explicit native TRJ assumptions."""
from pathlib import Path
import numpy as np
from . import sbet, trj

def is_trj(path):
    with Path(path).open("rb") as f:
        magic = f.read(8)
    return magic == b"TSCANTRJ" or Path(path).suffix.lower() == ".trj"

def read_times(path, *, trj_time=None):
    if is_trj(path):
        if trj_time not in ("same", "week"):
            raise ValueError("Select TRJ time: same stored timestamps as LAS, or GPS seconds of week")
        times = trj.read_trj(path).records["time"]
        validate_trj_time(times, trj_time)
        return times, trj_time
    return sbet.read_sbet(path)["time"], "week"

def validate_trj_time(times, mode):
    if mode == "week" and (times.min() < 0 or times.max() >= 604800):
        raise ValueError("TRJ timestamps are outside GPS seconds of week; confirm the stored time base")

def match_times(point_times, traj_times, mode="week"):
    p, t = np.asarray(point_times), np.asarray(traj_times)
    if p.size == 0 or t.size == 0 or not np.isfinite(p).all() or not np.isfinite(t).all():
        raise ValueError("trajectory matching requires nonempty finite timestamps")
    if mode == "week":
        week, inside = sbet.week_alignment(p, t)
        return p + 1_000_000_000.0 - week * 604800.0, week, inside
    if mode != "same":
        raise ValueError("unknown trajectory time mode")
    return p, None, float(((p >= t[0]) & (p <= t[-1])).mean())

def load_alignment(path, map_crs, *, vertical=None, allow_network=False,
                   trj_time=None, trj_confirmed=False):
    if not is_trj(path):
        from .crs import sbet_to_map
        d = sbet.read_sbet(path)
        return d, sbet_to_map(d, map_crs, vertical=vertical,
                             allow_network=allow_network), "week"
    if not trj_confirmed:
        raise ValueError("TRJ alignment requires confirmed matching LAS XYZ axes, units and datum; "
                         "grid-north clockwise heading, right-wing-down roll and nose-up pitch. "
                         "The file does not establish these conventions.")
    if trj_time not in ("same", "week"):
        raise ValueError("Select the TRJ time base before alignment")
    native = trj.read_trj(path).records
    validate_trj_time(native["time"], trj_time)
    if len(native) < 2:
        raise ValueError("alignment needs at least two trajectory positions")
    # Interface array only: no geographic conversion and no guessed wander angle.
    d = np.zeros(len(native), dtype=[(n, '<f8') for n in
                  ('time', 'roll', 'pitch', 'heading', 'wander')])
    d['time'] = native['time']
    for n in ('roll', 'pitch', 'heading'):
        d[n] = np.deg2rad(native[n])
    return d, tuple(native[n] for n in ('x', 'y', 'z')), trj_time
