"""The direct-georeferencing forward model.

    X_ground = X_nav + R_nav(rpy) @ (R_bore @ x_scan + lever)

where ``X_nav`` is the trajectory position at the return's GPS time,
``R_nav`` the navigation attitude, ``x_scan`` the ranging vector in the
scanner frame, ``R_bore`` the fixed boresight misalignment, and
``lever`` the IMU-to-scanner lever arm in the body frame.

This is the model the Phase-4 strip adjustment linearizes: the solver's
unknowns are the boresight angles (and per-strip corrections), and its
observations are surface-patch mismatches in strip overlaps. Frame and
sign conventions here are internally consistent and tested against
synthetic geometry, but they have NOT yet been validated against real
TrueView 660 data -- do not trust them across that boundary until
HANDOFF.md says otherwise.
"""

import numpy as np

from pyargus.core import rotation


def ground_points(nav_xyz, rpy, scan_vecs, boresight_rpy=(0.0, 0.0, 0.0),
                  lever_arm=(0.0, 0.0, 0.0)):
    """Ground coordinates for N returns.

    nav_xyz : (N, 3) trajectory positions, mapping frame
    rpy : (N, 3) roll, pitch, yaw in radians
    scan_vecs : (N, 3) ranging vectors in the scanner frame
    boresight_rpy : three angles in radians, fixed for the whole strip
    lever_arm : (3,) IMU-to-scanner offset in the body frame

    Returns (N, 3) ground coordinates.
    """
    nav_xyz = np.asarray(nav_xyz, dtype=float)
    rpy = np.asarray(rpy, dtype=float)
    scan_vecs = np.asarray(scan_vecs, dtype=float)
    if nav_xyz.shape != rpy.shape or nav_xyz.shape != scan_vecs.shape:
        raise ValueError("nav_xyz, rpy and scan_vecs must share one (N, 3) shape")

    r_bore = rotation.matrix(*boresight_rpy)
    body_vecs = scan_vecs @ r_bore.T + np.asarray(lever_arm, dtype=float)
    r_nav = rotation.matrices(rpy[:, 0], rpy[:, 1], rpy[:, 2])
    return nav_xyz + np.einsum("nij,nj->ni", r_nav, body_vecs)
