import json

import numpy as np
import pytest

from pyargus.formats import dxf, geojson
from pyargus.surfaces.contours import ContourLine


def sample_lines():
    open_line = ContourLine(
        level=651.0, xy=np.array([[0.0, 0.0], [5.0, 1.0], [10.0, 0.5]]),
        closed=False, is_index=False)
    ring = ContourLine(
        level=655.0,
        xy=np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0],
                     [0.0, 0.0]]),
        closed=True, is_index=True)
    return [open_line, ring]


def parse_dxf(path):
    lines = path.read_text().splitlines()
    return list(zip(lines[0::2], lines[1::2]))


def test_dxf_structure(tmp_path):
    path = tmp_path / "contours.dxf"
    dxf.write_contours_dxf(path, sample_lines())
    pairs = parse_dxf(path)
    values = [v for _, v in pairs]
    assert values.count("POLYLINE") == 2
    assert values.count("SEQEND") == 2
    assert values[-1] == "EOF"
    assert "CONTOUR_INDEX" in values and "CONTOUR_INTERMEDIATE" in values
    # the ring carries the closed flag (8|1) and drops its repeated
    # closing vertex; the open line stays flag 8
    flags = [v for c, v in pairs if c == "70" and v in ("8", "9")]
    assert sorted(flags) == ["8", "9"]
    assert values.count("VERTEX") == 3 + 4
    # every vertex z is its line's level
    zs = {v for c, v in pairs if c == "30"}
    assert "651.0000" in zs and "655.0000" in zs


def test_dxf_refuses_empty(tmp_path):
    with pytest.raises(ValueError, match="no contour"):
        dxf.write_contours_dxf(tmp_path / "x.dxf", [])


def test_geojson_round_trip(tmp_path):
    path = tmp_path / "contours.geojson"
    geojson.write_contours_geojson(path, sample_lines())
    data = json.loads(path.read_text())
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    ring = data["features"][1]
    assert ring["properties"] == {"elevation": 655.0, "index": True,
                                  "closed": True}
    coords = np.array(ring["geometry"]["coordinates"])
    assert coords.shape == (5, 3)
    assert np.allclose(coords[:, 2], 655.0)


def test_breakline_reader(tmp_path):
    path = tmp_path / "lines.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "LineString",
                          "coordinates": [[0, 0, 10], [5, 5, 12]]}},
            {"type": "Feature", "properties": {},
             "geometry": {"type": "MultiLineString",
                          "coordinates": [[[1, 1, 9], [2, 2, 9]],
                                          [[3, 3, 8], [4, 4, 8]]]}},
        ]}))
    lines = geojson.read_breaklines_geojson(path)
    assert len(lines) == 3
    assert lines[0].shape == (2, 3)
    assert np.allclose(lines[2][:, 2], 8.0)


def test_breakline_reader_refuses_2d_and_non_lines(tmp_path):
    flat = tmp_path / "flat.geojson"
    flat.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "LineString",
                                   "coordinates": [[0, 0], [5, 5]]}}]}))
    with pytest.raises(ValueError, match="2D"):
        geojson.read_breaklines_geojson(flat)
    point = tmp_path / "point.geojson"
    point.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "Point",
                                   "coordinates": [0, 0, 1]}}]}))
    with pytest.raises(ValueError, match="LineString"):
        geojson.read_breaklines_geojson(point)
