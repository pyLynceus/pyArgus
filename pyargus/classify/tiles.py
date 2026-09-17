"""SMRF over a cloud larger than memory: tiles with a halo.

Ground classification is the last consumer in this suite that wanted
the whole cloud at once, which put a 900M-point block (SH 151: 22
strips, 27.6 GB) out of reach however well the reads streamed. The way
past it is the shape of the algorithm itself:

* the expensive half of SMRF produces a RASTER -- a DEM, its slope and
  two masks. For a 10,569 ft SH 151 strip at 3 ft cells that is about
  24 MB, so the surface for an entire project fits in memory even when
  its points do not;
* the cheap half judges each point against that raster, one bilinear
  sample, which streams perfectly.

So: build the surface tile by tile, assemble one global raster, then
classify the points in a single streaming pass. The answer is the
whole-cloud answer wherever the halo is wide enough.

WHAT IS HELD AT ONCE is the points inside ONE tile's halo box -- the
core grown by the halo on every side -- not the raster. The halo is
fixed by SMRF's own reach (below), so the box can never be smaller
than about (2 * halo) on a side: at the survey-feet defaults that is
2,520 ft, and on a small project the default tile is the whole
project. ``--tile-size`` trades memory against re-reading: smaller
cores hold less, but the boxes overlap more, and every point in an
overlap is read once per box that holds it. ``plan_summary`` says
what a plan will cost before it runs.

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

EDGE_TOLERANCE = 1e-6
"""Cells of slack on the PROJECT's outer edges, for coordinates a
float's width outside the extent the header or scan reported. Such a
point folds into the edge cell, as it would in a whole-cloud run."""


def resolve_plan(cell, window, halo=None, tile_size=None):
    """(halo, tile_size) with the defaults filled in, or a refusal.

    The one place the defaults live, so the driver that logs a plan and
    the function that runs it cannot disagree about what was run.
    """
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
    return float(halo), float(tile_size)


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


def _cells(box, x_edges, y_edges):
    """A lattice-aligned box as cell indices (x0, y0, x1, y1)."""
    cell = x_edges[1] - x_edges[0]
    (bx0, by0), (bx1, by1) = box
    return (int(round((bx0 - x_edges[0]) / cell)),
            int(round((by0 - y_edges[0]) / cell)),
            int(round((bx1 - x_edges[0]) / cell)),
            int(round((by1 - y_edges[0]) / cell)))


def plan_summary(plan, x_edges, y_edges):
    """What a plan costs, before it runs.

    ``area_read`` sums the halo boxes over the project's area: how many
    times the tiles, between them, cover the cloud. With no index that
    is paid in passes AND in SMRF recomputed on the overlaps; a COPC
    index cuts the passes but not the overlap. ``largest_box`` is the
    biggest box's share of the project -- roughly the share of the
    cloud one tile holds at once. ``seamed`` counts the tiles whose box
    stops short of the project on some side: only those have seams at
    all, because a box spanning the whole project IS the whole-cloud
    run.
    """
    nx, ny = x_edges.size - 1, y_edges.size - 1
    total = float(nx * ny)
    shares, seamed = [], 0
    for tile in plan:
        hx0, hy0, hx1, hy1 = _cells(tile.halo, x_edges, y_edges)
        shares.append((hx1 - hx0) * (hy1 - hy0) / total)
        if hx0 > 0 or hy0 > 0 or hx1 < nx or hy1 < ny:
            seamed += 1
    return {"tiles": len(plan), "area_read": float(sum(shares)),
            "largest_box": float(max(shares)), "seamed": seamed}


def outside(x, y, x_edges, y_edges):
    """How many points fall off the project lattice (beyond the slack).

    A tiled run never reads such a point into any tile, and judging it
    against the surface would sample the edge cell -- a silent answer
    for a point the surface knows nothing about. So callers refuse.
    """
    slack = EDGE_TOLERANCE * (x_edges[1] - x_edges[0])
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    return int(np.count_nonzero(
        (x < x_edges[0] - slack) | (x > x_edges[-1] + slack)
        | (y < y_edges[0] - slack) | (y > y_edges[-1] + slack)))


def window_points(read, x_edges, y_edges, hx0, hy0, hx1, hy1):
    """The points of lattice cells [hx0, hx1) x [hy0, hy1).

    ``read(bounds)`` may be inclusive and may return extra points (a
    COPC query is node-granular); the cut here is what defines the
    window. It is HALF-OPEN on every interior edge: a point exactly on
    x_edges[hx1] belongs to column hx1, the next cell over, and folding
    it into this window's last column would give the tile a minimum
    the whole-cloud grid does not have there. Real coordinates are
    quantized and land on 3-ft grid lines constantly, so this is not a
    measure-zero case. On the project's own outer edges the window is
    closed, plus EDGE_TOLERANCE, exactly as ``gridding.cell_indices``
    folds the max edge into the last cell for a whole-cloud run.
    """
    nx, ny = x_edges.size - 1, y_edges.size - 1
    slack = EDGE_TOLERANCE * (x_edges[1] - x_edges[0])
    lo_x = x_edges[hx0] - (slack if hx0 == 0 else 0.0)
    lo_y = y_edges[hy0] - (slack if hy0 == 0 else 0.0)
    hi_x = x_edges[hx1] + (slack if hx1 == nx else 0.0)
    hi_y = y_edges[hy1] + (slack if hy1 == ny else 0.0)
    x, y, z = read(((lo_x, lo_y), (hi_x, hi_y)))
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    keep = (x >= lo_x) & (y >= lo_y)
    keep &= (x <= hi_x) if hx1 == nx else (x < hi_x)
    keep &= (y <= hi_y) if hy1 == ny else (y < hi_y)
    return x[keep], y[keep], z[keep]


def tiled_surface(read, mins, maxs, *, cell=1.0, slope=0.15, window=18.0,
                  low_cut=None, tile_size=None, halo=None, progress=None,
                  stats=None):
    """Build one project-wide ground surface, tile by tile.

    ``read(bounds)`` returns (x, y, z) for a box -- a COPC query, a
    streaming cull, whatever the caller has. It is called once per
    tile with the HALO box; ``window_points`` cuts the answer to the
    tile's half-open window of the project lattice, and only the core
    cells of the result are kept, so the seams carry the same values a
    whole-cloud run would have produced.

    ``stats``, when a dict, is filled with what actually happened: the
    resolved ``halo`` and ``tile_size``, and the points each tile held
    (``tile_points``, ``points_read``, ``max_tile_points``) -- the
    number that sets peak memory.

    Returns a GroundSurface on the project lattice. Tiles with no
    points are left NaN in the DEM and filled at the end, so an empty
    corner does not abort the run.
    """
    x_edges, y_edges = global_edges(mins, maxs, cell)
    halo, tile_size = resolve_plan(cell, window, halo, tile_size)
    tiles = plan_tiles(x_edges, y_edges, cell, halo, tile_size)

    shape = (x_edges.size - 1, y_edges.size - 1)
    dem = np.full(shape, np.nan)
    dem_slope = np.full(shape, np.nan)
    object_cells = np.zeros(shape, dtype=bool)
    low_cells = np.zeros(shape, dtype=bool)
    filled = 0
    held = []
    for n, tile in enumerate(tiles, start=1):
        if progress is not None:
            progress(n, len(tiles), tile)
        # the tile's own lattice, in phase with the project's
        hx0, hy0, hx1, hy1 = _cells(tile.halo, x_edges, y_edges)
        x, y, z = window_points(read, x_edges, y_edges, hx0, hy0, hx1, hy1)
        held.append(int(x.size))
        if x.size == 0:
            continue
        local = ground_mod.ground_surface(
            x, y, z, x_edges[hx0:hx1 + 1], y_edges[hy0:hy1 + 1],
            cell=cell, slope=slope, window=window, low_cut=low_cut)
        cx0, cy0, cx1, cy1 = _cells(tile.core, x_edges, y_edges)
        sx, sy = cx0 - hx0, cy0 - hy0
        ex, ey = sx + (cx1 - cx0), sy + (cy1 - cy0)
        dem[cx0:cx1, cy0:cy1] = local.dem[sx:ex, sy:ey]
        dem_slope[cx0:cx1, cy0:cy1] = local.dem_slope[sx:ex, sy:ey]
        object_cells[cx0:cx1, cy0:cy1] = local.object_cells[sx:ex, sy:ey]
        low_cells[cx0:cx1, cy0:cy1] = local.low_cells[sx:ex, sy:ey]
        filled += 1
    if stats is not None:
        stats.update(halo=halo, tile_size=tile_size, tiles=len(tiles),
                     tile_points=held, points_read=int(sum(held)),
                     max_tile_points=int(max(held, default=0)))
    if filled == 0:
        raise ValueError("no tile held any points")
    if not np.isfinite(dem).any():
        raise ValueError("no ground cells survived in any tile")
    dem = gridding.inpaint_nearest(dem)
    dem_slope = np.where(np.isfinite(dem_slope), dem_slope, 0.0)
    return ground_mod.GroundSurface(
        dem=dem, dem_slope=dem_slope, object_cells=object_cells,
        low_cells=low_cells, x_edges=x_edges, y_edges=y_edges)
