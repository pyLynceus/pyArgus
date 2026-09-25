"""What a cloud holds at a control mark, and slabs cut through it.

The generic half of looking at a ground classification in cross-section
and at its control marks. The job scripts that run it against client
deliveries -- which marks, which sections, which clouds -- are kept
outside this public repository; what is here is the geometry and the
one judgement a test can pin: whether a mark's published elevation
corresponds to a SURFACE in the cloud, or to nothing.

A slab is centred on a point, runs along an azimuth, and keeps points
within ``half_width`` of the centre line; each point is placed at its
distance ALONG the line. ``gather`` reads a cloud once for any number of
sections.
"""

import math

import numpy as np

from pyargus.formats import las as las_mod

GROUND, LOW_NOISE, HIGH_NOISE = 2, 7, 18


def _frame(section):
    """Unit vectors along and across the section line."""
    theta = math.radians(section["azimuth"])
    along = np.array([math.sin(theta), math.cos(theta)])   # azimuth from north
    across = np.array([along[1], -along[0]])
    return along, across


def _slab(points, section):
    """Station along the line and offset across it, for points inside."""
    along, across = _frame(section)
    dx = np.asarray(points["x"]) - section["x"]
    dy = np.asarray(points["y"]) - section["y"]
    station = dx * along[0] + dy * along[1]
    offset = dx * across[0] + dy * across[1]
    keep = ((np.abs(station) <= section["length"] / 2.0)
            & (np.abs(offset) <= section["half_width"]))
    return station, keep


def gather(path, sections, *, fields=("x", "y", "z", "classification"),
           chunk_size=las_mod.DEFAULT_CHUNK, log=print):
    """One streaming pass; returns {section name: {station, z, cls}}."""
    out = {s["name"]: {"station": [], "z": [], "cls": []} for s in sections}
    total = 0
    for chunk in las_mod.iter_points(path, fields=fields, chunk_size=chunk_size):
        total += np.asarray(chunk["x"]).size
        for section in sections:
            station, keep = _slab(chunk, section)
            if not keep.any():
                continue
            bucket = out[section["name"]]
            bucket["station"].append(station[keep])
            bucket["z"].append(np.asarray(chunk["z"])[keep])
            bucket["cls"].append(np.asarray(chunk["classification"])[keep])
    for name, bucket in out.items():
        for key in ("station", "z", "cls"):
            bucket[key] = (np.concatenate(bucket[key]) if bucket[key]
                           else np.array([]))
    log(f"{path.name}: {total:,} points read, "
        + ", ".join(f"{n} {b['z'].size:,}" for n, b in out.items()))
    return out


def _residual_text(residual):
    """The residual, or why there isn't one.

    A mark on a roof, a bridge deck or open water has no class-2 point
    within its radius, so the residual is None and formatting it with
    ``:+.2f`` kills the whole run at the summary line -- after both
    streaming passes have already been paid for.
    """
    return "no ground under it" if residual is None else f"{residual:+.2f}"


def _standout(elevations, published, band=0.5):
    """How far the band at ``published`` stands out from its neighbours.

    A COUNT of points at an elevation proves nothing on its own, and
    believing otherwise is the mistake this function exists to stop. A
    vertical face -- a sound wall, a barrier, a sign -- returns points
    at EVERY elevation it spans, so any one-foot band across it holds a
    similar handful, and a reading that only counts them calls the wall
    a surface at whatever height you happen to ask about. A real flat
    surface is a spike against its own neighbourhood.

    So this returns the band's count divided by the larger of the two
    bands immediately above and below it. About 1 means a face or
    nothing; much more than 1 means a surface.
    """
    elevations = np.asarray(elevations)
    here = np.count_nonzero(np.abs(elevations - published) <= band)
    below = np.count_nonzero((elevations < published - band)
                             & (elevations >= published - 3 * band))
    above = np.count_nonzero((elevations > published + band)
                             & (elevations <= published + 3 * band))
    return here / max(below, above, 1)


def _sits_on(elevations, published, ground_median, band=0.5):
    """What the published elevation actually corresponds to."""
    if not np.asarray(elevations).size:
        return "nothing in the cloud"
    if (ground_median is not None
            and abs(ground_median - published) <= band):
        return "ground"
    if _standout(elevations, published, band) >= 3.0:
        return "a flat surface above the ground"
    return "nothing that stands out at that elevation"


def mark_profiles(path, marks, *, radius=5.0, log=print):
    """What the cloud actually holds at each control mark.

    ``control-by-strip`` compares a mark's published elevation against
    the GROUND under it, which is the right question only if the mark
    IS on the ground. A mark whose residual is large and identical on
    every strip is not noise: its published elevation is either on
    something, or on nothing.

    Answering that with a COUNT at the published elevation is the trap,
    and it caught me once: a few dozen points looked like a structure
    top, and a vertical face returns points at every elevation it spans,
    so it was the slice of a sound wall that happened to land in the
    band I asked about. ``_standout`` asks the question that survives:
    does the band stand out from the bands beside it? On the job that
    motivated this, marks on a surface read several times to thousands
    of times, and the mis-recorded one read well under 1.
    """
    held = {key: {"all": [], "ground": []} for key in marks}
    for chunk in las_mod.iter_points(path, fields=("x", "y", "z",
                                                   "classification")):
        x, y = np.asarray(chunk["x"]), np.asarray(chunk["y"])
        z = np.asarray(chunk["z"])
        codes = np.asarray(chunk["classification"])
        for key, (east, north, _) in marks.items():
            near = (np.abs(x - east) <= radius) & (np.abs(y - north) <= radius)
            if near.any():
                held[key]["all"].append(z[near])
                held[key]["ground"].append(z[near][codes[near] == GROUND])
    out = []
    for key, (_, _, published) in marks.items():
        every = (np.concatenate(held[key]["all"]) if held[key]["all"]
                 else np.array([]))
        ground = (np.concatenate(held[key]["ground"]) if held[key]["ground"]
                  else np.array([]))
        if not every.size:
            out.append({"mark": key, "published": published, "points": 0})
            continue
        at_published = int(np.count_nonzero(np.abs(every - published) <= 0.5))
        median = float(np.median(ground)) if ground.size else None
        out.append({
            "mark": key, "published": round(published, 3),
            "points": int(every.size), "ground_points": int(ground.size),
            "ground_median": None if median is None else round(median, 3),
            "residual": None if median is None else round(median - published, 3),
            "highest_point": round(float(every.max()), 3),
            "points_at_published": at_published,
            "standout": round(_standout(every, published), 2),
            "sits_on": _sits_on(every, published, median)})
    for row in out:
        if not row["points"]:
            log(f"  mark {row['mark']:>5}: no points within {radius:g} ft")
            continue
        ground = ("        --" if row["ground_median"] is None
                  else f"{row['ground_median']:>9,.2f}")
        log(f"  mark {row['mark']:>5}: published {row['published']:>9,.2f} "
            f"ground {ground} ({_residual_text(row['residual'])})  "
            f"{row['points_at_published']:>5,} points there, standing out "
            f"{row['standout']:>6.2f}x from the bands beside it "
            f"-> {row['sits_on']}")
    return out
