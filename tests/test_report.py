import numpy as np
import pytest

from pyargus.qa import report
from tests.synthetic import linear_sbet, planar_strip, write_sbet

WEEK = 2385


def two_strip_points(offset=0.05):
    """Two overlapping planar strips as one points dict, strip 2 higher."""
    a = planar_strip(20000, (0, 60), (0, 30), plane=(0, 0, 100.0),
                     noise=0.02, seed=1)
    b = planar_strip(20000, (30, 90), (0, 30), plane=(0, 0, 100.0 + offset),
                     noise=0.02, seed=2)
    n_a, n_b = a["x"].size, b["x"].size
    sow = np.linspace(481100.0, 481300.0, n_a + n_b)
    return {
        "x": np.concatenate([a["x"], b["x"]]),
        "y": np.concatenate([a["y"], b["y"]]),
        "z": np.concatenate([a["z"], b["z"]]),
        "classification": np.full(n_a + n_b, 2, dtype=np.uint8),
        "point_source_id": np.concatenate(
            [np.ones(n_a, dtype=np.uint16), np.full(n_b, 2, dtype=np.uint16)]),
        "gps_time": sow + WEEK * 604800.0 - 1_000_000_000.0,
    }


def test_report_end_to_end(tmp_path):
    points = two_strip_points(offset=0.05)
    control = (["10", "FAR"],
               np.array([45.0, 500.0]),      # easting
               np.array([15.0, 500.0]),      # northing
               np.array([99.95, 99.0]))      # 10 sits 0.05 under strip 1
    traj = linear_sbet(n=1000, t0=481000.0, dt=0.5)
    summary = report.generate(
        points, tmp_path / "qa", title="Synthetic block",
        control=control, traj_time=traj["time"], dz_cell=4.0)

    assert summary["time_base"]["gps_week"] == WEEK
    assert summary["time_base"]["fraction_inside"] == 1.0

    assert [s["strip"] for s in summary["strips"]] == [1, 2]
    assert summary["ground_points"] == summary["points"]

    (pair,) = summary["strip_dz"]
    assert (pair["a"], pair["b"]) == (1, 2)
    assert abs(pair["median"] - 0.05) < 0.01

    c = summary["control"]
    # mark 10 is in the overlap: median over both strips sits between
    # +0.05 (strip 1) and +0.10 (strip 2) above its elevation.
    assert 0.04 < c["residuals"]["10"] < 0.11
    assert "FAR" in c["skipped"]
    assert c["n"] == 1

    out = tmp_path / "qa"
    for name in ("report.html", "density.png", "density.pgw",
                 "dz_1-2.png", "dz_1-2.pgw"):
        assert (out / name).exists(), name
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "Synthetic block" in html
    assert "data:image/png;base64," in html
    assert "skipped" in html


def test_report_without_control_or_sbet(tmp_path):
    points = two_strip_points()
    summary = report.generate(points, tmp_path / "qa", title="Bare")
    assert "control" not in summary and "time_base" not in summary
    assert (tmp_path / "qa" / "report.html").exists()


def test_cli_qa_report(tmp_path):
    laspy = pytest.importorskip("laspy")
    from pyargus import cli

    points = two_strip_points()
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    data.classification = points["classification"]
    data.point_source_id = points["point_source_id"]
    data.gps_time = points["gps_time"]
    cloud = tmp_path / "block.las"
    data.write(str(cloud))

    ctrl = tmp_path / "ctrl.csv"
    ctrl.write_text("10,15.0,45.0,99.95,MARK\n")  # P,N,E,Z
    traj = tmp_path / "traj.sbet"
    write_sbet(traj, linear_sbet(n=1000, t0=481000.0, dt=0.5))

    out = tmp_path / "qa"
    rc = cli.main(["qa-report", str(cloud), "--out", str(out),
                   "--control", str(ctrl), "--control-order", "pnez",
                   "--sbet", str(traj), "--dz-cell", "4.0"])
    assert rc == 0
    assert (out / "report.html").exists()

    with pytest.raises(SystemExit, match="control-order"):
        cli.main(["qa-report", str(cloud), "--out", str(out),
                  "--control", str(ctrl)])
