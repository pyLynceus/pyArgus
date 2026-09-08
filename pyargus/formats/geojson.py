"""GeoJSON lines: contours out, breaklines in.

Breaklines arrive as LineString/MultiLineString features and MUST
carry z on every coordinate -- a breakline's elevations are surveyed
truth the TIN will honor, so a 2D line is refused rather than draped
silently.
"""

import json

import numpy as np


def write_contours_geojson(path, lines):
    """ContourLines as a FeatureCollection of 3D LineStrings."""
    features = []
    for line in lines:
        coords = [[round(float(x), 4), round(float(y), 4),
                   round(line.level, 4)] for x, y in line.xy]
        features.append({
            "type": "Feature",
            "properties": {"elevation": line.level,
                           "index": bool(line.is_index),
                           "closed": bool(line.closed)},
            "geometry": {"type": "LineString", "coordinates": coords},
        })
    with open(path, "w", newline="\n") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)


def read_breaklines_geojson(path):
    """Read 3D LineString/MultiLineString features as (N, 3) arrays."""
    with open(path) as fh:
        data = json.load(fh)
    features = data.get("features", [data] if "geometry" in data else [])
    if not features:
        raise ValueError(f"{path}: no features")
    lines = []
    for k, feature in enumerate(features):
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        if kind == "LineString":
            parts = [geometry["coordinates"]]
        elif kind == "MultiLineString":
            parts = geometry["coordinates"]
        else:
            raise ValueError(f"{path}: feature {k} is {kind!r}, not a "
                             f"LineString/MultiLineString")
        for part in parts:
            arr = np.asarray(part, dtype=float)
            if arr.ndim != 2 or arr.shape[1] < 3:
                raise ValueError(
                    f"{path}: feature {k} has 2D coordinates; a breakline "
                    f"needs surveyed z on every vertex, and draping it "
                    f"silently is not this module's call to make")
            lines.append(arr[:, :3])
    return lines
