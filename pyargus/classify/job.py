"""Ground-classify a cloud, whole or tiled, under ONE labeling policy.

Two drivers, one answer:

* ``classify_ground_whole`` holds the cloud, builds the SMRF surface
  and labels every point -- the plain ``classify-ground`` command and
  the desktop Classify stage;
* ``classify_ground_tiled`` builds the same surface tile by tile
  (classify.tiles) and labels the points in a streaming pass, for a
  cloud too large to hold.

They agree because everything that decides a label is SHARED rather
than repeated: the lattice (``project_extent`` -- the header's extent,
or the points' own with ``rescan``), which points may build the
surface and be called ground (``candidates``), and the rule that turns
a surface into class codes (``labels``). The first version of the
tiled driver re-implemented the rule and got it different -- every
non-last return near the DEM became ground, where the plain command
never lets one -- and its tests could not see it, because their clouds
had one return per pulse.

Passes, for the tiled driver on a file with no index: one per tile to
build the surface, plus one to write, plus one to rescan if asked. A
COPC index answers each tile's box from its octree, which removes the
passes but not the overlap between halo boxes -- and a small box still
decompresses the coarse octree levels, which span the whole file. The
driver says all of that before it starts, and afterwards reports the
most points one tile actually held: the number that sets peak memory.
"""

from pathlib import Path

import numpy as np

from pyargus.classify import ground as ground_mod
from pyargus.classify import tiles as tiles_mod
from pyargus.formats import las as las_mod

GROUND_CLASS = 2
UNCLASSIFIED = 1
RETURN_FIELDS = ("return_number", "number_of_returns")


def candidates(points, any_return=False):
    """Which points may build the surface -- and so be called ground.

    Last returns by default: they are the ones that can see the ground,
    and a non-last return is by definition not the lowest surface its
    pulse reached. ``any_return`` admits everything. This is the one
    place the policy lives; both drivers and the desktop stage call it.
    """
    if any_return:
        return np.ones(np.asarray(points["x"]).size, dtype=bool)
    return (np.asarray(points["return_number"])
            == np.asarray(points["number_of_returns"]))


def labels(surface, points, eligible, *, threshold, scalar):
    """Class codes: ground where a candidate lies within the allowance
    of the surface, unclassified everywhere else."""
    near = ground_mod.classify_against(
        surface, points["x"], points["y"], points["z"],
        threshold=threshold, scalar=scalar)
    return np.where(near & eligible, GROUND_CLASS,
                    UNCLASSIFIED).astype(np.uint8)


def _stale_header(count, scope):
    return ValueError(
        f"{count:,} point(s){scope} lie outside the extent the LAS header "
        f"reports -- the header is stale (a crop, merge or append that "
        f"did not update it), and a surface built on it would silently "
        f"judge those points against its edge. Pass --rescan to take the "
        f"extent from the points, at the cost of one extra pass.")


def _refuse_same(path, out):
    if Path(out).resolve() == Path(path).resolve():
        raise ValueError("refusing to overwrite the input cloud; the "
                         "classified cloud must be a new file")


def project_extent(path, *, rescan=False, chunk_size=las_mod.DEFAULT_CHUNK):
    """(mins, maxs) in x and y: the header's, or with ``rescan`` the
    points' own, from one streaming pass."""
    if rescan:
        from pyargus.qa import density
        return density.scan_extent(las_mod.iter_points(
            path, fields=("x", "y"), chunk_size=chunk_size))
    info = las_mod.cloud_info(path)
    return (np.asarray(info["mins"][:2], dtype=float),
            np.asarray(info["maxs"][:2], dtype=float))


def box_reader(path, *, fields=("x", "y", "z"), keep=None,
               chunk_size=las_mod.DEFAULT_CHUNK, lattice=None):
    """A ``read(bounds) -> (x, y, z)`` over one cloud.

    Uses COPC's octree when the file has one and a streaming cull when
    it does not. ``keep(points)`` optionally returns a boolean mask --
    ``candidates``, say. Returns (read, indexed) so the caller can tell
    an operator which of the two it got.

    ``lattice`` = (x_edges, y_edges): without an index the first read
    passes over every point anyway, so it also counts the points that
    fall off the lattice and refuses at once, rather than after the
    whole surface has been built.
    """
    indexed = las_mod.cloud_info(path)["is_copc"]
    checked = [lattice is None or indexed]

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
        xs, ys, zs = [], [], []
        stray = 0
        for chunk in las_mod.iter_points(path, fields=fields,
                                         chunk_size=chunk_size):
            if not checked[0]:
                stray += tiles_mod.outside(chunk["x"], chunk["y"], *lattice)
            x, y, z = select(chunk, bounds)
            if x.size:
                xs.append(x)
                ys.append(y)
                zs.append(z)
        if not checked[0]:
            if stray:
                raise _stale_header(stray, "")
            checked[0] = True
        # one axis at a time, dropping each list as it is joined: the
        # peak is 4/3 of the tile's points rather than twice them
        out = []
        for parts in (xs, ys, zs):
            out.append(np.concatenate(parts) if parts else np.empty(0))
            parts.clear()
        return tuple(out)

    return read, indexed


def classify_ground_whole(path, out, *, cell=1.0, slope=0.15, window=18.0,
                          threshold=0.5, scalar=1.25, low_cut=None,
                          any_return=False, rescan=False, log=print,
                          should_stop=None, keep_points=False):
    """Ground-classify ``path`` into ``out``, holding the whole cloud.

    Returns a dict of what happened; with ``keep_points`` it also
    carries the x, y, z and classification arrays, for a caller that
    previews them. ``should_stop()`` is asked once, after the work and
    before anything is written; if it says stop, nothing is, and the
    dict says ``cancelled``.
    """
    import laspy

    path, out = Path(path), Path(out)
    _refuse_same(path, out)
    if window < cell:
        raise ValueError("window must be at least one cell")
    las = laspy.read(str(path))
    x, y, z = (np.asarray(las.x), np.asarray(las.y), np.asarray(las.z))
    if x.size == 0:
        raise ValueError(f"{path} holds no points")
    if rescan:
        mins = np.array([x.min(), y.min()])
        maxs = np.array([x.max(), y.max()])
    else:
        mins = np.asarray(las.header.mins[:2], dtype=float)
        maxs = np.asarray(las.header.maxs[:2], dtype=float)
    x_edges, y_edges = tiles_mod.global_edges(mins, maxs, cell)
    stray = tiles_mod.outside(x, y, x_edges, y_edges)
    if stray:
        raise _stale_header(stray, "")

    points = {"x": x, "y": y, "z": z}
    if not any_return:
        points.update(return_number=np.asarray(las.return_number),
                      number_of_returns=np.asarray(las.number_of_returns))
    eligible = candidates(points, any_return)
    if not eligible.any():
        raise ValueError("no candidate returns to build a surface from")
    surface = ground_mod.ground_surface(
        x[eligible], y[eligible], z[eligible], x_edges, y_edges,
        cell=cell, slope=slope, window=window, low_cut=low_cut)
    classification = labels(surface, points, eligible,
                            threshold=threshold, scalar=scalar)
    if should_stop is not None and should_stop():
        return {"cancelled": True}
    las.classification = classification
    las.write(str(out))

    n_ground = int(np.count_nonzero(classification == GROUND_CLASS))
    which = ("every return a candidate" if any_return
             else f"{int(eligible.sum()):,} last-return candidates")
    log(f"points:  {x.size:,} ({which})")
    log(f"ground:  {n_ground:,} ({100.0 * n_ground / x.size:.1f}% of cloud)")
    log(f"cells:   {int(surface.object_cells.sum()):,} object, "
        f"{int(surface.low_cells.sum()):,} low-outlier")
    log(f"wrote:   {out}")
    result = {"ground": n_ground, "total": int(x.size),
              "ground_fraction": n_ground / x.size,
              "candidates": int(eligible.sum()),
              "cells": int(surface.dem.size)}
    if keep_points:
        result["points"] = (x, y, z, classification)
    return result


def classify_ground_tiled(path, out, *, cell=1.0, slope=0.15, window=18.0,
                          threshold=0.5, scalar=1.25, low_cut=None,
                          tile_size=None, halo=None, any_return=False,
                          rescan=False, log=print, progress=None,
                          chunk_size=las_mod.DEFAULT_CHUNK):
    """Ground-classify ``path`` into ``out`` without holding the cloud.

    Labels exactly as ``classify_ground_whole`` does -- same lattice,
    same candidates, same rule -- wherever the halo is wide enough, and
    the default halo is SMRF's own reach. Returns a dict of what
    happened, including what the plan cost (``area_read``,
    ``largest_box``, ``seamed``) and what the tiles actually held
    (``max_tile_points``, ``points_read``).
    """
    path, out = Path(path), Path(out)
    _refuse_same(path, out)
    if window < cell:
        raise ValueError("window must be at least one cell")
    halo, tile_size = tiles_mod.resolve_plan(cell, window, halo, tile_size)
    mins, maxs = project_extent(path, rescan=rescan, chunk_size=chunk_size)
    x_edges, y_edges = tiles_mod.global_edges(mins, maxs, cell)
    plan = tiles_mod.plan_tiles(x_edges, y_edges, cell, halo, tile_size)
    cost = tiles_mod.plan_summary(plan, x_edges, y_edges)

    fields = ("x", "y", "z") if any_return else ("x", "y", "z") + RETURN_FIELDS
    read, indexed = box_reader(
        path, fields=fields,
        keep=None if any_return else candidates,
        chunk_size=chunk_size, lattice=(x_edges, y_edges))

    log(f"tiles:   {len(plan)} over {maxs[0] - mins[0]:,.0f} x "
        f"{maxs[1] - mins[1]:,.0f} map units: cores {tile_size:,.0f}, "
        f"halo {halo:,.0f}")
    if len(plan) == 1:
        log("         one tile, whose box is the whole project: this holds "
            "the whole cloud, and tiling saves nothing at this size")
    else:
        log(f"         the halo boxes overlap: between them the tiles cover "
            f"the project {cost['area_read']:.1f}x, and the largest box "
            f"is {100.0 * cost['largest_box']:.0f}% of it")
    passes = len(plan) + 1 + (1 if rescan else 0)
    if indexed:
        log("reads:   COPC index: each tile decompresses only the octree "
            "nodes its box touches -- but the coarse levels span the whole "
            "file, so a small box still costs a good share of a full read, "
            "and the overlap above is paid either way")
    else:
        log(f"reads:   no COPC index, so every tile is a full pass over "
            f"the file: {len(plan)} to build the surface, 1 to write"
            f"{', 1 to rescan' if rescan else ''} -- {passes} passes")

    held = {}
    surface = tiles_mod.tiled_surface(
        read, mins, maxs, cell=cell, slope=slope, window=window,
        low_cut=low_cut, tile_size=tile_size, halo=halo,
        progress=progress, stats=held)
    log(f"surface: {surface.dem.shape[0]} x {surface.dem.shape[1]} cells, "
        f"{int(surface.object_cells.sum()):,} object cells")
    log(f"held:    at most {held['max_tile_points']:,} points in one tile; "
        f"{held['points_read']:,} read across all tiles")

    counts = {"ground": 0, "total": 0}

    def label(chunk, start):
        # the backstop for an indexed file, whose reads never saw the
        # points outside the boxes they asked for
        stray = tiles_mod.outside(chunk["x"], chunk["y"], x_edges, y_edges)
        if stray:
            raise _stale_header(stray, " in one chunk alone")
        codes = labels(surface, chunk, candidates(chunk, any_return),
                       threshold=threshold, scalar=scalar)
        counts["ground"] += int(np.count_nonzero(codes == GROUND_CLASS))
        counts["total"] += codes.size
        return {"classification": codes}

    las_mod.stream_update(path, out, label, fields=fields,
                          chunk_size=chunk_size)
    pct = 100.0 * counts["ground"] / max(counts["total"], 1)
    log(f"ground:  {counts['ground']:,} of {counts['total']:,} points "
        f"({pct:.1f}%)")
    log(f"wrote:   {out}")
    return {"tiles": len(plan), "indexed": indexed, "halo": halo,
            "tile_size": tile_size, "passes": None if indexed else passes,
            "ground": counts["ground"], "total": counts["total"],
            "ground_fraction": pct / 100.0, "cells": int(surface.dem.size),
            "area_read": cost["area_read"], "largest_box": cost["largest_box"],
            "seamed": cost["seamed"], "max_tile_points": held["max_tile_points"],
            "points_read": held["points_read"]}
