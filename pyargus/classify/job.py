"""Ground-classify a cloud too large to hold, start to finish.

Three passes, each bounded:

1. tile the project and build ONE ground surface (classify.tiles),
   reading each tile's halo box;
2. stream the points once, judging each against that surface;
3. stream again to write the classification out.

How a tile is read matters more than it looks. A COPC file answers a
bounding box from its octree, so tiling costs roughly one read of the
project. A plain LAS or LAZ has no index, so every tile means another
pass over the whole file -- correct, but N times the I/O. The reader
says which it is doing, because "this will take twenty passes" is
something an operator should be told rather than discover.
"""

from pathlib import Path

import numpy as np

from pyargus.classify import ground as ground_mod
from pyargus.classify import tiles as tiles_mod
from pyargus.formats import las as las_mod

GROUND_CLASS = 2
UNCLASSIFIED = 1


def box_reader(path, *, fields=("x", "y", "z"), keep=None,
               chunk_size=las_mod.DEFAULT_CHUNK):
    """A ``read(bounds) -> (x, y, z)`` over one cloud.

    Uses COPC's octree when the file has one and a streaming cull when
    it does not. ``keep(points)`` optionally returns a boolean mask --
    last returns only, say. Returns (read, indexed) so the caller can
    tell an operator which of the two it got.
    """
    indexed = las_mod.cloud_info(path)["is_copc"]

    def select(points, bounds):
        (x0, y0), (x1, y1) = bounds
        mask = ((points["x"] >= x0) & (points["x"] <= x1)
                & (points["y"] >= y0) & (points["y"] <= y1))
        if keep is not None:
            mask &= keep(points)
        return points["x"][mask], points["y"][mask], points["z"][mask]

    def read(bounds):
        if indexed:
            # the octree already limits this to the box; select() still
            # runs because a COPC query is node-granular on the way in
            return select(las_mod.copc_query(path, fields=fields,
                                             bounds=bounds), bounds)
        parts = [select(chunk, bounds) for chunk in
                 las_mod.iter_points(path, fields=fields,
                                     chunk_size=chunk_size)]
        parts = [p for p in parts if p[0].size]
        if not parts:
            return (np.empty(0), np.empty(0), np.empty(0))
        return tuple(np.concatenate([p[i] for p in parts])
                     for i in range(3))

    return read, indexed


def last_return_mask(points):
    """Returns that can see the ground. The surface is built from
    these; every point is still CLASSIFIED against the result."""
    return points["return_number"] == points["number_of_returns"]


def classify_ground_tiled(path, out, *, cell=1.0, slope=0.15, window=18.0,
                          threshold=0.5, scalar=1.25, low_cut=None,
                          tile_size=None, halo=None, last_returns=True,
                          log=print, progress=None):
    """Ground-classify ``path`` into ``out`` without holding the cloud.

    Returns a dict of what happened. ``last_returns`` restricts the
    SURFACE to returns that can see the ground, exactly as the
    whole-cloud command does; every point is still classified against
    the finished surface.
    """
    path, out = Path(path), Path(out)
    if out.resolve() == path.resolve():
        raise ValueError("refusing to overwrite the input cloud; the "
                         "classified cloud must be a new file")
    info = las_mod.cloud_info(path)
    mins, maxs = info["mins"][:2], info["maxs"][:2]
    if halo is None:
        halo = tiles_mod.required_halo(cell, window)

    surface_fields = ("x", "y", "z")
    keep = None
    if last_returns:
        surface_fields += ("return_number", "number_of_returns")
        keep = last_return_mask
    read, indexed = box_reader(path, fields=surface_fields, keep=keep)

    plan = tiles_mod.plan_tiles(
        *tiles_mod.global_edges(mins, maxs, cell), cell, halo,
        tile_size if tile_size is not None else max(6.0 * halo, 50.0 * cell))
    log(f"tiles:   {len(plan)} over {maxs[0] - mins[0]:,.0f} x "
        f"{maxs[1] - mins[1]:,.0f} map units, halo {halo:,.0f}")
    if indexed:
        log("reads:   COPC octree, so a tile costs only its own points")
    else:
        log(f"reads:   no COPC index, so each tile is another pass over "
            f"the file -- {len(plan)} passes. `pyargus copc` first "
            f"turns that into one.")

    surface = tiles_mod.tiled_surface(
        read, mins, maxs, cell=cell, slope=slope, window=window,
        low_cut=low_cut, tile_size=tile_size, halo=halo,
        progress=progress)
    log(f"surface: {surface.dem.shape[0]} x {surface.dem.shape[1]} cells, "
        f"{int(surface.object_cells.sum()):,} object cells")

    counts = {"ground": 0, "total": 0}

    def label(chunk, start):
        mask = ground_mod.classify_against(
            surface, chunk["x"], chunk["y"], chunk["z"],
            threshold=threshold, scalar=scalar)
        counts["ground"] += int(mask.sum())
        counts["total"] += mask.size
        return {"classification": np.where(mask, GROUND_CLASS,
                                           UNCLASSIFIED).astype(np.uint8)}

    las_mod.stream_update(path, out, label, fields=("x", "y", "z"))
    pct = 100.0 * counts["ground"] / max(counts["total"], 1)
    log(f"ground:  {counts['ground']:,} of {counts['total']:,} points "
        f"({pct:.1f}%)")
    log(f"wrote:   {out}")
    return {"tiles": len(plan), "indexed": indexed, "halo": halo,
            "ground": counts["ground"], "total": counts["total"],
            "ground_fraction": pct / 100.0,
            "cells": int(surface.dem.size)}
