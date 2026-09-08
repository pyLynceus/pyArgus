"""Point density on a regular grid."""

import numpy as np

from pyargus.core.gridding import grid_edges  # shared; re-exported here

__all__ = ["grid_edges", "density_grid"]


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
