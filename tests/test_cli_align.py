import numpy as np
import pytest

laspy = pytest.importorskip("laspy")
pytest.importorskip("pyproj")

from pyargus import cli
from tests.synthetic import write_sbet
from tests.test_attach import GEOID, WEEK, eastbound_scene, scene_points


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


def test_align_cli_drift_recovers_injected_wander(scene_files, capsys,
                                                  tmp_path):
    # Inject a sinusoidal wander on strip 2 only and demand the full
    # LAS -> SBET -> solve -> --write path scrub it. Control marks are
    # ESSENTIAL here, not decoration: two fully overlapping strips
    # observe only the DIFFERENCE of their drift curves, and the
    # minimum-stiffness answer without marks splits the wander half
    # and half between the strips (measured: strip 1 absorbed the
    # same max as strip 2). The marks pin the common mode.
    cloud, traj = scene_files
    las = laspy.read(str(cloud))
    sow = np.asarray(las.gps_time) + 1_000_000_000.0 - WEEK * 604800.0
    wander = 0.08 * np.sin(2 * np.pi * (sow - sow.min()) / 20.0)
    strip2 = np.asarray(las.point_source_id) == 2
    z0 = np.asarray(las.z).copy()
    las.z = z0 + np.where(strip2, wander, 0.0)
    wandered = tmp_path / "wandered.las"
    las.write(str(wandered))

    rng = np.random.default_rng(5)
    me = 1_943_000.0 + np.linspace(60.0, 1440.0, 27)
    mn = 1_628_800.0 + rng.uniform(-60.0, 60.0, 27)
    marks = tmp_path / "marks.csv"
    with open(marks, "w") as f:
        for i, (e, n) in enumerate(zip(me, mn)):
            f.write(f"{i + 1},{n:.3f},{e:.3f},650.000\n")

    out = tmp_path / "fixed_drift.las"
    rc = cli.main(["align", str(wandered), "--sbet", str(traj),
                   "--map-crs", "EPSG:6447", "--vertical", str(GEOID),
                   "--no-boresight", "--cell", "40", "--min-points", "6",
                   "--drift-spacing", "2.5",
                   "--control", str(marks), "--control-order", "pnez",
                   "--control-radius", "30", "--write", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "drift strip" in text and "span" in text
    assert "ABSOLUTE" in text
    fixed = laspy.read(str(out))
    dz = np.asarray(fixed.z) - z0            # against the PRE-WANDER truth
    # strip 2's wander is scrubbed and strip 1 stays put -- the
    # per-strip curves are distinct, so drift_by_sid cross-wiring
    # would blow the strip-1 bound by ~6x
    assert np.abs(dz[strip2]).max() < 0.05, float(np.abs(dz[strip2]).max())
    assert float(np.std(dz[strip2])) < 0.01
    assert np.abs(dz[~strip2]).max() < 0.025, float(np.abs(dz[~strip2]).max())


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
