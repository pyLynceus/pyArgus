"""LAS/LAZ point clouds, through laspy.

A thin wrapper: the rest of the suite works on plain numpy arrays and
never sees a laspy object, so the dependency stays optional and swaps
out cleanly if PDAL takes over ingest later.
"""

import numpy as np


def _laspy():
    try:
        import laspy
    except ImportError as exc:
        raise ImportError(
            "reading LAS/LAZ needs laspy: uv pip install -e \".[lidar]\""
        ) from exc
    return laspy


FIELDS = ("x", "y", "z", "gps_time", "intensity", "classification",
          "point_source_id", "return_number", "number_of_returns")


def read_points(path, fields=FIELDS):
    """Read a LAS/LAZ file into a dict of numpy arrays.

    x/y/z arrive scaled (real coordinates, float64). A requested field
    the file does not carry raises rather than returning zeros.
    """
    laspy = _laspy()
    with laspy.open(path) as reader:
        las = reader.read()
    out = {}
    for name in fields:
        try:
            out[name] = np.asarray(las[name])
        except (KeyError, AttributeError) as exc:
            raise ValueError(f"{path}: point format has no field {name!r}") from exc
    return out


def split_by_strip(points):
    """Split a points dict into {point_source_id: points dict}.

    Strip identity rides on point_source_id per the LAS spec; a file
    where every point carries id 0 was never assigned strips, and this
    raises so the caller finds out now rather than in the overlap QA.
    """
    ids = points["point_source_id"]
    unique = np.unique(ids)
    if unique.size == 1 and unique[0] == 0:
        raise ValueError("every point has point_source_id 0: strips were never assigned")
    return {int(u): {k: v[ids == u] for k, v in points.items()} for u in unique}
