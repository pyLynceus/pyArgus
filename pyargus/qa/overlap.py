"""Strip-to-strip vertical disagreement.

The single most informative lidar QA product: per-cell median Z of each
strip, differenced where both strips have coverage. Systematic patterns
in this surface are what the Phase-4 alignment exists to remove --
roll error paints stripes across-track, pitch shifts along-track,
a range/lever error shows as a flat bias.
"""

from dataclasses import dataclass

import numpy as np
from scipy.stats import binned_statistic_2d

from pyargus.qa.density import grid_edges


@dataclass
class StripDz:
    dz: np.ndarray          # [ix, iy], median(b) - median(a), NaN off-overlap
    x_edges: np.ndarray
    y_edges: np.ndarray

    @property
    def overlap_cells(self):
        return int(np.count_nonzero(np.isfinite(self.dz)))

    def summary(self):
        """Robust summary of the overlap disagreement, in data units."""
        finite = self.dz[np.isfinite(self.dz)]
        if finite.size == 0:
            raise ValueError("no overlapping cells: strips do not overlap at this cell size")
        return {
            "cells": finite.size,
            "median": float(np.median(finite)),
            "rmse": float(np.sqrt(np.mean(finite ** 2))),
            "p95_abs": float(np.percentile(np.abs(finite), 95)),
        }


def strip_dz(a, b, cell=1.0, min_points=3):
    """Per-cell median-Z difference between two strips.

    a, b : dicts with at least x, y, z arrays (as from formats.las)
    Returns a StripDz with dz = median(b) - median(a). Cells where either
    strip has fewer than ``min_points`` points are NaN.

    On sloped or vegetated ground the raw median difference mixes
    alignment error with surface texture; this is the honest first-order
    map, and the patch-based measure in the alignment core is the
    refined one.
    """
    if a["x"].size == 0 or b["x"].size == 0:
        # An empty strip cannot overlap anything, and empty is exactly
        # what selecting ground returns yields on an unclassified cloud.
        # Report no overlap: callers already treat overlap_cells == 0 as
        # "nothing to compare". The alternative was a numpy reduction
        # error from deep inside grid_edges that named neither the strip
        # nor the cause.
        return StripDz(dz=np.zeros((0, 0)), x_edges=np.zeros(0),
                       y_edges=np.zeros(0))

    all_x = np.concatenate([a["x"], b["x"]])
    all_y = np.concatenate([a["y"], b["y"]])
    x_edges, y_edges = grid_edges(all_x, all_y, cell)
    bins = [x_edges, y_edges]

    med_a, _, _, _ = binned_statistic_2d(a["x"], a["y"], a["z"], "median", bins=bins)
    cnt_a, _, _, _ = binned_statistic_2d(a["x"], a["y"], a["z"], "count", bins=bins)
    med_b, _, _, _ = binned_statistic_2d(b["x"], b["y"], b["z"], "median", bins=bins)
    cnt_b, _, _, _ = binned_statistic_2d(b["x"], b["y"], b["z"], "count", bins=bins)

    valid = (cnt_a >= min_points) & (cnt_b >= min_points)
    dz = np.where(valid, med_b - med_a, np.nan)
    return StripDz(dz=dz, x_edges=x_edges, y_edges=y_edges)
