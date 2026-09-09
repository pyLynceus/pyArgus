"""The decomposition that exonerated the SH 151 lidar, pinned: strip-
dependent misses and position-locked misses must read differently."""

import numpy as np
import pytest

from pyargus.qa import control_by_strip as cbs


def synthetic_gather(strip_offsets, mark_positions, slope_x=0.1, seed=1,
                     n_per=120):
    """Points around each mark from each strip, on a sloped plane with
    each strip's own vertical offset."""
    rng = np.random.default_rng(seed)
    gathered = {}
    for strip, offset in strip_offsets.items():
        marks = {}
        for k, (e, n) in enumerate(mark_positions):
            x = e + rng.uniform(-3, 3, n_per)
            y = n + rng.uniform(-3, 3, n_per)
            z = 100.0 + slope_x * x + offset + rng.normal(0, 0.02, n_per)
            marks[k] = (x, y, z)
        gathered[strip] = marks
    return gathered


MARKS = [(10.0, 0.0), (40.0, 5.0), (80.0, -5.0), (120.0, 3.0)]


def known_z(positions, slope_x=0.1):
    return np.array([100.0 + slope_x * e for e, _ in positions])


def test_strip_dependent_misses_read_as_per_strip_bias():
    gathered = synthetic_gather({"A": 0.0, "B": 0.20}, MARKS)
    ids = [f"m{k}" for k in range(len(MARKS))]
    e = np.array([p[0] for p in MARKS])
    n = np.array([p[1] for p in MARKS])
    deco = cbs.decompose(gathered, ids, e, n, known_z(MARKS))
    per_strip = deco.per_strip()
    assert abs(per_strip["A"]["median"]) < 0.02
    assert abs(per_strip["B"]["median"] - 0.20) < 0.02
    for stats in deco.per_mark().values():
        assert stats["spread"] > 0.15      # strips disagree at the mark


def test_position_locked_misses_read_as_agreement():
    # every strip carries the same wrong value at mark 1 (the survey or
    # a pre-applied warp), and is clean elsewhere
    gathered = synthetic_gather({"A": 0.0, "B": 0.0}, MARKS)
    ids = [f"m{k}" for k in range(len(MARKS))]
    e = np.array([p[0] for p in MARKS])
    n = np.array([p[1] for p in MARKS])
    kz = known_z(MARKS)
    kz[1] -= 0.30                          # the mark is recorded 0.30 low
    deco = cbs.decompose(gathered, ids, e, n, kz)
    stats = deco.per_mark()["m1"]
    assert stats["n_strips"] == 2
    assert stats["spread"] < 0.03          # strips agree with each other
    assert abs(stats["mean_dz"] - 0.30) < 0.03
    assert abs(stats["dz_plane"] - 0.30) < 0.03


def test_plane_dz_is_grade_corrected():
    # 10% slope: a naive median inside a 3-unit window carries slope
    # noise, the plane evaluated AT the mark does not
    gathered = synthetic_gather({"A": 0.25}, MARKS[:1], slope_x=0.1)
    deco = cbs.decompose(gathered, ["m0"], np.array([MARKS[0][0]]),
                         np.array([MARKS[0][1]]), known_z(MARKS[:1]))
    cell = deco.cells[0]
    assert abs(cell.dz_plane - 0.25) < 0.02
    assert 0.08 < cell.slope < 0.12        # and it reports the grade


def test_empty_gather_refuses():
    with pytest.raises(ValueError, match="no strip"):
        cbs.decompose({}, [], np.array([]), np.array([]), np.array([]))


def test_gather_streams_and_labels_by_file_or_psid(tmp_path):
    laspy = pytest.importorskip("laspy")
    rng = np.random.default_rng(3)

    def write_cloud(path, psids):
        n = 4000
        header = laspy.LasHeader(point_format=6, version="1.4")
        header.scales = (0.001, 0.001, 0.001)
        data = laspy.LasData(header)
        data.x = rng.uniform(0, 50, n)
        data.y = rng.uniform(0, 50, n)
        data.z = np.full(n, 100.0)
        data.point_source_id = np.where(np.arange(n) % 2 == 0, psids[0],
                                        psids[-1]).astype(np.uint16)
        data.classification = np.full(n, 2, dtype=np.uint8)
        data.write(str(path))
        return path

    # one multi-strip file: labels are the psids
    both = write_cloud(tmp_path / "both.las", (7, 9))
    gathered = cbs.gather_near_marks([both], [25.0], [25.0], radius=3.0)
    assert set(gathered) == {"7", "9"}
    # two files: labels are the stems
    a = write_cloud(tmp_path / "line_a.las", (7, 7))
    b = write_cloud(tmp_path / "line_b.las", (9, 9))
    gathered = cbs.gather_near_marks([a, b], [25.0], [25.0], radius=3.0)
    assert set(gathered) == {"line_a", "line_b"}
    # class filter empties a class-2 cloud when asked for class 5
    gathered = cbs.gather_near_marks([a], [25.0], [25.0], radius=3.0,
                                     ground_class=5)
    assert not gathered


def test_cli_control_by_strip(tmp_path):
    laspy = pytest.importorskip("laspy")
    from pyargus import cli

    rng = np.random.default_rng(4)
    paths = []
    for stem, offset in (("s1", 0.0), ("s2", 0.15)):
        n = 5000
        header = laspy.LasHeader(point_format=6, version="1.4")
        header.scales = (0.001, 0.001, 0.001)
        data = laspy.LasData(header)
        data.x = rng.uniform(0, 60, n)
        data.y = rng.uniform(0, 20, n)
        data.z = 100.0 + offset + rng.normal(0, 0.02, n)
        data.point_source_id = np.full(n, 1, dtype=np.uint16)
        data.classification = np.ones(n, dtype=np.uint8)
        path = tmp_path / f"{stem}.las"
        data.write(str(path))
        paths.append(str(path))

    ctrl = tmp_path / "marks.csv"
    ctrl.write_text("1,10.0,30.0,100.0,MK\n2,10.0,50.0,100.0,MK\n")  # P,N,E,Z
    rc = cli.main(["control-by-strip", *paths, "--control", str(ctrl),
                   "--control-order", "pnez"])
    assert rc == 0
    with pytest.raises(SystemExit, match="control-order"):
        cli.main(["control-by-strip", *paths, "--control", str(ctrl)])
