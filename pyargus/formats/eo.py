"""Exterior orientation for camera imagery: the LP360/pyLynceus EO CSV.

One reader covers both producers because they share the same eleven
leading columns::

    Timestamp, Filename, Origin(E,N,H), Direction(E,N,H), Up(E,N,H), ...

* LP360/TrueView exports (``eo_Photos_*.csv``) append six angle columns
  after these. They are NEVER parsed: the Roll/Pitch/Yaw and
  Omega/Phi/Kappa columns each follow their own convention (the OPK
  export disagrees with the platform angles by up to 79 degrees on real
  data -- pyLynceus's hard-won finding), while the Direction/Up vectors
  are the ground-space camera axes themselves, convention-free.
* pyLynceus's ``adjusted_eo.csv`` (its Tie+Adjust output, the artifact
  its GUI hands to pyArgus) writes exactly the eleven columns and no
  angles at all.

The rotation is rebuilt from Direction and Up: z = -direction (the
optical axis looks along -z), y = up orthogonalised against z (the
export rounds its vectors; trusting them un-orthogonalised leaves a
small rotation error nobody can attribute), x = y cross z. Columns
[x y z] give the CAMERA-TO-GROUND matrix.

Units: positions are whatever frame the producer worked in, and the
LP360 header LIES about it -- it says [m] while Summerville's values
are US survey feet. No unit conversion happens here; the colorizer
refuses when the EO positions do not overlap the cloud, which is what
a wrong unit or CRS actually looks like.
"""

from pathlib import Path

import numpy as np


def read_eo_csv(path):
    """Read an LP360-style EO CSV.

    Returns a dict: ``time`` (N,) float seconds as written,
    ``filename`` list of N image names, ``origin`` (N, 3) positions,
    ``direction`` (N, 3) and ``up`` (N, 3) unit-ish vectors. Only the
    first eleven columns are read; anything after them is ignored on
    purpose (see the module docstring).
    """
    path = Path(path)
    times, names, origins, directions, ups = [], [], [], [], []
    with open(path, encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if line_no == 1 and not _is_float(parts[0]):
                continue                      # the header line
            if len(parts) < 11:
                raise ValueError(
                    f"{path.name} line {line_no}: expected at least 11 "
                    f"columns (Timestamp, Filename, Origin x3, Direction "
                    f"x3, Up x3), got {len(parts)}")
            try:
                times.append(float(parts[0]))
                origins.append([float(v) for v in parts[2:5]])
                directions.append([float(v) for v in parts[5:8]])
                ups.append([float(v) for v in parts[8:11]])
            except ValueError:
                raise ValueError(
                    f"{path.name} line {line_no}: non-numeric value in "
                    f"the first eleven columns") from None
            names.append(parts[1])
    if not names:
        raise ValueError(f"{path.name} holds no EO rows")
    eo = {
        "time": np.array(times),
        "filename": names,
        "origin": np.array(origins),
        "direction": np.array(directions),
        "up": np.array(ups),
    }
    for key in ("time", "origin", "direction", "up"):
        if not np.all(np.isfinite(eo[key])):
            raise ValueError(f"{path.name}: non-finite {key} values")
    return eo


def _is_float(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def rotations_from_direction_up(direction, up):
    """(N, 3, 3) CAMERA-TO-GROUND rotations from viewing geometry.

    z = -direction (optical axis along -z), y = up orthogonalised
    against z, x = y cross z; columns [x y z]. Refuses by name on a
    degenerate row (zero direction, or up parallel to the axis) --
    a silently skipped photo would just become an uncolored hole
    nobody can explain.
    """
    d = np.asarray(direction, dtype=float)
    u = np.asarray(up, dtype=float)
    norms = np.linalg.norm(d, axis=1)
    bad = norms < 1e-9
    if bad.any():
        raise ValueError(f"EO rows {np.flatnonzero(bad).tolist()} have a "
                         f"zero-length direction vector")
    z = -d / norms[:, None]
    unorm = np.linalg.norm(u, axis=1)
    bad = unorm < 1e-12
    if bad.any():
        raise ValueError(f"EO rows {np.flatnonzero(bad).tolist()} have a "
                         f"zero-length up vector")
    u = u / unorm[:, None]
    y = u - np.einsum("ni,ni->n", u, z)[:, None] * z
    ynorm = np.linalg.norm(y, axis=1)
    # ynorm is now sin(angle between up and the optical axis). The
    # export writes 9 decimals, so rounding noise is ~5e-10 per
    # component: below ~1e-6 the roll about the optical axis is
    # decided by that noise, not by the data (measured: at ynorm 1e-7
    # a half-ulp nudge swings the camera x axis 0.29 deg). Refuse the
    # whole noise band rather than the exactly-parallel case only.
    bad = ynorm < 1e-6
    if bad.any():
        raise ValueError(
            f"EO rows {np.flatnonzero(bad).tolist()}: up is parallel (to "
            f"within {ynorm[bad].max():.1e}) to the viewing direction, so "
            f"the roll about the optical axis is rounding noise")
    y = y / ynorm[:, None]
    x = np.cross(y, z)
    return np.stack([x, y, z], axis=2)


def camera_tag(filename):
    """The camera-role tag from a TrueView-style image name.

    ``250926_134000_N_0015.JPG`` -> ``"N"``. The tag is the
    second-to-last underscore-separated piece of the stem (N/P/S for
    nadir/port/starboard on a TrueView 660). Returns None when the
    name does not follow the pattern -- single-camera deliveries need
    no tag.
    """
    stem = Path(str(filename)).stem
    parts = stem.split("_")
    if len(parts) >= 2 and parts[-2].isalpha():
        return parts[-2].upper()
    return None
