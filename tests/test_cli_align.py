import numpy as np
import pytest

laspy = pytest.importorskip("laspy")
pytest.importorskip("pyproj")

from pyargus import cli
from tests.synthetic import write_sbet
from tests.test_attach import GEOID, eastbound_scene, scene_points


@pytest.fixture(scope="module")
def scene_files(tmp_path_factory):
    root = tmp_path_factory.mktemp("align")
    sbet, e, n, z = eastbound_scene()
    points, _ = scene_points(sbet, e, n, z)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    data.gps_time = points["gps_time"]
    data.point_source_id = points["point_source_id"]
    data.classification = np.full(points["x"].size, 2, dtype=np.uint8)
    cloud = root / "block.las"
    data.write(str(cloud))
    traj = write_sbet(root / "traj.sbet", sbet)
    return cloud, traj


def test_align_cli_runs_and_reports_near_zero(scene_files, capsys, tmp_path):
    cloud, traj = scene_files
    out = tmp_path / "fixed.las"
    rc = cli.main(["align", str(cloud), "--sbet", str(traj),
                   "--map-crs", "EPSG:6447", "--vertical", str(GEOID),
                   "--no-boresight", "--cell", "20", "--min-points", "6",
                   "--write", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "heading source 'heading'" in text
    # AGL is the vertical-plumbing witness: a sign-flipped, halved, or
    # ignored --vertical lands far from the constructed 300 ft.
    assert "AGL 300" in text
    assert "wrote:" in text
    # the scene is aligned by construction: corrections stay tiny and
    # applying them barely moves the cloud
    fixed = laspy.read(str(out))
    original = laspy.read(str(cloud))
    assert np.abs(np.asarray(fixed.z) - np.asarray(original.z)).max() < 0.02


def test_align_cli_refuses_in_place_write(scene_files):
    cloud, traj = scene_files
    with pytest.raises(SystemExit, match="new file"):
        cli.main(["align", str(cloud), "--sbet", str(traj),
                  "--map-crs", "EPSG:6447", "--vertical", str(GEOID),
                  "--write", str(cloud)])


def test_align_cli_requires_a_vertical_story(scene_files):
    cloud, traj = scene_files
    with pytest.raises(ValueError, match="vertical"):
        cli.main(["align", str(cloud), "--sbet", str(traj),
                  "--map-crs", "EPSG:6447"])
