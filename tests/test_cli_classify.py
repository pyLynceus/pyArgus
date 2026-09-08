import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from pyargus import cli
from pyargus.classify import ground
from tests.synthetic import classification_scene


@pytest.fixture(scope="module")
def scene_las(tmp_path_factory):
    points, truth = classification_scene(seed=5)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    data.return_number = np.ones(truth.size, dtype=np.uint8)
    data.number_of_returns = np.ones(truth.size, dtype=np.uint8)
    path = tmp_path_factory.mktemp("cloud") / "scene.las"
    data.write(str(path))
    return path, truth


def test_classify_ground_writes_a_new_file(scene_las, tmp_path):
    src, truth = scene_las
    out = tmp_path / "classified.las"
    rc = cli.main(["classify-ground", str(src), "--out", str(out),
                   "--cell", "1.0", "--window", "18.0"])
    assert rc == 0
    result = laspy.read(str(out))
    predicted = np.asarray(result.classification) == 2
    score = ground.confusion(predicted, truth)
    assert score["agreement"] > 0.97
    # the input file was not touched
    original = laspy.read(str(src))
    assert not np.any(np.asarray(original.classification) == 2)


def test_classify_ground_refuses_in_place_and_existing(scene_las, tmp_path):
    src, _ = scene_las
    with pytest.raises(SystemExit, match="new file"):
        cli.main(["classify-ground", str(src), "--out", str(src)])
    out = tmp_path / "exists.las"
    out.write_bytes(b"already here")
    with pytest.raises(SystemExit, match="--force"):
        cli.main(["classify-ground", str(src), "--out", str(out)])


def test_dtm_command(scene_las, tmp_path):
    src, _ = scene_las
    classified = tmp_path / "classified.las"
    cli.main(["classify-ground", str(src), "--out", str(classified)])
    out = tmp_path / "dtm.asc"
    rc = cli.main(["dtm", str(classified), "--out", str(out), "--cell", "2.0"])
    assert rc == 0
    header = dict(line.split() for line in
                  out.read_text().splitlines()[:6])
    assert header["cellsize"] == "2.000000"
    with pytest.raises(SystemExit, match="no class-7"):
        cli.main(["dtm", str(classified), "--out", str(out),
                  "--ground-class", "7"])


def test_contours_cli(scene_las, tmp_path):
    src, _ = scene_las
    classified = tmp_path / "classified.las"
    cli.main(["classify-ground", str(src), "--out", str(classified)])
    out = tmp_path / "contours.dxf"
    rc = cli.main(["contours", str(classified), "--out", str(out),
                   "--interval", "1.0", "--cell", "2.0"])
    assert rc == 0
    text = out.read_text()
    assert "POLYLINE" in text and text.rstrip().endswith("EOF")
    gj = tmp_path / "contours.geojson"
    rc = cli.main(["contours", str(classified), "--out", str(gj),
                   "--interval", "1.0", "--cell", "2.0", "--smooth", "1"])
    assert rc == 0
    import json
    assert json.loads(gj.read_text())["features"]
    with pytest.raises(SystemExit, match=".dxf or .geojson"):
        cli.main(["contours", str(classified), "--out",
                  str(tmp_path / "contours.txt")])


def test_contours_breakline_path_respects_voids(tmp_path):
    """The review panel proved the TIN path invented contours across
    interior voids and ignored --max-fill; the coverage mask pins the
    fix: a hole in the ground data stays contour-free even when a
    breakline switches the surface to a TIN."""
    import json

    rng = np.random.default_rng(11)
    n = 12000
    gx = rng.uniform(0, 100, n)
    gy = rng.uniform(0, 100, n)
    hole = (gx > 35) & (gx < 65) & (gy > 35) & (gy < 65)
    gx, gy = gx[~hole], gy[~hole]
    gz = 50.0 + 0.1 * gx
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = gx, gy, gz
    data.classification = np.full(gx.size, 2, dtype=np.uint8)
    cloud = tmp_path / "holed.las"
    data.write(str(cloud))

    lines = tmp_path / "line.geojson"
    lines.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "LineString",
                                   "coordinates": [[5, 5, 50.5],
                                                   [5, 95, 50.5]]}}]}))
    out = tmp_path / "contours.geojson"
    rc = cli.main(["contours", str(cloud), "--out", str(out),
                   "--interval", "1.0", "--cell", "2.0", "--max-fill", "1",
                   "--breaklines", str(lines)])
    assert rc == 0
    features = json.loads(out.read_text())["features"]
    assert features
    for feature in features:
        for x, y, _ in feature["geometry"]["coordinates"]:
            assert not (39.0 < x < 61.0 and 39.0 < y < 61.0), (x, y)
