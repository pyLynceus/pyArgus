"""Regular grids over point clouds: the primitives everything shares.

Grids throughout the suite are indexed [ix, iy] with both axes
ascending (x east, y north), edges aligned to multiples of the cell
size. ``qa.raster.grid_to_image`` is the one place this becomes image
rows; nothing else reorients.
"""

import numpy as np


MAX_GRID_CELLS = 25_000_000
"""Admission ceiling for dense rasters; not a guarantee about process RSS."""


def check_grid_shape(nx, ny, *, extent=None, cell=None):
    """Refuse excessive rasters before allocating edges, tiles or surfaces."""
    nx, ny = int(nx), int(ny)
    if nx < 1 or ny < 1:
        raise ValueError("Grid dimensions must be positive")
    cells = nx * ny  # Python integers, so the product cannot overflow.
    if cells > MAX_GRID_CELLS:
        detail = f"; XY extent {extent}, cell {cell:g}" if extent is not None else ""
        raise ValueError(
            f"Grid requires {nx:,} x {ny:,} = {cells:,} cells{detail}; "
            f"the dense-grid safety limit is {MAX_GRID_CELLS:,}. "
            "Check XY outliers and stale header bounds, increase the cell "
            "size, or select a smaller block. Tiling does not remove the "
            "global raster allocation.")
    return nx, ny


def grid_edges(x, y, cell):
    """Cell edges covering finite data, with admission before allocation."""
    x, y = np.asarray(x), np.asarray(y)
    if not np.isfinite(cell) or cell <= 0:
        raise ValueError("cell must be positive and finite")
    if not x.size or not y.size:
        raise ValueError("Grid coordinates must be nonempty and finite")
    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(y.min()), float(y.max())
    # Min/max propagate NaNs and expose infinities without allocating a
    # full-cloud boolean mask just to admit a raster.
    if not np.isfinite([xmin, xmax, ymin, ymax]).all():
        raise ValueError("Grid coordinates must be nonempty and finite")
    x0 = np.floor(xmin / cell) * cell
    y0 = np.floor(ymin / cell) * cell
    widths = np.array([(xmax - x0) / cell, (ymax - y0) / cell])
    if not np.isfinite(widths).all():
        raise ValueError("Grid extent/cell ratio is not finite")
    nx, ny = max(1, int(np.ceil(widths[0]))), max(1, int(np.ceil(widths[1])))
    check_grid_shape(nx, ny, extent=(xmin, ymin, xmax, ymax), cell=cell)
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
    check_grid_shape(len(x_edges) - 1, len(y_edges) - 1)
    ix, iy = cell_indices(x, y, x_edges, y_edges)
    grid = np.full((len(x_edges) - 1, len(y_edges) - 1), np.inf)
    np.minimum.at(grid, (ix, iy), z)
    grid[~np.isfinite(grid)] = np.nan
    return grid


def max_grid(x, y, z, x_edges, y_edges):
    """Per-cell maximum z; empty cells are NaN. The DSM primitive."""
    check_grid_shape(len(x_edges) - 1, len(y_edges) - 1)
    ix, iy = cell_indices(x, y, x_edges, y_edges)
    grid = np.full((len(x_edges) - 1, len(y_edges) - 1), -np.inf)
    np.maximum.at(grid, (ix, iy), z)
    grid[~np.isfinite(grid)] = np.nan
    return grid


def mean_grid(x, y, z, x_edges, y_edges):
    """Per-cell mean z; empty cells are NaN."""
    check_grid_shape(len(x_edges) - 1, len(y_edges) - 1)
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
    check_grid_shape(*grid.shape)
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


def coverage_mask(x, y, x_edges, y_edges, max_distance=0):
    """True where a cell holds data or lies within ``max_distance``
    cells of one. The guard that keeps interpolating surfaces (a TIN
    spans every interior void) from inventing terrain across lakes."""
    from scipy.ndimage import distance_transform_edt

    ix, iy = cell_indices(np.asarray(x, dtype=float),
                          np.asarray(y, dtype=float), x_edges, y_edges)
    occupied = np.zeros((len(x_edges) - 1, len(y_edges) - 1), dtype=bool)
    occupied[ix, iy] = True
    if max_distance <= 0:
        return occupied
    return distance_transform_edt(~occupied) <= max_distance


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
