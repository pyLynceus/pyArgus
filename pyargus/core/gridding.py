"""Regular grids over point clouds: the primitives everything shares.

Grids throughout the suite are indexed [ix, iy] with both axes
ascending (x east, y north), edges aligned to multiples of the cell
size. ``qa.raster.grid_to_image`` is the one place this becomes image
rows; nothing else reorients.
"""

import numpy as np


def grid_edges(x, y, cell):
    """Cell edges covering the data, aligned to multiples of ``cell``."""
    x0 = np.floor(x.min() / cell) * cell
    y0 = np.floor(y.min() / cell) * cell
    nx = int(np.ceil((x.max() - x0) / cell)) or 1
    ny = int(np.ceil((y.max() - y0) / cell)) or 1
    return x0 + np.arange(nx + 1) * cell, y0 + np.arange(ny + 1) * cell


def cell_indices(x, y, x_edges, y_edges):
    """(ix, iy) of each point; the max edge folds into the last cell."""
    cell_x = x_edges[1] - x_edges[0]
    cell_y = y_edges[1] - y_edges[0]
    ix = np.clip(((x - x_edges[0]) / cell_x).astype(np.intp), 0,
                 len(x_edges) - 2)
    iy = np.clip(((y - y_edges[0]) / cell_y).astype(np.intp), 0,
                 len(y_edges) - 2)
    return ix, iy


def min_grid(x, y, z, x_edges, y_edges):
    """Per-cell minimum z; empty cells are NaN."""
    ix, iy = cell_indices(x, y, x_edges, y_edges)
    grid = np.full((len(x_edges) - 1, len(y_edges) - 1), np.inf)
    np.minimum.at(grid, (ix, iy), z)
    grid[~np.isfinite(grid)] = np.nan
    return grid


def mean_grid(x, y, z, x_edges, y_edges):
    """Per-cell mean z; empty cells are NaN."""
    ix, iy = cell_indices(x, y, x_edges, y_edges)
    shape = (len(x_edges) - 1, len(y_edges) - 1)
    total = np.zeros(shape)
    count = np.zeros(shape)
    np.add.at(total, (ix, iy), z)
    np.add.at(count, (ix, iy), 1.0)
    with np.errstate(invalid="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def inpaint_nearest(grid, max_distance=None):
    """Fill NaN cells with the value of the nearest finite cell.

    ``max_distance`` (in cells) limits how far a value may travel; cells
    farther from data than that stay NaN, so a DTM does not invent
    ground across a lake or past the project boundary.
    """
    from scipy.ndimage import distance_transform_edt

    grid = np.asarray(grid, dtype=float)
    missing = ~np.isfinite(grid)
    if not missing.any():
        return grid.copy()
    if not (~missing).any():
        raise ValueError("grid has no finite cells to inpaint from")
    distance, (jx, jy) = distance_transform_edt(missing, return_indices=True)
    filled = grid[jx, jy]
    if max_distance is not None:
        filled = np.where(distance <= max_distance, filled, np.nan)
    return np.where(missing, filled, grid)


def bilinear_sample(grid, x, y, x_edges, y_edges):
    """Sample a finite [ix, iy] grid at point locations, bilinearly.

    Coordinates are taken relative to cell centers and clipped to the
    grid, so points in the outer half-cell ring read the edge value.
    """
    from scipy.ndimage import map_coordinates

    cell_x = x_edges[1] - x_edges[0]
    cell_y = y_edges[1] - y_edges[0]
    fx = (np.asarray(x, dtype=float) - x_edges[0]) / cell_x - 0.5
    fy = (np.asarray(y, dtype=float) - y_edges[0]) / cell_y - 0.5
    fx = np.clip(fx, 0, grid.shape[0] - 1)
    fy = np.clip(fy, 0, grid.shape[1] - 1)
    return map_coordinates(grid, [fx, fy], order=1, mode="nearest")
