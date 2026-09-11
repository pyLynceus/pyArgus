"""Point density on a regular grid."""

import numpy as np

from pyargus.core.gridding import grid_edges  # shared; re-exported here

__all__ = ["grid_edges", "density_grid", "density_grid_streamed",
           "scan_extent"]


def density_grid(x, y, cell=1.0):
    """Points per square unit on a ``cell``-sized grid.

    Returns (density, x_edges, y_edges); density is indexed [ix, iy].
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0:
        raise ValueError("no points")
    x_edges, y_edges = grid_edges(x, y, cell)
    counts, _, _ = np.histogram2d(x, y, bins=[x_edges, y_edges])
    return counts / (cell * cell), x_edges, y_edges


def density_grid_streamed(chunks, mins, maxs, cell=1.0):
    """The same grid, accumulated over chunks instead of one array.

    ``mins``/``maxs`` are the cloud's horizontal extent -- normally
    the LAS header's, so the edges are fixed before a single point is
    read and every chunk votes into the same bins. A counting
    histogram is exactly summable, so this returns bit-identical
    numbers to ``density_grid`` on the same points.

    THE HEADER IS NOT ALWAYS RIGHT. A clip, an edit or a reprojection
    that never rewrote min/max leaves a box that does not contain the
    data, and ``np.histogram2d`` DISCARDS samples outside its explicit
    bins -- silently. ``density_grid`` derives its edges from the
    points and counts all of them, so the two would disagree while
    both printed a believable density on the suite's own QA metric.
    Every point outside the box is therefore counted and REFUSED:
    the caller is told the header is stale and what to do about it,
    rather than being handed a number computed from a subset.
    """
    mins = np.asarray(mins, dtype=float)
    maxs = np.asarray(maxs, dtype=float)
    # grid_edges takes COORDINATES, not corners: hand it the x range
    # and the y range separately, or the two axes fold together
    x_edges, y_edges = grid_edges(np.array([mins[0], maxs[0]]),
                                  np.array([mins[1], maxs[1]]), cell)
    counts = np.zeros((x_edges.size - 1, y_edges.size - 1))
    total = 0
    outside = 0
    for chunk in chunks:
        x = np.asarray(chunk["x"], dtype=float)
        if x.size == 0:
            continue
        y = np.asarray(chunk["y"], dtype=float)
        part, _, _ = np.histogram2d(x, y, bins=[x_edges, y_edges])
        counts += part
        total += x.size
        outside += int(x.size - part.sum())
    if total == 0:
        raise ValueError("no points")
    if outside:
        raise ValueError(
            f"{outside:,} of {total:,} points fall outside the declared "
            f"extent {mins[:2]} .. {maxs[:2]}, so a grid fixed to it would "
            f"silently ignore them. The file's header does not describe "
            f"its own points -- rewrite the header, or rescan the extent "
            f"from the points first.")
    return counts / (cell * cell), x_edges, y_edges


def scan_extent(chunks):
    """True horizontal extent, one chunk at a time.

    For the case above: when the header cannot be trusted, a first
    streaming pass costs a second read but yields a box that provably
    contains every point.
    """
    lo = np.array([np.inf, np.inf])
    hi = np.array([-np.inf, -np.inf])
    seen = 0
    for chunk in chunks:
        x = np.asarray(chunk["x"], dtype=float)
        if x.size == 0:
            continue
        y = np.asarray(chunk["y"], dtype=float)
        lo = np.minimum(lo, [x.min(), y.min()])
        hi = np.maximum(hi, [x.max(), y.max()])
        seen += x.size
    if seen == 0:
        raise ValueError("no points")
    return lo, hi
