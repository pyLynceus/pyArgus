"""SMRF over a cloud larger than memory: tiles with a halo.

Ground classification is the last consumer in this suite that wanted
the whole cloud at once, which put a 900M-point block (SH 151: 22
strips, 27.6 GB) out of reach however well the reads streamed. The way
past it is the shape of the algorithm itself:

* the expensive half of SMRF produces a RASTER -- a DEM and its slope.
  At 3 ft cells a 13,700 ft corridor is a few megabytes, so the
  surface for an entire project fits in memory easily even when its
  points do not;
* the cheap half judges each point against that raster, one bilinear
  sample, which streams perfectly.

So: build the surface tile by tile, assemble one global raster, then
classify the points in a single streaming pass. Bounded memory, and
the answer is the whole-cloud answer wherever the halo is wide enough.

THE HALO IS THE WHOLE PROBLEM. SMRF's progressive opening is
ITERATIVE -- each round opens the PREVIOUS round's output, not the
original surface -- so influence accumulates. One opening of radius r
reaches 2r cells; the cascade r = 1..R reaches sum(2r) = R(R+1). At
the survey-feet defaults (cell 3, window 60) that is R = 20 and a
theoretical bound of 420 cells, 1,260 ft. That bound is not tight:
openings converge, and a perturbation usually dies within a few cells.
But "usually" is not a guarantee, and a tile seam that silently
classifies differently from the whole-cloud run is exactly the defect
this suite refuses to ship, so ``required_halo`` returns the BOUND and
that is the default.

MEASURED, on a hard synthetic scene (rolling terrain, canopy, and a
building deliberately straddling the seam; cell 3, window 30, so the
bound is 330 units):

    halo 0    DEM wrong by up to 30.7 units, 197 points misclassified
    halo 12   DEM exact, 8 points still differ (the slope raster)
    halo 60   exact: identical DEM and identical ground mask
    halo 330  exact

So twice the window sufficed there, a quarter of the bound. A caller
who knows their terrain may say so; ``MINIMUM_HALO_WINDOWS`` is the
floor below which this refuses, because a SINGLE opening already
reaches 2 * window and no scene can be safe under that.
"""

from dataclasses import dataclass

import numpy as np

from pyargus.classify import ground as ground_mod
from pyargus.core import gridding


MINIMUM_HALO_WINDOWS = 2.0
"""A halo below this many windows cannot be right for any scene: one
opening of the largest radius alone reaches 2 * window."""


def required_halo(cell, window):
    """Map units of overlap a tile needs on every side.

    The exact reach of the opening cascade: radius r reaches 2r cells
    and the rounds compose, so R(R+1) cells where R = ceil(window /
    cell). Shrinking this is a decision about risk, not a free
    parameter -- see the module docstring.
    """
    if cell <= 0:
        raise ValueError(f"cell must be positive, got {cell}")
    if window < cell:
        raise ValueError("window must be at least one cell")
    radius = max(1, int(np.ceil(window / cell)))
    return float(radius * (radius + 1) * cell)


def global_edges(mins, maxs, cell):
    """One lattice for the whole project.

    Every tile's own ``grid_edges`` would floor to the same multiples
    of ``cell``, so tiles are already in phase; taking the edges from
    the project extent makes the shared indexing explicit instead of
    incidental.
    """
    mins = np.asarray(mins, dtype=float)
    maxs = np.asarray(maxs, dtype=float)
    return gridding.grid_edges(np.array([mins[0], maxs[0]]),
                               np.array([mins[1], maxs[1]]), cell)


@dataclass
class Tile:
    """One piece of work: what to read, and what to keep of it."""
    core: tuple      # ((min_e, min_n), (max_e, max_n)) -- kept
    halo: tuple      # the same box grown by the halo -- read
    ix: int          # core's first column in the global grid
    iy: int          # core's first row


def plan_tiles(x_edges, y_edges, cell, halo, tile_size):
    """Cover the grid with tiles whose cores tile it exactly."""
    if tile_size <= 0:
        raise ValueError(f"tile_size must be positive, got {tile_size}")
    step = max(1, int(round(tile_size / cell)))
    pad = int(np.ceil(halo / cell))
    nx = x_edges.size - 1
    ny = y_edges.size - 1
    tiles = []
    for ix in range(0, nx, step):
        for iy in range(0, ny, step):
            ix1 = min(ix + step, nx)
            iy1 = min(iy + step, ny)
            hx0, hx1 = max(0, ix - pad), min(nx, ix1 + pad)
            hy0, hy1 = max(0, iy - pad), min(ny, iy1 + pad)
            tiles.append(Tile(
                core=((x_edges[ix], y_edges[iy]),
                      (x_edges[ix1], y_edges[iy1])),
                halo=((x_edges[hx0], y_edges[hy0]),
                      (x_edges[hx1], y_edges[hy1])),
                ix=ix, iy=iy))
    return tiles


def tiled_surface(read, mins, maxs, *, cell=1.0, slope=0.15, window=18.0,
                  low_cut=None, tile_size=None, halo=None, progress=None):
    """Build one project-wide ground surface, tile by tile.

    ``read(bounds)`` returns (x, y, z) for a box -- a COPC query, a
    streaming cull, whatever the caller has. It is called once per
    tile with the HALO box, and only the core cells of the result are
    kept, so the seams carry the same values a whole-cloud run would
    have produced.

    Returns a GroundSurface on the project lattice. Tiles with no
    points are left NaN in the DEM and filled at the end, so an empty
    corner does not abort the run.
    """
    x_edges, y_edges = global_edges(mins, maxs, cell)
    if halo is None:
        halo = required_halo(cell, window)
    else:
        floor = MINIMUM_HALO_WINDOWS * window
        if halo < floor:
            raise ValueError(
                f"a halo of {halo:g} map units cannot be right: one "
                f"opening at the largest radius already reaches "
                f"2 * window = {floor:g}, and SMRF's cascade reaches "
                f"{required_halo(cell, window):g}. Tiling with less "
                f"classifies seams differently from a whole-cloud run "
                f"(measured: no halo put a 30-unit error in the DEM "
                f"where a building straddled a seam).")
    if tile_size is None:
        # cores six halos wide: the read overlap then costs about 1.8x
        # the area, against 2.25x at four and 9x at one
        tile_size = max(6.0 * halo, 50.0 * cell)
    tiles = plan_tiles(x_edges, y_edges, cell, halo, tile_size)

    shape = (x_edges.size - 1, y_edges.size - 1)
    dem = np.full(shape, np.nan)
    dem_slope = np.full(shape, np.nan)
    object_cells = np.zeros(shape, dtype=bool)
    low_cells = np.zeros(shape, dtype=bool)
    filled = 0
    for n, tile in enumerate(tiles, start=1):
        if progress is not None:
            progress(n, len(tiles), tile)
        x, y, z = read(tile.halo)
        x = np.asarray(x, dtype=float)
        if x.size == 0:
            continue
        y = np.asarray(y, dtype=float)
        z = np.asarray(z, dtype=float)
        # the tile's own lattice, in phase with the project's
        hx0 = int(round((tile.halo[0][0] - x_edges[0]) / cell))
        hy0 = int(round((tile.halo[0][1] - y_edges[0]) / cell))
        hx1 = int(round((tile.halo[1][0] - x_edges[0]) / cell))
        hy1 = int(round((tile.halo[1][1] - y_edges[0]) / cell))
        local = ground_mod.ground_surface(
            x, y, z, x_edges[hx0:hx1 + 1], y_edges[hy0:hy1 + 1],
            cell=cell, slope=slope, window=window, low_cut=low_cut)
        cx0 = int(round((tile.core[0][0] - x_edges[0]) / cell))
        cy0 = int(round((tile.core[0][1] - y_edges[0]) / cell))
        cx1 = int(round((tile.core[1][0] - x_edges[0]) / cell))
        cy1 = int(round((tile.core[1][1] - y_edges[0]) / cell))
        sx, sy = cx0 - hx0, cy0 - hy0
        ex, ey = sx + (cx1 - cx0), sy + (cy1 - cy0)
        dem[cx0:cx1, cy0:cy1] = local.dem[sx:ex, sy:ey]
        dem_slope[cx0:cx1, cy0:cy1] = local.dem_slope[sx:ex, sy:ey]
        object_cells[cx0:cx1, cy0:cy1] = local.object_cells[sx:ex, sy:ey]
        low_cells[cx0:cx1, cy0:cy1] = local.low_cells[sx:ex, sy:ey]
        filled += 1
    if filled == 0:
        raise ValueError("no tile held any points")
    if not np.isfinite(dem).any():
        raise ValueError("no ground cells survived in any tile")
    dem = gridding.inpaint_nearest(dem)
    dem_slope = np.where(np.isfinite(dem_slope), dem_slope, 0.0)
    return ground_mod.GroundSurface(
        dem=dem, dem_slope=dem_slope, object_cells=object_cells,
        low_cells=low_cells, x_edges=x_edges, y_edges=y_edges)
