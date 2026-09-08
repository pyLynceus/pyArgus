import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from pyargus.formats import las
from tests.synthetic import planar_strip


def _write_las(path, strip, point_source_id=None):
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x = strip["x"]
    data.y = strip["y"]
    data.z = strip["z"]
    data.gps_time = np.linspace(1000.0, 1010.0, strip["x"].size)
    if point_source_id is not None:
        data.point_source_id = point_source_id
    data.write(str(path))
    return path


def test_round_trip(tmp_path):
    strip = planar_strip(1000, (0, 50), (0, 30), seed=1)
    path = _write_las(tmp_path / "strip.las", strip)
    points = las.read_points(path)
    assert np.allclose(points["x"], strip["x"], atol=0.001)
    assert np.allclose(points["z"], strip["z"], atol=0.001)
    assert points["gps_time"].size == 1000


def test_split_by_strip(tmp_path):
    strip = planar_strip(1000, (0, 50), (0, 30), seed=2)
    ids = np.where(np.arange(1000) < 400, 1, 2).astype(np.uint16)
    path = _write_las(tmp_path / "two.las", strip, point_source_id=ids)
    strips = las.split_by_strip(las.read_points(path))
    assert set(strips) == {1, 2}
    assert strips[1]["x"].size == 400
    assert strips[2]["x"].size == 600


def test_unassigned_strips_refuse(tmp_path):
    strip = planar_strip(100, (0, 10), (0, 10), seed=3)
    path = _write_las(tmp_path / "flat.las", strip,
                      point_source_id=np.zeros(100, dtype=np.uint16))
    with pytest.raises(ValueError, match="point_source_id"):
        las.split_by_strip(las.read_points(path))
