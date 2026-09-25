"""Surveyed points joining a lidar surface, and winning where they land.

Two things the lidar cannot do arrive as the same kind of file. Under
thick canopy no pulse reaches the ground, so the surveyors go and shoot
it; and where an operator judges the surface in stereo, they measure a
point themselves. Both are a handful of coordinates with a description,
both are better than anything the lidar has at that spot, and until now
neither had any route into a surface at all.

The question that decides the design is what a shot should DO. Joining
it to the ground points as one more return is the tempting answer and
the wrong one: a cell holding two hundred lidar returns and one
surveyed shot would average the shot away to half a percent, so the
surveyor's work would change the surface by nothing and nobody would
see that it had not. A shot is not another opinion about the cell. It
is a measurement of the cell, made by someone standing on it.

So a supplementary point WINS its own cell. Where shots land, the cell
is theirs; everywhere else the lidar is untouched. That is what a
surveyor means by "I shot it there", and it is the behaviour that makes
the trip worth making.

What this deliberately does not do is spread a shot's influence beyond
its cell. Blending outward needs a decision about how far and with what
weight, and a wrong answer there is a smooth, plausible surface that is
wrong over an area rather than at a point. The cell is the honest unit:
it is the resolution the surface is stated at.

Every supplement is counted and reported -- how many points were given,
how many landed inside the surface, how many cells changed and by how
much -- because a file quietly landing outside the site and changing
nothing is otherwise indistinguishable from one that worked.
"""

import numpy as np

from pyargus.core import gridding


def apply_points(grid, x_edges, y_edges, x, y, z, *, log=print):
    """Let surveyed points own the cells they fall in.

    ``grid`` is a DTM as :func:`pyargus.surfaces.dtm.dtm_grid` returns
    it. Returns ``(grid, report)`` with a NEW grid; the original is not
    modified, so a caller can compare them.
    """
    grid = np.array(grid, dtype=float, copy=True)
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    z = np.asarray(z, dtype=float).ravel()
    if not (x.size == y.size == z.size):
        raise ValueError(f"{x.size} eastings, {y.size} northings and "
                         f"{z.size} elevations")
    if x.size == 0:
        raise ValueError("no supplementary points were given")
    if not np.isfinite(z).all():
        raise ValueError("a supplementary point has no elevation; a shot "
                         "without a height cannot supplement a surface")

    col = np.searchsorted(x_edges, x, side="right") - 1
    row = np.searchsorted(y_edges, y, side="right") - 1
    inside = ((col >= 0) & (col < grid.shape[1])
              & (row >= 0) & (row < grid.shape[0])
              & np.isfinite(x) & np.isfinite(y))
    if not inside.any():
        raise ValueError(
            f"none of the {x.size} supplementary points fall inside the "
            f"surface ({x_edges[0]:,.1f}..{x_edges[-1]:,.1f} by "
            f"{y_edges[0]:,.1f}..{y_edges[-1]:,.1f}). Check the column "
            f"order and the coordinate system before assuming the file is "
            f"wrong.")

    flat = row[inside] * grid.shape[1] + col[inside]
    order = np.argsort(flat, kind="stable")
    flat, values = flat[order], z[inside][order]
    edges = np.flatnonzero(np.diff(flat)) + 1
    starts = np.r_[0, edges]
    stops = np.r_[edges, flat.size]

    changed, deltas, created = 0, [], 0
    flat_grid = grid.ravel()
    for lo, hi in zip(starts, stops):
        cell = int(flat[lo])
        was = flat_grid[cell]
        now = float(np.mean(values[lo:hi]))     # several shots in one cell
        if np.isfinite(was):
            deltas.append(now - was)
        else:
            created += 1
        flat_grid[cell] = now
        changed += 1

    report = {"given": int(x.size), "inside": int(inside.sum()),
              "outside": int((~inside).sum()),
              "cells_changed": changed, "cells_created": created}
    if deltas:
        deltas = np.asarray(deltas)
        report.update(median_shift=round(float(np.median(deltas)), 4),
                      largest_shift=round(float(np.abs(deltas).max()), 4))
    log(f"supplement: {report['inside']:,} of {report['given']:,} points "
        f"landed inside, and own {changed:,} cells "
        f"({created:,} of them had no lidar ground at all)")
    if report["outside"]:
        log(f"            {report['outside']:,} fell outside the surface "
            f"and were not used")
    if deltas is not None and len(deltas):
        log(f"            where the lidar already had a value, the shots "
            f"move it a median {report['median_shift']:+.3f}, worst "
            f"{report['largest_shift']:.3f}")
    return grid, report


def read_points(paths, order, *, log=print):
    """Surveyed points from control-format CSVs.

    Deliberately the control reader, not a second parser. Field shots
    and stereo measurements arrive in the same shape control does, and
    that reader already refuses to guess the column order -- which is
    the failure that transposes a site while leaving it plausible.
    """
    from pyargus.formats import control as control_mod

    ids, east, north, elev = control_mod.read_control_csvs(list(paths), order)
    log(f"points:  {len(ids):,} supplementary points read as {order}")
    return (np.asarray(east, dtype=float), np.asarray(north, dtype=float),
            np.asarray(elev, dtype=float))
