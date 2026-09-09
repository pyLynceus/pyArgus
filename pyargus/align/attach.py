"""From a delivered cloud and its SBET to solvable StripBundles.

This is where vendor conventions meet the math core, so nothing is
taken on faith:

* Attitude mapping (NED aerospace -> this suite's Rz*Ry*Rx, +Z-up):
  roll -> roll, pitch -> -pitch, yaw = pi/2 - heading. Derived
  numerically, and tests/test_attach.py re-derives it from the frame
  definitions on every run.
* The SBET heading field is checked AGAINST THE FLIGHT TRACK computed
  from the transformed positions, both as stored and with the wander
  angle added; whichever agrees is used, both errors are reported, and
  a disagreement beyond ``max_track_error`` refuses -- that is what a
  90-degree axis mix-up or a sign flip looks like, and no solve should
  run on top of one. (Crab pushes heading away from track equally for
  both candidates; the default tolerance leaves room for it.)
* AGL must come out positive and sane. A trajectory below the ground
  is the ellipsoidal-vs-orthometric trap arriving from formats.crs
  uncaught, and is refused by name.
"""

from dataclasses import dataclass

import numpy as np

from pyargus.align.bundles import StripBundle
from pyargus.formats import sbet as sbet_mod
from pyargus.formats.trajectory import match_times


def _interp_wrapped(t, angles, t_query):
    unwrapped = np.unwrap(angles)
    out = np.interp(t_query, t, unwrapped)
    return np.mod(out + np.pi, 2.0 * np.pi) - np.pi


@dataclass
class AttachResult:
    strip_ids: list          # point_source_id per bundle, same order
    bundles: list            # StripBundle per strip
    gps_week: int | None
    heading_source: str      # "heading" or "heading+wander"
    track_error: float       # median |chosen heading - track| (radians)
    track_errors: dict       # both candidates' median errors
    agl_median: float        # map units
    nadir_median_deg: float  # of a sample of body vectors


def bundles_from_cloud(points, sbet, map_e, map_n, map_z, *,
                       max_track_error=0.5, speed_floor=None, time_mode="week"):
    """Build one StripBundle per point_source_id.

    ``map_e/n/z`` are the trajectory positions from formats.crs, one
    per SBET record, in the SAME frame and units as the points.
    ``speed_floor`` drops standstill records from the heading-vs-track
    comparison; the default (None) uses a quarter of the p95 speed, so
    it needs no unit -- a fixed number here would mean different
    physics in a metric CRS than in survey feet.

    One check no code can make: a CONSTANT vertical bias smaller than
    the flying height (a wrong-sign geoid shift, say) passes the AGL
    gate and quietly scales the boresight lever arm. formats.crs
    refuses the known silent causes; the supplied shift's sign is the
    caller's to get right (N is NEGATIVE across CONUS).
    """
    for name in ("x", "y", "z", "gps_time", "point_source_id"):
        if name not in points:
            raise ValueError(f"points need field {name!r} to attach a trajectory")

    t = sbet["time"]
    sow, week, inside_fraction = match_times(points["gps_time"], t, time_mode)
    inside = (sow >= t[0]) & (sow <= t[-1])
    if inside.mean() < 0.99:
        raise ValueError(
            f"only {100 * inside.mean():.1f}% of returns fall inside the "
            f"trajectory (week {week}); wrong SBET or wrong time base")

    # Which heading is true heading? Ask the flight track.
    dt = np.gradient(t)
    de = np.gradient(map_e) / dt
    dn = np.gradient(map_n) / dt
    speed = np.hypot(de, dn)
    if speed_floor is None:
        fast = float(np.percentile(speed, 95))
        if fast <= 0:
            raise ValueError("trajectory never moves; cannot verify the "
                             "heading convention")
        speed_floor = 0.25 * fast
    moving = speed > speed_floor
    if moving.sum() < 10:
        raise ValueError("trajectory has almost no motion above the speed "
                         "floor; cannot verify the heading convention")
    track = np.arctan2(de, dn)  # azimuth from north, east positive
    candidates = {"heading": sbet["heading"],
                  "heading+wander": sbet["heading"] + sbet["wander"]}
    errors = {}
    for name, series in candidates.items():
        diff = np.mod(series[moving] - track[moving] + np.pi,
                      2.0 * np.pi) - np.pi
        errors[name] = float(np.median(np.abs(diff)))
    heading_source = min(errors, key=errors.get)
    if errors[heading_source] > max_track_error:
        raise ValueError(
            f"heading disagrees with the flight track by "
            f"{np.degrees(errors[heading_source]):.1f} deg median (best "
            f"candidate {heading_source!r}); check attitude conventions and crab angle. Refusing to attach.")

    sow = sow[inside]
    att = sbet_mod.interpolate(sbet, sow, fields=("roll", "pitch"))
    heading = _interp_wrapped(t, candidates[heading_source], sow)
    # NED -> Rz*Ry*Rx +Z-up: roll, -pitch, pi/2 - heading (see module doc)
    rpy = np.column_stack([att["roll"], -att["pitch"],
                           np.pi / 2.0 - heading])
    nav = np.column_stack([np.interp(sow, t, map_e),
                           np.interp(sow, t, map_n),
                           np.interp(sow, t, map_z)])
    xyz = np.column_stack([points["x"][inside], points["y"][inside],
                           points["z"][inside]])

    agl = float(np.median(nav[:, 2] - xyz[:, 2]))
    if agl <= 0:
        raise ValueError(
            f"median flying height is {agl:.1f} map units -- the trajectory "
            f"is below the ground, which is the ellipsoidal-vs-orthometric "
            f"height trap (see formats.crs). Check the vertical argument.")

    strip_ids, bundles = [], []
    psid = points["point_source_id"][inside]
    for sid in np.unique(psid):
        m = psid == sid
        bundles.append(StripBundle(xyz=xyz[m], nav_xyz=nav[m], rpy=rpy[m],
                                   times=sow[m]))
    strip_ids = [int(s) for s in np.unique(psid)]

    sample = bundles[0].body_vecs[:10000]
    norms = np.linalg.norm(sample, axis=1)
    nadir = np.degrees(np.arccos(np.clip(-sample[:, 2] / norms, -1, 1)))
    if float(np.median(nadir)) > 60.0:
        raise ValueError(
            f"median scan angle {float(np.median(nadir)):.0f} deg off nadir "
            f"-- wider than any airborne scanner's fan. The geometry is "
            f"wrong: usually the vertical datum (AGL too small widens the "
            f"apparent fan) or the attitude convention.")
    return AttachResult(
        strip_ids=strip_ids, bundles=bundles, gps_week=week,
        heading_source=heading_source,
        track_error=errors[heading_source], track_errors=errors,
        agl_median=agl, nadir_median_deg=float(np.median(nadir)))


def apply_corrections(points, sbet, map_e, map_n, map_z, heading_source,
                      boresight, offsets_by_sid, chunk_size=2_000_000,
                      drift_by_sid=None, time_mode="week"):
    """Corrected coordinates for a whole cloud, in chunks.

    Applies the solved boresight and per-strip offsets through the same
    forward model the solver linearized. Points whose GPS time falls
    outside the trajectory are returned UNCHANGED and counted -- they
    cannot be corrected honestly. A point_source_id with no entry in
    ``offsets_by_sid`` refuses: it means the solve never saw that
    strip. Returns (xyz, n_uncorrected).

    ``drift_by_sid`` (sid -> (node_times, values)) applies a solved
    drift model instead: each point gets the piecewise-linear vertical
    correction at ITS OWN time, the same np.interp the solver's
    DriftModel.offset_at uses (clamped at the node ends, matching the
    solve's clamped brackets). ``offsets_by_sid`` is ignored then --
    in drift mode it holds per-strip means, and applying a mean on top
    of the drift would double-correct.
    """
    from pyargus.core import rotation

    t = sbet["time"]
    sow, week, _ = match_times(points["gps_time"], t, time_mode)
    inside = (sow >= t[0]) & (sow <= t[-1])

    active = drift_by_sid if drift_by_sid is not None else offsets_by_sid
    unknown = set(np.unique(points["point_source_id"][inside]).tolist()) \
        - set(int(k) for k in active)
    if unknown:
        raise ValueError(f"no solved offset for strip(s) {sorted(unknown)}; "
                         f"the adjustment never saw them")

    heading_series = sbet["heading"] if heading_source == "heading" \
        else sbet["heading"] + sbet["wander"]
    boresight = np.asarray(boresight, dtype=float)
    xyz = np.column_stack([points["x"], points["y"], points["z"]]).astype(float)

    indices = np.flatnonzero(inside)
    for start in range(0, indices.size, chunk_size):
        idx = indices[start:start + chunk_size]
        sq = sow[idx]
        att = sbet_mod.interpolate(sbet, sq, fields=("roll", "pitch"))
        heading = _interp_wrapped(t, heading_series, sq)
        r_nav = rotation.matrices(att["roll"], -att["pitch"],
                                  np.pi / 2.0 - heading)
        nav = np.column_stack([np.interp(sq, t, map_e),
                               np.interp(sq, t, map_n),
                               np.interp(sq, t, map_z)])
        body = np.einsum("nji,nj->ni", r_nav, xyz[idx] - nav)
        delta = np.einsum("nij,nj->ni", r_nav, np.cross(boresight, body))
        if drift_by_sid is not None:
            sids = points["point_source_id"][idx]
            offsets = np.zeros((idx.size, 3))
            for s in np.unique(sids):
                m = sids == s
                nt, vals = drift_by_sid[int(s)]
                offsets[m, 2] = np.interp(sq[m], nt, vals)
        else:
            offsets = np.array([offsets_by_sid[int(s)]
                                for s in points["point_source_id"][idx]])
        xyz[idx] = xyz[idx] + delta + offsets
    return xyz, int((~inside).sum())
