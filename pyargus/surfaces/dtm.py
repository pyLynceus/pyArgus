"""DTM grids, and writing them somewhere GIS can read.

The grid is the per-cell mean of ground returns, filled only within
``max_fill`` cells of real data -- a DTM must not invent ground across
a lake or past the project boundary, so everything farther stays
nodata. Output is ESRI ASCII grid (.asc): plain text, no GDAL, loads
in QGIS, Global Mapper, LP360 and everything else. GeoTIFF can join in
a later phase when GDAL earns its place in the dependency tree.
"""

import numpy as np

from pyargus.core import gridding


def dtm_grid(x, y, z, cell, max_fill=10):
    """Mean-of-ground DTM. Returns (grid, x_edges, y_edges); gaps beyond
    ``max_fill`` cells from data are NaN."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    if x.size == 0:
        raise ValueError("no ground points")
    x_edges, y_edges = gridding.grid_edges(x, y, cell)
    grid = gridding.mean_grid(x, y, z, x_edges, y_edges)
    if max_fill:
        grid = gridding.inpaint_nearest(grid, max_distance=max_fill)
    return grid, x_edges, y_edges


def write_esri_ascii(path, grid, x_edges, y_edges, nodata=-9999.0):
    """Write an [ix, iy] grid as an ESRI ASCII raster (rows north-first)."""
    grid = np.asarray(grid, dtype=float)
    cell_x = float(x_edges[1] - x_edges[0])
    cell_y = float(y_edges[1] - y_edges[0])
    if not np.isclose(cell_x, cell_y):
        raise ValueError(".asc requires square cells")
    rows = np.where(np.isfinite(grid), grid, nodata).T[::-1]
    header = (f"ncols {grid.shape[0]}\n"
              f"nrows {grid.shape[1]}\n"
              f"xllcorner {float(x_edges[0]):.6f}\n"
              f"yllcorner {float(y_edges[0]):.6f}\n"
              f"cellsize {cell_x:.6f}\n"
              f"NODATA_value {nodata:g}\n")
    with open(path, "w", newline="\n") as fh:
        fh.write(header)
        np.savetxt(fh, rows, fmt="%.3f")
