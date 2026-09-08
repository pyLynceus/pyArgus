"""Ground classification: SMRF, implemented in the math core.

A Simple Morphological Filter after Pingel, Clarke & Nelson (2013),
"An improved simple morphological filter for the terrain classification
of airborne LIDAR data" -- the same algorithm PDAL ships as
``filters.smrf``. It lives here as ~150 lines of numpy/scipy instead of
a PDAL dependency because python-pdal has no Windows wheel (it wants
the C++ SDK and a compiler; see HANDOFF.md), and because a from-scratch
implementation is testable against constructed truth the way the rest
of the core is.

The shape of it:

1. Grid the minimum z per cell and inpaint empty cells.
2. Optionally knock out low outliers (cells far below their
   neighborhood median) before they anchor the surface.
3. Open the surface with growing disk windows; a cell that drops more
   than ``slope * radius`` under any opening is an object cell
   (buildings and canopy collapse under large windows, terrain does
   not).
4. Inpaint a provisional DEM from the surviving cells, and classify
   each point against it: ground when |z - dem| <= threshold +
   scalar * dem_slope, the per-cell allowance loosening on steep
   ground exactly as PDAL's implementation does.

All parameters are in map units; the classic meter defaults (cell 1.0,
slope 0.15, window 18, threshold 0.5, scalar 1.25) scale to survey feet
as cell 3, window 60, threshold 1.5.

Feed it the returns that can see the ground -- last returns, when
return numbers exist. It classifies what it is given; the CLI does that
filtering.
"""

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from pyargus.core import gridding


@dataclass
class GroundResult:
    ground: np.ndarray        # bool per input point
    dem: np.ndarray           # provisional ground surface, [ix, iy]
    dem_slope: np.ndarray     # |grad dem|, dimensionless rise/run
    object_cells: np.ndarray  # bool grid: rejected by the opening
    low_cells: np.ndarray     # bool grid: rejected as low outliers
    x_edges: np.ndarray
    y_edges: np.ndarray

    @property
    def ground_fraction(self):
        return float(self.ground.mean())


def _disk(radius):
    span = np.arange(-radius, radius + 1)
    dx, dy = np.meshgrid(span, span, indexing="ij")
    return dx * dx + dy * dy <= radius * radius


def _progressive_opening(surface, max_radius, depth_at):
    """Flag cells that drop more than depth_at(radius) under growing openings."""
    flagged = np.zeros(surface.shape, dtype=bool)
    last = surface
    for radius in range(1, max_radius + 1):
        opened = ndimage.grey_opening(last, footprint=_disk(radius),
                                      mode="nearest")
        flagged |= (last - opened) > depth_at(radius)
        last = opened
    return flagged


def smrf(x, y, z, *, cell=1.0, slope=0.15, window=18.0, threshold=0.5,
         scalar=1.25, low_cut=None):
    """Classify points as ground/not-ground. Returns a GroundResult.

    ``low_cut`` (map units), when set, first discards minimum-surface
    cells that sit more than that depth below the opened INVERTED
    surface at any window -- clustered low outliers otherwise become
    the provisional ground and drag their whole neighborhood down,
    because an opening removes bumps, never pits.

    **Leave it off under canopy.** In forest the minimum surface is
    salt-and-pepper -- cells where the lidar punched through sit tens
    of feet below canopy-only neighbors -- and ANY cell-level pit
    detector reads exactly those ground penetrations as outliers
    (Summerville: 144k cells flagged, the DEM pushed up into the
    canopy, false ground 39 ft in the air). The symmetric |z - dem|
    bound in the point stage already rejects low points; ``low_cut``
    is only for open-terrain clouds genuinely contaminated with
    clustered low blunders. Two designs failed before this one and are
    recorded here so they are not tried again: a 3x3-median cut misses
    clustered pits (a pit is its own median), and scaling the inverted
    threshold by slope*radius reads every ditch as an outlier.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    if x.size == 0:
        raise ValueError("no points")
    if window < cell:
        raise ValueError("window must be at least one cell")

    x_edges, y_edges = gridding.grid_edges(x, y, cell)
    zmin = gridding.min_grid(x, y, z, x_edges, y_edges)
    surface = gridding.inpaint_nearest(zmin)
    max_radius = max(1, int(np.ceil(window / cell)))

    low_cells = np.zeros(zmin.shape, dtype=bool)
    if low_cut is not None:
        low_cells = _progressive_opening(-surface, max_radius,
                                         lambda radius: low_cut)
        zmin = np.where(low_cells, np.nan, zmin)
        surface = gridding.inpaint_nearest(zmin)

    object_cells = _progressive_opening(
        surface, max_radius, lambda radius: slope * radius * cell)

    keep = ~object_cells & ~low_cells & np.isfinite(zmin)
    if not keep.any():
        raise ValueError("no ground cells survived; parameters reject the "
                         "entire surface")
    dem = gridding.inpaint_nearest(np.where(keep, zmin, np.nan))
    gx, gy = np.gradient(dem, cell)
    dem_slope = np.hypot(gx, gy)

    dem_at = gridding.bilinear_sample(dem, x, y, x_edges, y_edges)
    slope_at = gridding.bilinear_sample(dem_slope, x, y, x_edges, y_edges)
    allowance = threshold + scalar * slope_at
    ground = np.abs(z - dem_at) <= allowance

    return GroundResult(ground=ground, dem=dem, dem_slope=dem_slope,
                        object_cells=object_cells, low_cells=low_cells,
                        x_edges=x_edges, y_edges=y_edges)


def confusion(predicted, reference):
    """Score a ground mask against a reference mask.

    Returns a dict with the four cells plus agreement, precision and
    recall for ground, and Cohen's kappa. The reference is whatever you
    trust -- on Summerville, the delivered classification -- and the
    numbers say how far this filter is from it, not which one is right.
    """
    predicted = np.asarray(predicted, dtype=bool)
    reference = np.asarray(reference, dtype=bool)
    if predicted.shape != reference.shape:
        raise ValueError("masks must share a shape")
    n = predicted.size
    if n == 0:
        raise ValueError("empty masks")
    tp = int(np.count_nonzero(predicted & reference))
    fp = int(np.count_nonzero(predicted & ~reference))
    fn = int(np.count_nonzero(~predicted & reference))
    tn = n - tp - fp - fn
    agreement = (tp + tn) / n
    expected = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n)
    kappa = ((agreement - expected) / (1.0 - expected)
             if expected < 1.0 else 1.0)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "agreement": agreement,
        "precision": tp / (tp + fp) if tp + fp else float("nan"),
        "recall": tp / (tp + fn) if tp + fn else float("nan"),
        "kappa": kappa,
    }
