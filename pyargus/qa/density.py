"""Point density on a regular grid."""

import numpy as np

from pyargus.core.gridding import grid_edges  # shared; re-exported here

__all__ = ["grid_edges", "density_grid", "density_grid_streamed"]


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

    ``mins``/``maxs`` are the cloud's horizontal extent, which the LAS
    header already knows -- so the edges are fixed before a single
    point is read and every chunk votes into the same bins. A counting
    histogram is exactly summable, so this returns bit-identical
    numbers to ``density_grid`` on the same points; the test asserts
    that rather than trusting it.
    """
    mins = np.asarray(mins, dtype=float)
    maxs = np.asarray(maxs, dtype=float)
    # grid_edges takes COORDINATES, not corners: hand it the x range
    # and the y range separately, or the two axes fold together
    x_edges, y_edges = grid_edges(np.array([mins[0], maxs[0]]),
                                  np.array([mins[1], maxs[1]]), cell)
    counts = np.zeros((x_edges.size - 1, y_edges.size - 1))
    total = 0
    for chunk in chunks:
        x = np.asarray(chunk["x"], dtype=float)
        if x.size == 0:
            continue
        part, _, _ = np.histogram2d(x, np.asarray(chunk["y"], dtype=float),
                                    bins=[x_edges, y_edges])
        counts += part
        total += x.size
    if total == 0:
        raise ValueError("no points")
    return counts / (cell * cell), x_edges, y_edges
