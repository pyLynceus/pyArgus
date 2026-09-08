import struct
import zlib

import numpy as np
import pytest

from pyargus.qa import raster


def decode_png(data):
    """Minimal decoder for the PNGs this suite writes (filter 0, one IDAT)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, chunks = 8, {}
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        assert crc == zlib.crc32(tag + payload)
        chunks[tag] = chunks.get(tag, b"") + payload
        pos += 12 + length
    w, h, depth, ctype = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (depth, ctype) == (8, 6)
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = 1 + 4 * w
    rows = []
    for r in range(h):
        line = raw[r * stride:(r + 1) * stride]
        assert line[0] == 0  # filter type
        rows.append(np.frombuffer(line[1:], dtype=np.uint8).reshape(w, 4))
    return np.stack(rows)


def test_png_round_trip(tmp_path):
    rng = np.random.default_rng(1)
    rgba = rng.integers(0, 256, (7, 5, 4), dtype=np.uint8)
    path = tmp_path / "img.png"
    raster.write_png(path, rgba)
    assert np.array_equal(decode_png(path.read_bytes()), rgba)


def test_png_refuses_wrong_shape():
    with pytest.raises(ValueError):
        raster.encode_png(np.zeros((4, 4, 3), dtype=np.uint8))


def test_grid_to_image_orientation():
    grid = np.zeros((3, 2))          # 3 columns of x, 2 rows of y
    grid[0, 0] = 7.0                 # west-most, south-most cell
    img = raster.grid_to_image(grid)
    assert img.shape == (2, 3)       # H=ny, W=nx
    assert img[-1, 0] == 7.0         # bottom-left of a north-up image


def test_world_file_puts_top_left_center(tmp_path):
    x_edges = np.array([100.0, 102.0, 104.0])
    y_edges = np.array([500.0, 502.0, 504.0])
    path = tmp_path / "img.pgw"
    raster.write_world_file(path, x_edges, y_edges)
    vals = [float(v) for v in path.read_text().split()]
    assert vals == [2.0, 0.0, 0.0, -2.0, 101.0, 503.0]


def test_diverging_colors_and_transparency():
    grid = np.array([[-1.0], [0.0], [1.0], [np.nan]])  # 4 x-cols, 1 y-row
    rgba = raster.diverging_rgba(grid, limit=1.0)
    img = raster.grid_to_image(grid)
    assert rgba.shape == img.shape + (4,)
    low, mid, high, nan = rgba[0, 0], rgba[0, 1], rgba[0, 2], rgba[0, 3]
    assert low[2] > low[0]           # negative is blue
    assert high[0] > high[2]         # positive is red
    assert mid[3] == 255 and nan[3] == 0
    # values beyond the limit clip rather than wrap
    clipped = raster.diverging_rgba(np.array([[-5.0], [5.0]]), limit=1.0)
    assert np.array_equal(clipped[0, 0], low)
    assert np.array_equal(clipped[0, 1], high)


def test_sequential_transparency_and_scale():
    grid = np.array([[0.0], [1.0], [2.0]])
    rgba = raster.sequential_rgba(grid, vmax=2.0)
    assert rgba[0, 0, 3] == 0        # zero density is transparent
    assert rgba[0, 1, 3] == 255 and rgba[0, 2, 3] == 255
    # deeper color at higher density (green channel drops toward dark)
    assert rgba[0, 2, 0] < rgba[0, 1, 0]
    with pytest.raises(ValueError):
        raster.sequential_rgba(np.zeros((2, 2)))
