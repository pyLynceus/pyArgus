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
from pyargus.classify.recording import recorded_classification

import numpy as np

from pyargus.classify import ground as ground_mod
from pyargus.classify import noise as noise_mod
from pyargus.classify import tiles as tiles_mod
from pyargus.formats import las as las_mod

GROUND_CLASS = 2
UNCLASSIFIED = 1
RETURN_FIELDS = ("return_number", "number_of_returns")
NOISE_CLASSES = (7, 18)
"""ASPRS low noise and high noise. A point carrying one of these is a
statement about that point which SMRF has no business overturning:
it never enters the minimum surface and it keeps its class.

Why this matters: SMRF builds a per-cell MINIMUM and an opening removes
bumps, never pits, so a single gross low outlier becomes the DEM's own
value in its cell and the slope term around it inflates the allowance
for every neighbour. Measured on a real two-line delivery classified
straight from the vendor export: over a hundred such outliers, nearly
all of them low, more than half of them labeled ground, and at more
than a dozen pits the result put ground tens of feet above the
vendor's own class-2 surface -- canopy and roofs pulled into class 2.
The measurement and its script are kept with that job's private
records, outside this repository.

There are two ways a point becomes noise, and they were built
independently before being reconciled here. ``pyargus noise-cut`` flags
it once, in a separate recorded step that writes a new cloud and
refuses a window that would catch the site. Screening by elevation
(``noise_min``/``noise_max`` on the classifiers, the desktop Classify
stage and batch runs) flags it on the fly during classification. Both
land on these same two codes, and ``noise_codes`` is the one place
that decides which points are noise, so the surface, the labels and
every count agree whichever route a point took. Both routes also
refuse the same way (``noise_max_fraction``, ``screen_guard``): a
window the header says would catch every point, before a point is
read, and a window that catches more than a declared fraction of the
cloud, before anything is classified.
"""
LOW_NOISE, HIGH_NOISE = NOISE_CLASSES
NOISE_MAX_FRACTION = noise_mod.DEFAULT_MAX_FRACTION
"""Default share of the cloud that screening may flag: noise-cut's."""


def noise_mask(points):
    """Points already flagged as noise, or None when the caller did not
    read the classification field at all."""
    if "classification" not in points:
        return None
    codes = np.asarray(points["classification"])
    mask = np.zeros(codes.shape, dtype=bool)
    for code in NOISE_CLASSES:
        mask |= codes == code
    return mask


def validate_noise_bounds(noise_min=None, noise_max=None,
                          max_fraction=NOISE_MAX_FRACTION):
    """Refuse a screening window that cannot be right, before any work."""
    for value in (noise_min, noise_max):
        if value is not None and not np.isfinite(value):
            raise ValueError("Noise elevation limits must be finite")
    if (noise_min is not None and noise_max is not None
            and noise_min >= noise_max):
        raise ValueError("Minimum noise-screening elevation must be below "
                         "maximum")
    if not 0.0 < max_fraction <= 1.0:      # NaN fails this too
        raise ValueError(f"Noise max fraction must be in (0, 1], got "
                         f"{max_fraction}")


def _screening(noise_min, noise_max):
    return noise_min is not None or noise_max is not None


def _refuse_screen_from_header(path, noise_min, noise_max):
    """Before a point is read: a screen outside the header's z range
    would flag the whole cloud. A cloud holding no points is left for
    the drivers' own refusal, which says so plainly."""
    info = las_mod.cloud_info(path)
    if info["point_count"]:
        noise_mod.refuse_outside_header(
            noise_min, noise_max, info["mins"][2], info["maxs"][2],
            low="--noise-min", high="--noise-max")
    return info


def screen_guard(screened, seen, expected, max_fraction):
    """Refuse when screening has flagged more than ``max_fraction`` of
    the cloud: that is not gross noise, it is the site. The same budget
    as noise-cut -- ``int(max_fraction * points)`` may be flagged -- and
    the same reason; points flagged before the run do not count, being
    no part of this run's decision."""
    if screened > int(max_fraction * expected):
        raise ValueError(noise_mod.too_many(
            screened, seen, expected, max_fraction,
            option="--noise-max-fraction (Noise max fraction in the "
                   "desktop Classify stage)",
            nothing="Nothing was classified or written"))


def noise_codes(points, noise_min=None, noise_max=None):
    """Each point's class once noise is settled.

    A point already flagged keeps its flag, however it was flagged.
    Screening then flags what falls outside ``[noise_min, noise_max]``:
    low noise below, high noise above. This is the ONE place that says
    which points are noise; ``candidates``, ``labels`` and every count
    in both drivers read it, so they cannot disagree about it.
    """
    if "classification" in points:
        codes = np.asarray(points["classification"]).astype(np.uint8)
    else:
        codes = np.zeros(np.asarray(points["x"]).size, dtype=np.uint8)
    codes = codes.copy()
    existing = np.isin(codes, NOISE_CLASSES)
    z = np.asarray(points["z"]) if (noise_min is not None
                                    or noise_max is not None) else None
    if noise_min is not None:
        codes[(z < noise_min) & ~existing] = LOW_NOISE
    if noise_max is not None:
        codes[(z > noise_max) & ~existing] = HIGH_NOISE
    return codes


def noise_counts(points, noise_min=None, noise_max=None):
    """(already flagged, screened now) -- the two routes, told apart.

    Reported separately because they mean different things in a log: a
    point already flagged was a decision someone recorded earlier, and
    a point screened now is this run's decision. Merging the two lines
    that counted them, one from each side of a reconcile, produced a
    count that included every existing flag twice.
    """
    before = noise_mask(points)
    already = 0 if before is None else int(np.count_nonzero(before))
    total = int(np.count_nonzero(
        np.isin(noise_codes(points, noise_min, noise_max), NOISE_CLASSES)))
    return already, total - already


def _log_noise(log, already, screened, noise_min, noise_max):
    """One line per route. Flags carried in are reported when there are
    any; screening is reported whenever a limit was set, even when it
    caught nothing, because "screened 0" is itself the answer to "did
    the window run". Limits print as applied: ``:g`` keeps six digits,
    and 10234.56 logged as 10234.6 is a window the run did not use."""
    classes = "/".join(map(str, NOISE_CLASSES))
    if already:
        log(f"noise:   {already:,} points already flagged (classes "
            f"{classes}) kept out of the surface and carried through")
    if noise_min is not None or noise_max is not None:
        low = "-inf" if noise_min is None else f"{noise_min:.15g}"
        high = "+inf" if noise_max is None else f"{noise_max:.15g}"
        log(f"noise:   {screened:,} points screened outside {low} to {high} "
            f"and flagged {LOW_NOISE} below / {HIGH_NOISE} above")


def candidates(points, any_return=False, noise_min=None, noise_max=None):
    """Which points may build the surface -- and so be called ground.

    Last returns by default: they are the ones that can see the ground,
    and a non-last return is by definition not the lowest surface its
    pulse reached. ``any_return`` admits everything. Noise is never a
    candidate, whatever its return number and whichever route flagged
    it. This is the one place the policy lives; both drivers and the
    desktop stage call it.
    """
    eligible = ~np.isin(noise_codes(points, noise_min, noise_max),
                        NOISE_CLASSES)
    if not any_return:
        eligible &= (np.asarray(points["return_number"])
                     == np.asarray(points["number_of_returns"]))
    return eligible


def labels(surface, points, eligible, *, threshold, scalar, noise_min=None,
           noise_max=None):
    """Class codes: ground where a candidate lies within the allowance
    of the surface, unclassified everywhere else -- except that noise
    keeps its flag.

    Noise is excluded HERE as well as in ``candidates``, rather than
    trusting the caller's ``eligible``: a caller that built ``eligible``
    some other way must still not be able to label a flagged point
    ground.
    """
    near = ground_mod.classify_against(
        surface, points["x"], points["y"], points["z"],
        threshold=threshold, scalar=scalar)
    codes = noise_codes(points, noise_min, noise_max)
    noise = np.isin(codes, NOISE_CLASSES)
    result = np.where(near & eligible & ~noise, GROUND_CLASS,
                      UNCLASSIFIED).astype(np.uint8)
    result[noise] = codes[noise]
    return result


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


@recorded_classification
def classify_ground_whole(path, out, *, cell=1.0, slope=0.15, window=18.0,
                          threshold=0.5, scalar=1.25, low_cut=None,
                          any_return=False, rescan=False, noise_min=None,
                          noise_max=None,
                          noise_max_fraction=NOISE_MAX_FRACTION, log=print,
                          should_stop=None, keep_points=False):
    """Ground-classify ``path`` into ``out``, holding the whole cloud.

    Returns a dict of what happened; with ``keep_points`` it also
    carries the x, y, z and classification arrays, for a caller that
    previews them. ``should_stop()`` is asked once, after the work and
    before anything is written; if it says stop, nothing is, and the
    dict says ``cancelled``. A noise screen that would flag more than
    ``noise_max_fraction`` of the cloud refuses (``screen_guard``).
    """
    import laspy

    path, out = Path(path), Path(out)
    _refuse_same(path, out)
    validate_noise_bounds(noise_min, noise_max, noise_max_fraction)
    if window < cell:
        raise ValueError("window must be at least one cell")
    screening = _screening(noise_min, noise_max)
    if screening:
        info = _refuse_screen_from_header(path, noise_min, noise_max)
    las = laspy.read(str(path))
    x, y, z = (np.asarray(las.x), np.asarray(las.y), np.asarray(las.z))
    if x.size == 0:
        raise ValueError(f"{path} holds no points")
    if screening and x.size != info["point_count"]:
        # as the tiled driver: the screen's budget is a share of the
        # cloud, and a cloud that is not what its header says has no
        # share to take
        raise ValueError(noise_mod.miscounted(path, x.size,
                                              info["point_count"]))
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

    points = {"x": x, "y": y, "z": z,
              "classification": np.asarray(las.classification)}
    if not any_return:
        points.update(return_number=np.asarray(las.return_number),
                      number_of_returns=np.asarray(las.number_of_returns))
    # the budget before the candidates: a screen that caught the site
    # would otherwise surface as "no candidate returns", which names
    # the symptom and not the cause
    already, screened = noise_counts(points, noise_min, noise_max)
    screen_guard(screened, x.size, x.size, noise_max_fraction)
    eligible = candidates(points, any_return, noise_min, noise_max)
    if not eligible.any():
        raise ValueError("no candidate returns to build a surface from")
    _log_noise(log, already, screened, noise_min, noise_max)
    surface = ground_mod.ground_surface(
        x[eligible], y[eligible], z[eligible], x_edges, y_edges,
        cell=cell, slope=slope, window=window, low_cut=low_cut)
    classification = labels(surface, points, eligible,
                            threshold=threshold, scalar=scalar,
                            noise_min=noise_min, noise_max=noise_max)
    if should_stop is not None and should_stop():
        return {"cancelled": True}
    las.classification = classification
    # a COPC input is read like any cloud but written as a plain one:
    # laspy cannot write its octree records, and they would be false here
    las_mod.drop_copc_records(las.header)
    las.write(str(out))

    n_ground = int(np.count_nonzero(classification == GROUND_CLASS))
    which = ("all non-noise returns eligible" if any_return
             else f"{int(eligible.sum()):,} last-return candidates")
    log(f"points:  {x.size:,} ({which})")
    log(f"ground:  {n_ground:,} ({100.0 * n_ground / x.size:.1f}% of cloud)")
    log(f"cells:   {int(surface.object_cells.sum()):,} object, "
        f"{int(surface.low_cells.sum()):,} low-outlier")
    log(f"wrote:   {out}")
    result = {"ground": n_ground, "total": int(x.size),
              "ground_fraction": n_ground / x.size,
              "candidates": int(eligible.sum()),
              "noise": int(np.count_nonzero(
                  np.isin(classification, NOISE_CLASSES))),
              "noise_already": already, "noise_screened": screened,
              "cells": int(surface.dem.size)}
    if keep_points:
        result["points"] = (x, y, z, classification)
    return result


@recorded_classification
def classify_ground_tiled(path, out, *, cell=1.0, slope=0.15, window=18.0,
                          threshold=0.5, scalar=1.25, low_cut=None,
                          tile_size=None, halo=None, any_return=False,
                          rescan=False, noise_min=None, noise_max=None,
                          noise_max_fraction=NOISE_MAX_FRACTION,
                          log=print, progress=None,
                          chunk_size=las_mod.DEFAULT_CHUNK):
    """Ground-classify ``path`` into ``out`` without holding the cloud.

    Labels exactly as ``classify_ground_whole`` does -- same lattice,
    same candidates, same rule -- wherever the halo is wide enough, and
    the default halo is SMRF's own reach. Returns a dict of what
    happened, including what the plan cost (``area_read``,
    ``largest_box``, ``seamed``) and what the tiles actually held
    (``max_tile_points``, ``points_read``).

    A noise screen costs one extra streaming pass, taken FIRST: it
    counts what the window would flag and refuses on the running count
    (``screen_guard``) before any tile's surface is built, because on a
    cloud too big to hold the refusal is the cheap thing.
    """
    path, out = Path(path), Path(out)
    _refuse_same(path, out)
    validate_noise_bounds(noise_min, noise_max, noise_max_fraction)
    if window < cell:
        raise ValueError("window must be at least one cell")
    # the plan's own refusals read nothing, so they come before the
    # screen's pass rather than after it
    halo, tile_size = tiles_mod.resolve_plan(cell, window, halo, tile_size)
    if tile_size <= 0:
        raise ValueError(f"tile_size must be positive, got {tile_size}")
    screening = _screening(noise_min, noise_max)
    if screening:
        info = _refuse_screen_from_header(path, noise_min, noise_max)
        seen = screened_seen = 0
        for chunk in las_mod.iter_points(path, fields=("z", "classification"),
                                         chunk_size=chunk_size):
            screened_seen += noise_counts(chunk, noise_min, noise_max)[1]
            seen += np.asarray(chunk["z"]).size
            screen_guard(screened_seen, seen, info["point_count"],
                         noise_max_fraction)
        # the budget is a share of the header's count, so a file that
        # holds fewer records than it claims would be screened against
        # a looser budget than declared -- and the whole driver, which
        # counts what it read, would refuse the same file
        if seen != info["point_count"]:
            raise ValueError(noise_mod.miscounted(path, seen,
                                                  info["point_count"]))
        log(f"screen:  {screened_seen:,} of {seen:,} points outside the "
            f"noise window, within the declared "
            f"{100 * noise_max_fraction:.3f}% (one extra pass, before any "
            f"surface)")
    mins, maxs = project_extent(path, rescan=rescan, chunk_size=chunk_size)
    x_edges, y_edges = tiles_mod.global_edges(mins, maxs, cell)
    plan = tiles_mod.plan_tiles(x_edges, y_edges, cell, halo, tile_size)
    cost = tiles_mod.plan_summary(plan, x_edges, y_edges)

    # classification rides along so noise -- flagged before, or screened
    # now -- stays out of every tile's surface and keeps its flag in the
    # streamed pass
    fields = ("x", "y", "z", "classification")
    if not any_return:
        fields += RETURN_FIELDS
    read, indexed = box_reader(
        path, fields=fields,
        keep=lambda points: candidates(points, any_return, noise_min,
                                       noise_max),
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
    passes = len(plan) + 1 + (1 if rescan else 0) + (1 if screening else 0)
    if indexed:
        log("reads:   COPC index: each tile decompresses only the octree "
            "nodes its box touches -- but the coarse levels span the whole "
            "file, so a small box still costs a good share of a full read, "
            "and the overlap above is paid either way")
    else:
        log(f"reads:   no COPC index, so every tile is a full pass over "
            f"the file: {len(plan)} to build the surface, 1 to write"
            f"{', 1 to rescan' if rescan else ''}"
            f"{', 1 to count the noise screen' if screening else ''} -- "
            f"{passes} passes")

    held = {}
    surface = tiles_mod.tiled_surface(
        read, mins, maxs, cell=cell, slope=slope, window=window,
        low_cut=low_cut, tile_size=tile_size, halo=halo,
        progress=progress, stats=held)
    log(f"surface: {surface.dem.shape[0]} x {surface.dem.shape[1]} cells, "
        f"{int(surface.object_cells.sum()):,} object cells")
    log(f"held:    at most {held['max_tile_points']:,} points in one tile; "
        f"{held['points_read']:,} read across all tiles")

    counts = {"ground": 0, "total": 0, "noise": 0, "already": 0,
              "screened": 0}

    def label(chunk, start):
        # the backstop for an indexed file, whose reads never saw the
        # points outside the boxes they asked for
        stray = tiles_mod.outside(chunk["x"], chunk["y"], x_edges, y_edges)
        if stray:
            raise _stale_header(stray, " in one chunk alone")
        codes = labels(surface, chunk,
                       candidates(chunk, any_return, noise_min, noise_max),
                       threshold=threshold, scalar=scalar,
                       noise_min=noise_min, noise_max=noise_max)
        # ONE count of noise, from the codes written. The reconcile
        # auto-merged a line from each side here, and the two together
        # counted every already-flagged point twice.
        already, screened = noise_counts(chunk, noise_min, noise_max)
        counts["already"] += already
        counts["screened"] += screened
        counts["noise"] += int(np.count_nonzero(
            np.isin(codes, NOISE_CLASSES)))
        counts["ground"] += int(np.count_nonzero(codes == GROUND_CLASS))
        counts["total"] += codes.size
        return {"classification": codes}

    las_mod.stream_update(path, out, label, fields=fields,
                          chunk_size=chunk_size)
    pct = 100.0 * counts["ground"] / max(counts["total"], 1)
    log(f"ground:  {counts['ground']:,} of {counts['total']:,} points "
        f"({pct:.1f}%)")
    _log_noise(log, counts["already"], counts["screened"], noise_min,
               noise_max)
    log(f"wrote:   {out}")
    return {"tiles": len(plan), "indexed": indexed, "halo": halo,
            "tile_size": tile_size, "passes": None if indexed else passes,
            "ground": counts["ground"], "total": counts["total"],
            "noise": counts["noise"], "noise_already": counts["already"],
            "noise_screened": counts["screened"],
            "ground_fraction": pct / 100.0, "cells": int(surface.dem.size),
            "area_read": cost["area_read"], "largest_box": cost["largest_box"],
            "seamed": cost["seamed"], "max_tile_points": held["max_tile_points"],
            "points_read": held["points_read"]}
