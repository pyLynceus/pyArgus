"""Checkpoint accuracy per the ASPRS Positional Accuracy Standards.

Residual convention throughout: dz = lidar surface minus checkpoint, so
a positive residual means the cloud floats above the control.

Statistics follow the ASPRS Positional Accuracy Standards for Digital
Geospatial Data (2014 edition): NVA = 1.96 * RMSEz for non-vegetated
terrain, VVA = 95th percentile of absolute error for vegetated. The
2023 edition reorganizes these; when a project cites it, add the 2023
computation beside this one rather than silently changing numbers.
"""

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import LinearNDInterpolator


@dataclass
class VerticalAccuracy:
    n: int
    mean: float
    rmse_z: float
    nva: float       # 1.96 * RMSEz
    p95_abs: float   # VVA when the checkpoints are vegetated-terrain points


def vertical_residuals(surface_xyz, check_xyz):
    """dz at each checkpoint against a TIN of the surface points.

    surface_xyz : (N, 3) ground-classified points
    check_xyz : (M, 3) surveyed checkpoints

    Returns (M,) residuals; a checkpoint outside the surface's convex
    hull gets NaN -- report it as untestable, never interpolate past
    the data.
    """
    surface_xyz = np.asarray(surface_xyz, dtype=float)
    check_xyz = np.asarray(check_xyz, dtype=float)
    if surface_xyz.shape[0] < 3:
        raise ValueError("need at least 3 surface points to triangulate")
    tin = LinearNDInterpolator(surface_xyz[:, :2], surface_xyz[:, 2])
    surface_z = tin(check_xyz[:, :2])
    return surface_z - check_xyz[:, 2]


def asprs_vertical(dz):
    """Vertical accuracy statistics from finite residuals.

    Refuses NaN input: dropping untestable checkpoints is a reporting
    decision the caller makes visibly, not one this function hides.
    """
    dz = np.asarray(dz, dtype=float)
    if dz.size == 0:
        raise ValueError("no residuals")
    if not np.all(np.isfinite(dz)):
        raise ValueError(
            "residuals contain NaN/inf; filter untestable checkpoints "
            "explicitly and report how many were dropped")
    rmse = float(np.sqrt(np.mean(dz ** 2)))
    return VerticalAccuracy(
        n=int(dz.size),
        mean=float(np.mean(dz)),
        rmse_z=rmse,
        nva=1.96 * rmse,
        p95_abs=float(np.percentile(np.abs(dz), 95)),
    )
