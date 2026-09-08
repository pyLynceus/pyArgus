"""Point density on a regular grid."""

import numpy as np


def grid_edges(x, y, cell):
    """Cell edges covering the data, aligned to multiples of ``cell``."""
    x0 = np.floor(x.min() / cell) * cell
    y0 = np.floor(y.min() / cell) * cell
    nx = int(np.ceil((x.max() - x0) / cell)) or 1
    ny = int(np.ceil((y.max() - y0) / cell)) or 1
    return x0 + np.arange(nx + 1) * cell, y0 + np.arange(ny + 1) * cell


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
