"""Rasters the QA writes: PNG images with world files, no GDAL.

A QA map needs to land in GIS beside the delivery. GeoTIFF needs GDAL;
an RGBA PNG with a .pgw world file needs nothing beyond stdlib zlib and
loads in QGIS, Global Mapper, and LP360 alike. So the QA writes its
maps this way, and GDAL stays out of the dependency tree until surfaces
need it in Phase 3.

Grids arrive as the QA produces them -- indexed [ix, iy] with y
ascending -- and are flipped here into north-up image rows exactly once,
in ``grid_to_image``. Nothing else in the suite reorients rasters.
"""

import struct
import zlib

import numpy as np

# Diverging map for dZ: blue below, white at zero, red above.
_DIVERGING_LOW = np.array([44.0, 86.0, 164.0])
_DIVERGING_MID = np.array([247.0, 247.0, 244.0])
_DIVERGING_HIGH = np.array([178.0, 40.0, 52.0])
# Sequential map for density: pale ground to deep green.
_SEQ_LOW = np.array([238.0, 243.0, 238.0])
_SEQ_HIGH = np.array([23.0, 77.0, 52.0])


def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload)))


def encode_png(rgba):
    """Encode an (H, W, 4) uint8 array as RGBA PNG bytes (filter 0, one IDAT)."""
    rgba = np.asarray(rgba)
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
        raise ValueError(f"rgba must be (H, W, 4) uint8, got {rgba.shape} {rgba.dtype}")
    height, width = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[row].tobytes() for row in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))


def write_png(path, rgba):
    """Write an (H, W, 4) uint8 array as an RGBA PNG file."""
    with open(path, "wb") as fh:
        fh.write(encode_png(rgba))


def write_world_file(path, x_edges, y_edges):
    """Write a .pgw for the north-up image of a grid with these edges.

    World-file convention: cell sizes (y negative), zero rotation, then
    the coordinates of the CENTER of the top-left pixel.
    """
    cx = float(x_edges[1] - x_edges[0])
    cy = float(y_edges[1] - y_edges[0])
    values = (cx, 0.0, 0.0, -cy,
              float(x_edges[0]) + cx / 2.0, float(y_edges[-1]) - cy / 2.0)
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(f"{v:.6f}" for v in values) + "\n")


def grid_to_image(grid):
    """[ix, iy] grid with y ascending -> (H, W) rows running north to south."""
    return np.asarray(grid).T[::-1]


def diverging_rgba(grid, limit):
    """Color a dZ grid over [-limit, +limit]; NaN cells are transparent."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    img = grid_to_image(grid).astype(float)
    finite = np.isfinite(img)
    t = np.clip(np.where(finite, img, 0.0) / limit, -1.0, 1.0)
    up = np.clip(t, 0.0, 1.0)[..., None]
    down = np.clip(-t, 0.0, 1.0)[..., None]
    rgb = (_DIVERGING_MID
           + up * (_DIVERGING_HIGH - _DIVERGING_MID)
           + down * (_DIVERGING_LOW - _DIVERGING_MID))
    out = np.zeros(img.shape + (4,), dtype=np.uint8)
    out[..., :3] = np.round(rgb).astype(np.uint8)
    out[..., 3] = np.where(finite, 255, 0)
    return out


def sequential_rgba(grid, vmax=None):
    """Color a density grid from pale to deep; zero/NaN cells transparent.

    ``vmax`` defaults to the 98th percentile of the covered cells so a
    few dense cells do not wash out the map.
    """
    img = grid_to_image(grid).astype(float)
    covered = np.isfinite(img) & (img > 0)
    if not covered.any():
        raise ValueError("no covered cells to draw")
    if vmax is None:
        vmax = float(np.percentile(img[covered], 98))
    if vmax <= 0:
        raise ValueError("vmax must be positive")
    t = np.clip(np.where(covered, img, 0.0) / vmax, 0.0, 1.0)[..., None]
    rgb = _SEQ_LOW + t * (_SEQ_HIGH - _SEQ_LOW)
    out = np.zeros(img.shape + (4,), dtype=np.uint8)
    out[..., :3] = np.round(rgb).astype(np.uint8)
    out[..., 3] = np.where(covered, 255, 0)
    return out
