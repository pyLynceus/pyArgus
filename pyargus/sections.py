"""Bounded-memory read-only corridor sections from full LAS/LAZ files."""
from dataclasses import dataclass
import csv
import json
from pathlib import Path
import numpy as np


def section_coordinates(x, y, start, end, width):
    a, b = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    if a.shape != (2,) or b.shape != (2,) or not np.isfinite([*a, *b, width]).all() or width <= 0:
        raise ValueError("Section endpoints and width must be finite; width must be positive.")
    delta = b-a
    length = float(np.linalg.norm(delta))
    if length <= 1e-9:
        raise ValueError("Section endpoints must be distinct.")
    ux, uy = delta/length
    dx, dy = np.asarray(x)-a[0], np.asarray(y)-a[1]
    station, across = dx*ux+dy*uy, -dx*uy+dy*ux
    keep = (station >= 0) & (station <= length) & (np.abs(across) <= width/2)
    return station, across, keep


@dataclass
class Section:
    points: np.ndarray  # X,Y,Z,station,cross-track
    classes: np.ndarray
    lines: np.ndarray
    files: np.ndarray
    point_indices: np.ndarray
    matched: int
    matched_by_file: list
    inputs: list
    crs: str
    start: list
    end: list
    width: float
    limit: int


def extract_section(paths, start, end, width, *, limit=100000, cancel=None,
                    progress=lambda s: None, chunk_size=250000):
    import laspy
    from pyargus.job_manifest import identity
    section_coordinates([], [], start, end, width)
    if limit < 1 or chunk_size < 1:
        raise ValueError("Sample limit and chunk size must be positive.")
    paths = [Path(p).resolve() for p in paths]
    if not paths or len(set(paths)) != len(paths):
        raise ValueError("Choose distinct cloud files.")
    inputs = [identity(p) for p in paths]
    crs = None
    for path in paths:
        with laspy.open(path) as source:
            current = source.header.parse_crs()
            if current is None or not current.is_projected:
                raise ValueError("Sections require a declared projected LAS CRS.")
            if crs is not None and current != crs:
                raise ValueError("Cloud coordinate systems differ.")
            factors = [axis.unit_conversion_factor for axis in current.axis_info]
            if not np.allclose(factors, factors[0], rtol=1e-12, atol=0):
                raise ValueError("Sections require matching XYZ units.")
            crs = current
    # Independent uniform priority sampling for each layer preserves small
    # comparison layers. Total display bound is limit * number of layers.
    outputs, matched_by_file = [], []
    rng = np.random.default_rng(0)
    for file_id, path in enumerate(paths):
        progress(f"Scanning section: {path.name}")
        keys = np.empty(0)
        rows = np.empty((0, 5))
        classes = np.empty(0, dtype=np.uint8)
        lines = np.empty(0, dtype=np.uint16)
        indices = np.empty(0, dtype=np.int64)
        matched, offset = 0, 0
        with laspy.open(path) as source:
            for chunk in source.chunk_iterator(chunk_size):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Section cancelled")
                x, y, z = np.asarray(chunk.x), np.asarray(chunk.y), np.asarray(chunk.z)
                station, across, mask = section_coordinates(x, y, start, end, width)
                mask &= np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
                ids = np.flatnonzero(mask)
                matched += len(ids)
                keys = np.r_[keys, rng.random(len(ids))]
                rows = np.concatenate([rows, np.column_stack([x[ids], y[ids], z[ids], station[ids], across[ids]])])
                classes = np.r_[classes, np.asarray(chunk.classification)[ids]]
                lines = np.r_[lines, np.asarray(chunk.point_source_id)[ids]]
                indices = np.r_[indices, ids+offset]
                if len(keys) > limit:
                    chosen = np.argpartition(keys, limit-1)[:limit]
                    keys, rows, classes, lines, indices = (a[chosen] for a in (keys, rows, classes, lines, indices))
                offset += len(chunk)
        matched_by_file.append(matched)
        outputs.append((rows, classes, lines, np.full(len(rows), file_id, dtype=np.int32), indices))
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Section cancelled")
    for item, path in zip(inputs, paths):
        if identity(path) != item:
            raise ValueError(f"Cloud changed during section extraction: {path}")
    arrays = [np.concatenate([o[i] for o in outputs]) for i in range(5)]
    return Section(*arrays, sum(matched_by_file), matched_by_file, inputs, crs.to_wkt(),
                   list(map(float, start)), list(map(float, end)), float(width), int(limit))


def export_section(section, path):
    """Export displayed sample plus its definition; never claim a full extract."""
    path = Path(path)
    meta = path.with_suffix(path.suffix + ".json")
    if path.exists() or meta.exists():
        raise ValueError("Choose a new export name; CSV or definition already exists.")
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["source", "point_index", "x", "y", "z", "station", "cross_track", "classification", "las_line_id"])
        for row, cls, line, file_id, index in zip(section.points, section.classes, section.lines, section.files, section.point_indices):
            writer.writerow([section.inputs[int(file_id)]["path"], int(index), *row, int(cls), int(line)])
    metadata = json.dumps(dict(schema_version=1, start=section.start, end=section.end,
        full_width=section.width, crs=section.crs, inputs=section.inputs,
        matched=section.matched, matched_by_file=section.matched_by_file,
        displayed=len(section.points), sample_limit_per_file=section.limit,
        sampling="deterministic uniform priority sample per file; source point indices are zero-based",
        note="CSV contains the displayed sample, not necessarily all corridor returns. XYZ units and vertical datum must agree; projected CRS alone does not establish the vertical datum."), indent=2)
    with meta.open("x", encoding="utf-8") as stream:
        stream.write(metadata)
    return meta
