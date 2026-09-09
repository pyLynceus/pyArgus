"""pyargus colorize, end to end: LAS in, EO + images + .cal, RGB out."""

import json

import numpy as np
import pytest

laspy = pytest.importorskip("laspy")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from pyargus import cli
from tests.test_colorize import checker, render_nadir_image, simple_camera

H = 100.0


@pytest.fixture()
def scene(tmp_path):
    """A checkerboard world seen by one synthetic camera, plus a pf6
    cloud (no RGB fields -- the conversion path must announce itself)."""
    cam = simple_camera(width=600, height=400)
    origin = np.array([50.0, 80.0, H])
    stored = render_nadir_image(cam, origin, checker)
    imgdir = tmp_path / "imagery"
    imgdir.mkdir()
    Image.fromarray(stored).save(imgdir / "0001.png")
    (imgdir / "0001.png.cal").write_text(json.dumps([{
        "CalibratedFocalLength": cam.focal_mm / cam.pixel_mm,
        "ImageWidth": cam.width_px, "ImageHeight": cam.height_px,
    }]))

    eo = tmp_path / "eo.csv"
    eo.write_text(
        "Timestamp, Filename, Origin(Easting[m], Northing[m], Height[m]),"
        " Direction, , , Up, , \n"
        f"100.0,0001.png,50.0,80.0,{H},0.0,0.0,-1.0,0.0,1.0,0.0\n")

    gx, gy = np.meshgrid(np.arange(35.0, 76.0, 10.0),
                         np.arange(65.0, 96.0, 10.0))
    xyz = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    data.gps_time = np.full(xyz.shape[0], 100.0)
    data.point_source_id = np.ones(xyz.shape[0], dtype=np.uint16)
    cloud = tmp_path / "cloud.las"
    data.write(str(cloud))
    return cloud, eo, imgdir, xyz


def run(args_list):
    return cli.main(["colorize"] + [str(a) for a in args_list])


def test_colorize_cli_paints_and_converts_pf6(scene, tmp_path, capsys):
    cloud, eo, imgdir, xyz = scene
    out = tmp_path / "rgb.las"
    rc = run([cloud, "--eo", eo, "--images", imgdir,
              "--quarter-turns", "0", "--out", out])
    assert rc == 0
    text = capsys.readouterr().out
    assert "point format 6 carries no RGB" in text
    assert "wrote:" in text
    result = laspy.read(str(out))
    assert result.header.point_format.id == 7
    want = checker(xyz[:, 0], xyz[:, 1]).astype(np.uint16) << 8
    got = np.column_stack([result.red, result.green, result.blue])
    # LAS 16-bit RGB carries the 8-bit sample shifted left -- writing
    # it raw would be a near-black cloud
    assert np.array_equal(got, want)
    assert got.max() >= 200 << 8


def test_colorize_cli_refuses_a_scaled_datum_through_coverage(scene,
                                                              tmp_path,
                                                              capsys):
    """The overlap and AGL gates catch a mismatch that SEPARATES the
    two datasets. One that merely scales them -- metres written over
    survey feet, the exact lie the LP360 header tells -- keeps the
    boxes overlapping and the AGL positive, and used to write a
    confidently wrong cloud with exit 0. Coverage is what it looks
    like from here."""
    cloud, _, imgdir, _ = scene
    # horizontally exact, height in METRES over a survey-feet cloud:
    # the bboxes still overlap and the AGL is still positive, so both
    # earlier gates pass and every footprint comes out 3.28x too small
    metric = tmp_path / "metric.csv"
    metric.write_text(f"100.0,0001.png,50.0,80.0,{H / 3.28084},"
                      f"0,0,-1,0,1,0\n")
    with pytest.raises(SystemExit, match="min-coverage"):
        run([cloud, "--eo", metric, "--images", imgdir,
             "--quarter-turns", "0", "--min-coverage", "50",
             "--out", tmp_path / "scaled.las"])
    assert not (tmp_path / "scaled.las").exists()
    text = capsys.readouterr().out
    assert "colored:" in text          # it says what it saw first
    # and at the default threshold it cautions rather than passing the
    # wrong cloud off as fine
    run([cloud, "--eo", metric, "--images", imgdir, "--quarter-turns",
         "0", "--out", tmp_path / "scaled2.las"])
    assert "caution:" in capsys.readouterr().out


def test_colorize_cli_progress_reports_every_image(scene, tmp_path, capsys):
    cloud, eo, imgdir, _ = scene
    run([cloud, "--eo", eo, "--images", imgdir, "--quarter-turns", "0",
         "--out", tmp_path / "p.las"])
    text = capsys.readouterr().out
    # a thousand-image run is minutes of silent JPEG decoding otherwise
    assert "of 1 images" in text


def test_colorize_cli_refusals(scene, tmp_path):
    cloud, eo, imgdir, _ = scene
    with pytest.raises(SystemExit, match="new file"):
        run([cloud, "--eo", eo, "--images", imgdir, "--out", cloud])
    out = tmp_path / "exists.las"
    out.write_text("x")
    with pytest.raises(SystemExit, match="--force"):
        run([cloud, "--eo", eo, "--images", imgdir, "--out", out])
    # a units/CRS mismatch arrives as geometry: EO 2M units away
    far = tmp_path / "far.csv"
    far.write_text(f"100.0,0001.png,2000050.0,80.0,{H},0,0,-1,0,1,0\n")
    with pytest.raises(SystemExit, match="do not overlap"):
        run([cloud, "--eo", far, "--images", imgdir,
             "--out", tmp_path / "a.las"])
    # EO below the ground: a vertical datum or unit mismatch
    low = tmp_path / "low.csv"
    low.write_text("100.0,0001.png,50.0,80.0,-40.0,0,0,-1,0,1,0\n")
    with pytest.raises(SystemExit, match="BELOW"):
        run([cloud, "--eo", low, "--images", imgdir,
             "--out", tmp_path / "b.las"])
    # no calibration sidecar anywhere near the imagery
    bare = tmp_path / "bare"
    bare.mkdir()
    Image.fromarray(np.zeros((400, 600, 3), dtype=np.uint8)).save(
        bare / "0001.png")
    with pytest.raises(SystemExit, match="calibration"):
        run([cloud, "--eo", eo, "--images", bare,
             "--out", tmp_path / "c.las"])
    # a corrupt sidecar refuses as a named SystemExit, not a traceback
    broken = tmp_path / "broken"
    broken.mkdir()
    Image.fromarray(np.zeros((400, 600, 3), dtype=np.uint8)).save(
        broken / "0001.png")
    (broken / "0001.png.cal").write_text(json.dumps([{
        "CalibratedFocalLength": 1000.0, "ImageWidth": 600,
        "ImageHeight": 400, "CalibratedK1": None}]))
    with pytest.raises(SystemExit, match="CalibratedK1"):
        run([cloud, "--eo", eo, "--images", broken,
             "--out", tmp_path / "d.las"])
