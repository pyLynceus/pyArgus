"""Rotation conventions for navigation attitude.

One convention, stated once: ``matrix(roll, pitch, yaw)`` returns

    R = Rz(yaw) @ Ry(pitch) @ Rx(roll)

mapping body-frame vectors into the local-level frame, angles in
radians, +Z up. This is the same Rz*Ry*Rx / +Z-axis convention that was
proven correct for the TrueView 660 EO work in pyLynceus -- and the same
territory where two vendor conventions have already burned us (LP360's
Omega/Phi/Kappa columns are not this, and ATLAS negates all three
angles). Any new data source gets its angles validated against known
geometry before this module is trusted with them.
"""

import numpy as np


def matrix(roll, pitch, yaw):
    """Rotation matrix R = Rz(yaw) @ Ry(pitch) @ Rx(roll), angles in radians."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    return np.array([
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ])


def matrices(roll, pitch, yaw):
    """Vectorized ``matrix``: three length-N arrays in, (N, 3, 3) out."""
    roll = np.asarray(roll, dtype=float)
    pitch = np.asarray(pitch, dtype=float)
    yaw = np.asarray(yaw, dtype=float)
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    out = np.empty(roll.shape + (3, 3))
    out[..., 0, 0] = cy * cp
    out[..., 0, 1] = cy * sp * sr - sy * cr
    out[..., 0, 2] = cy * sp * cr + sy * sr
    out[..., 1, 0] = sy * cp
    out[..., 1, 1] = sy * sp * sr + cy * cr
    out[..., 1, 2] = sy * sp * cr - cy * sr
    out[..., 2, 0] = -sp
    out[..., 2, 1] = cp * sr
    out[..., 2, 2] = cp * cr
    return out


def angles(R):
    """Recover (roll, pitch, yaw) from a matrix built by ``matrix``.

    Valid for pitch strictly inside (-pi/2, pi/2); at the gimbal poles
    roll and yaw are not separable and this raises rather than picking
    one of the infinitely many answers.
    """
    R = np.asarray(R)
    sp = -R[2, 0]
    if abs(sp) >= 1.0 - 1e-12:
        raise ValueError("pitch at +/-90 degrees: roll and yaw are not separable")
    pitch = np.arcsin(sp)
    roll = np.arctan2(R[2, 1], R[2, 2])
    yaw = np.arctan2(R[1, 0], R[0, 0])
    return roll, pitch, yaw
