"""Where several rays say a point is, and how much to believe them.

The other half of :meth:`Camera.ray`. One photograph gives a direction
and no range; two or more give a position, and the honest question is
never just "where" but "how well determined".

Two numbers come back with every point and both matter for different
reasons.

``max_angle`` is the geometry. Two rays that leave nearly parallel
determine the along-ray direction almost not at all: at a base-to-height
ratio of 0.06, which is what ADJACENT frames give on a rig flying 21 ft
between stations at 343 ft, one pixel of pointing error is over a foot
of height. At 0.4 it is six hundredths. So a pair is CHOSEN, and a weak
one is refused rather than averaged -- `refuse_below` exists because the
temptation to take the nearest neighbour is exactly the mistake that
makes a stereo answer look precise and be wrong.

``residual`` is the consistency. It is the RMS distance from the solved
point to the rays themselves. Large residual with good geometry means
the rays disagree -- the operator pointed at two different things, or
the orientation is off -- and no amount of least squares fixes it. A
small residual with poor geometry means nothing at all, which is why
reporting only the residual would be worse than reporting neither.

The solve is the standard one: each ray contributes the projector
``I - dd^T`` that measures distance perpendicular to it, and the point
minimising the sum of squared perpendicular distances solves
``(sum P_i) p = sum P_i o_i``. It is linear, so there is no iteration
to converge and no starting value to get wrong.
"""

import numpy as np


class WeakGeometry(ValueError):
    """The rays are too nearly parallel to fix a point."""


def intersect(origins, directions, *, refuse_below=None):
    """Least-squares point from N rays. Returns (xyz, info).

    ``origins`` and ``directions`` are (N, 3); directions need not be
    normalised. ``refuse_below`` is an angle in DEGREES: pass it and a
    set of rays whose widest separation falls under it raises
    :class:`WeakGeometry` by name instead of returning a number.
    """
    o = np.asarray(origins, dtype=float).reshape(-1, 3)
    d = np.asarray(directions, dtype=float).reshape(-1, 3)
    if o.shape != d.shape:
        raise ValueError(f"{len(o)} origins against {len(d)} directions")
    if len(o) < 2:
        raise ValueError(f"a point needs at least two rays, got {len(o)}; "
                         f"one photograph gives a direction and no range")
    norms = np.linalg.norm(d, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0):
        raise ValueError("a direction is zero or not finite")
    d = d / norms

    angle = max_angle(d)
    if refuse_below is not None and angle < refuse_below:
        raise WeakGeometry(
            f"the widest angle between these {len(o)} rays is {angle:.2f} "
            f"degrees, under the {refuse_below:g} asked for: the point is "
            f"barely constrained along the line of sight and a small "
            f"pointing error becomes a large height error. Choose frames "
            f"further apart.")

    projectors = np.eye(3) - d[:, :, None] * d[:, None, :]
    a = projectors.sum(axis=0)
    b = np.einsum("nij,nj->i", projectors, o)
    try:
        xyz = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        raise WeakGeometry(
            f"these {len(o)} rays do not fix a point: the normal matrix is "
            f"singular, which means they are parallel or all in one "
            f"plane through the solution.") from None

    delta = xyz - o
    along = np.einsum("nj,nj->n", delta, d)
    perp = delta - along[:, None] * d
    distances = np.linalg.norm(perp, axis=1)
    return xyz, {"rays": len(o),
                 "max_angle_deg": float(angle),
                 "residual": float(np.sqrt(np.mean(distances ** 2))),
                 "worst_ray": float(distances.max()),
                 "condition": float(np.linalg.cond(a))}


def max_angle(directions):
    """The widest angle in degrees between any pair of unit directions.

    This is the strength of the geometry in one number. It is taken
    over every PAIR rather than against a mean direction, because three
    rays where two are nearly coincident and one is well off should
    read as strong, and a mean would hide the one that carries the
    solution.
    """
    d = np.asarray(directions, dtype=float).reshape(-1, 3)
    d = d / np.linalg.norm(d, axis=1, keepdims=True)
    cosines = np.clip(d @ d.T, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosines.min())))


def height_sensitivity(origins, directions, xyz, *, pointing_px=0.3,
                       focal_px=None):
    """How many map units of height one pixel of pointing error costs.

    The number that decides whether a pair can answer the question
    being asked of it. Measured rather than derived from a nominal
    base-to-height ratio: each ray is tilted by ``pointing_px /
    focal_px`` radians in the plane that moves the solution most, and
    the change in the solved Z is reported.
    """
    if focal_px is None:
        raise ValueError("focal_px is needed to turn pixels into an angle")
    o = np.asarray(origins, dtype=float).reshape(-1, 3)
    d = np.asarray(directions, dtype=float).reshape(-1, 3)
    d = d / np.linalg.norm(d, axis=1, keepdims=True)
    tilt = pointing_px / float(focal_px)
    worst = 0.0
    for i in range(len(d)):
        # a perpendicular in the vertical plane containing this ray
        axis = np.cross(d[i], [0.0, 0.0, 1.0])
        n = np.linalg.norm(axis)
        if n < 1e-12:
            continue
        axis = axis / n
        for sign in (+1.0, -1.0):
            nudged = d.copy()
            nudged[i] = d[i] + sign * tilt * np.cross(axis, d[i])
            try:
                moved, _ = intersect(o, nudged)
            except (ValueError, np.linalg.LinAlgError):
                continue
            worst = max(worst, abs(float(moved[2] - xyz[2])))
    return worst
