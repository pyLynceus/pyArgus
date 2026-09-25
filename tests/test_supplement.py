"""Surveyed points joining a surface, and the measurement record.

Two things the lidar cannot do arrive in the same shape: the field
shots surveyors take under canopy where no pulse reaches the ground,
and the points an operator measures in stereo. Until now neither had
any route into a surface on any path.

The design question these pin is what a shot should DO. Joining it as
one more return is the tempting answer and the wrong one, and the test
below makes the reason concrete: a cell holding two hundred lidar
returns and one surveyed shot would move by half a percent of the
difference, so the surveyor's trip would change the surface by nothing
and nobody would see that it had not.
"""

import json

import numpy as np
import pytest

from pyargus import measurements as meas
from pyargus.surfaces import dtm as dtm_mod
from pyargus.surfaces import supplement


def a_surface(cell=3.0):
    """A sloping lidar surface, densely sampled, like real ground."""
    rng = np.random.default_rng(11)
    n = 60_000
    x = 1_000.0 + rng.uniform(0, 120, n)
    y = 2_000.0 + rng.uniform(0, 90, n)
    z = 100.0 + 0.04 * (x - 1_000.0) + 0.01 * (y - 2_000.0)
    grid, xe, ye = dtm_mod.dtm_grid(x, y, z, cell, max_fill=0)
    return grid, xe, ye


def test_a_surveyed_shot_owns_its_cell_rather_than_being_averaged_away():
    """The whole design, as one number.

    Joining a shot to the returns would move its cell by the shot's
    share of the cell's points. Here that is under one percent, which
    is to say the surveyor's work would vanish.
    """
    grid, xe, ye = a_surface()
    # a cell with plenty of lidar in it
    col, row = 20, 15
    x = np.array([0.5 * (xe[col] + xe[col + 1])])
    y = np.array([0.5 * (ye[row] + ye[row + 1])])
    was = float(grid[row, col])
    shot = np.array([was + 2.5])

    out, report = supplement.apply_points(grid, xe, ye, x, y, shot,
                                          log=lambda *_: None)
    assert out[row, col] == pytest.approx(shot[0])
    assert report["cells_changed"] == 1
    assert report["inside"] == 1
    assert report["largest_shift"] == pytest.approx(2.5, abs=1e-6)

    # the alternative, for the record: averaged in among the returns it
    # would have moved the cell by almost nothing
    per_cell = 60_000 / ((grid.shape[0]) * (grid.shape[1]))
    averaged = (was * per_cell + shot[0]) / (per_cell + 1)
    assert abs(averaged - was) < 0.1, (
        f"the fixture is not dense enough to show the point: averaging "
        f"moves the cell {abs(averaged-was):.3f} ft")

    # and nothing else moved
    elsewhere = np.isfinite(grid) & np.isfinite(out)
    elsewhere[row, col] = False
    assert np.array_equal(grid[elsewhere], out[elsewhere])


def test_a_shot_fills_a_cell_the_lidar_never_saw():
    """The canopy case, which is why the surveyors went out."""
    grid, xe, ye = a_surface()
    grid[10:14, 10:14] = np.nan                 # a hole under canopy
    x = np.array([0.5 * (xe[11] + xe[12])])
    y = np.array([0.5 * (ye[11] + ye[12])])
    out, report = supplement.apply_points(grid, xe, ye, x, y,
                                          np.array([101.25]),
                                          log=lambda *_: None)
    assert report["cells_created"] == 1
    assert out[11, 11] == pytest.approx(101.25)
    assert np.isnan(out[10, 10]), "only the cell that was shot should fill"


def test_several_shots_in_one_cell_are_averaged_with_each_other():
    grid, xe, ye = a_surface()
    col, row = 20, 15
    cx = 0.5 * (xe[col] + xe[col + 1])
    cy = 0.5 * (ye[row] + ye[row + 1])
    x = np.array([cx - 0.5, cx, cx + 0.5])
    y = np.array([cy, cy + 0.4, cy - 0.3])
    z = np.array([120.0, 121.0, 122.0])
    out, report = supplement.apply_points(grid, xe, ye, x, y, z,
                                          log=lambda *_: None)
    assert report["cells_changed"] == 1
    assert out[row, col] == pytest.approx(121.0)


def test_points_that_miss_the_site_are_reported_not_silently_dropped():
    grid, xe, ye = a_surface()
    inside_x = np.array([0.5 * (xe[5] + xe[6])])
    inside_y = np.array([0.5 * (ye[5] + ye[6])])
    x = np.concatenate([inside_x, [9_000.0, 9_100.0]])
    y = np.concatenate([inside_y, [9_000.0, 9_100.0]])
    z = np.array([101.0, 101.0, 101.0])
    said = []
    _, report = supplement.apply_points(grid, xe, ye, x, y, z,
                                        log=said.append)
    assert report["outside"] == 2 and report["inside"] == 1
    assert any("outside" in line for line in said)


def test_a_file_that_lands_entirely_elsewhere_refuses():
    """A transposed or wrongly projected file changes nothing, and
    silence is indistinguishable from success."""
    grid, xe, ye = a_surface()
    with pytest.raises(ValueError, match="column order"):
        supplement.apply_points(grid, xe, ye, np.array([9_000.0]),
                                np.array([9_000.0]), np.array([100.0]),
                                log=lambda *_: None)


def test_a_shot_without_an_elevation_refuses():
    grid, xe, ye = a_surface()
    x = np.array([0.5 * (xe[5] + xe[6])])
    y = np.array([0.5 * (ye[5] + ye[6])])
    with pytest.raises(ValueError, match="without a height"):
        supplement.apply_points(grid, xe, ye, x, y, np.array([np.nan]),
                                log=lambda *_: None)


def test_supplementary_points_are_read_by_the_control_reader(tmp_path):
    """One ingest for field shots and stereo measurements both."""
    path = tmp_path / "shots.csv"
    path.write_text("S1,2000.5,1000.5,101.25\nS2,2010.0,1020.0,102.5\n",
                    encoding="utf-8")
    x, y, z = supplement.read_points([path], "pnez", log=lambda *_: None)
    assert np.allclose(x, [1000.5, 1020.0])     # easting, second column
    assert np.allclose(y, [2000.5, 2010.0])
    assert np.allclose(z, [101.25, 102.5])
    # and the order is never guessed
    x2, y2, _ = supplement.read_points([path], "penz", log=lambda *_: None)
    assert np.allclose(x2, [2000.5, 2010.0])


# --- the measurement record -------------------------------------------

def a_measurement(point_id="M1", angle=25.0):
    return meas.Measurement(
        point_id=point_id, easting=2_600_250.0, northing=1_200_250.0,
        elevation=100.25,
        observations=[meas.Observation("N_0101.JPG", 500.0, 400.0, 0.94),
                      meas.Observation("N_0109.JPG", 650.0, 400.0, 0.92)],
        max_angle_deg=angle, residual=0.03, height_per_pixel=0.15,
        disparity=150.0, description="stereo")


def test_a_measurement_round_trips_with_its_evidence(tmp_path):
    path = tmp_path / "measured.csv"
    meas.write(path, [a_measurement("M1"), a_measurement("M2")],
               log=lambda *_: None)
    back, order = meas.read(path)
    assert order == "pnez"
    assert [m.point_id for m in back] == ["M1", "M2"]
    assert back[0].observations[0].frame == "N_0101.JPG"
    assert back[0].max_angle_deg == pytest.approx(25.0)
    assert back[0].strength == "good"


def test_the_csv_is_the_same_shape_the_surface_ingest_takes(tmp_path):
    """The point of writing it this way: one file, two jobs."""
    path = tmp_path / "measured.csv"
    meas.write(path, [a_measurement("M1")], log=lambda *_: None)
    body = path.read_text(encoding="utf-8").splitlines()
    assert body[0] == meas.CSV_HEADER
    x, y, z = supplement.read_points([path], "pnez", log=lambda *_: None)
    assert x[0] == pytest.approx(2_600_250.0)
    assert z[0] == pytest.approx(100.25)


def test_a_measurement_that_cannot_say_where_it_came_from_is_refused():
    with pytest.raises(ValueError, match="at least two"):
        meas.Measurement(point_id="M1", easting=1.0, northing=2.0,
                         elevation=3.0,
                         observations=[meas.Observation("a.jpg", 1, 2)],
                         max_angle_deg=20.0, residual=0.1)
    with pytest.raises(ValueError, match="no ray geometry"):
        meas.Measurement(point_id="M1", easting=1.0, northing=2.0,
                         elevation=3.0,
                         observations=[meas.Observation("a.jpg", 1, 2),
                                       meas.Observation("b.jpg", 3, 4)],
                         max_angle_deg=0.0, residual=0.1)


def test_the_geometry_is_readable_at_a_glance():
    assert a_measurement(angle=4.0).strength == "weak"
    assert a_measurement(angle=11.0).strength == "marginal"
    assert a_measurement(angle=27.0).strength == "good"


def test_writing_refuses_an_empty_set_and_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="nothing to write"):
        meas.write(tmp_path / "x.csv", [], log=lambda *_: None)
    with pytest.raises(ValueError, match="appears twice"):
        meas.write(tmp_path / "x.csv", [a_measurement("M1"),
                                        a_measurement("M1")],
                   log=lambda *_: None)


def test_a_csv_without_its_evidence_is_refused_by_the_reader(tmp_path):
    path = tmp_path / "measured.csv"
    meas.write(path, [a_measurement("M1")], log=lambda *_: None)
    path.with_name(path.name + ".measurements.json").unlink()
    with pytest.raises(ValueError, match="no evidence sidecar"):
        meas.read(path)


def test_the_sidecar_states_the_column_order_it_was_written_in(tmp_path):
    path = tmp_path / "measured.csv"
    meas.write(path, [a_measurement("M1")], order="penz",
               log=lambda *_: None)
    body = json.loads(
        path.with_name(path.name + ".measurements.json").read_text())
    assert body["order"] == "penz"
    assert path.read_text(encoding="utf-8").splitlines()[0].startswith(
        "id,easting")
    _, order = meas.read(path)
    assert order == "penz"


def test_a_header_row_is_skipped_but_a_damaged_row_is_not(tmp_path):
    """A real client GCP file arrived with a header, and it had to be
    hand-stripped before the suite would read it.

    A data row always has numbers in its coordinate columns, so a FIRST
    row that does not is a header and nothing else. A later one is a
    damaged row, and skipping that would drop a control point in
    silence.
    """
    from pyargus.formats import control as control_mod

    headed = tmp_path / "headed.csv"
    headed.write_text("id,north,east,elevation\n"
                      "101,1200100.000,2600200.000,100.000\n"
                      "102,1200150.000,2600250.000,101.000\n",
                      encoding="utf-8")
    ids, east, north, elev = control_mod.read_control_csv(headed, "pnez")
    assert ids == ["101", "102"]
    assert north[0] == pytest.approx(1200100.000)
    assert east[0] == pytest.approx(2600200.000)

    damaged = tmp_path / "damaged.csv"
    damaged.write_text("101,1200100.000,2600200.000,100.000\n"
                       "102,,2600250.000,101.000\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        control_mod.read_control_csv(damaged, "pnez")


def test_the_dtm_command_takes_surveyed_points(tmp_path):
    """The whole point: it has to be reachable from the command line,
    or the surveyors' shots still have nowhere to go."""
    import numpy as np
    from pyargus import cli
    from pyargus.surfaces import dtm as dtm_mod

    laspy = pytest.importorskip("laspy")
    rng = np.random.default_rng(5)
    n = 20_000
    x = 1_000.0 + rng.uniform(0, 60, n)
    y = 2_000.0 + rng.uniform(0, 60, n)
    z = np.full(n, 100.0)
    header = laspy.LasHeader(version="1.4", point_format=6)
    header.scales = np.array([0.001] * 3)
    header.offsets = np.array([1_000.0, 2_000.0, 100.0])
    data = laspy.LasData(header)
    data.x, data.y, data.z = x, y, z
    data.classification = np.full(n, 2, dtype=np.uint8)
    cloud = tmp_path / "ground.las"
    data.write(str(cloud))

    shots = tmp_path / "shots.csv"
    shots.write_text("id,northing,easting,elevation\n"
                     "S1,2030.0,1030.0,140.0\n", encoding="utf-8")

    plain = tmp_path / "plain.asc"
    assert cli.main(["dtm", str(cloud), "--out", str(plain), "--cell", "3",
                     "--max-fill", "0"]) == 0
    with_shot = tmp_path / "with.asc"
    assert cli.main(["dtm", str(cloud), "--out", str(with_shot), "--cell", "3",
                     "--max-fill", "0", "--add-points", str(shots),
                     "--points-order", "pnez"]) == 0

    def read(path):
        rows = path.read_text(encoding="utf-8").splitlines()
        return np.array([[float(v) for v in r.split()] for r in rows[6:]])

    a, b = read(plain), read(with_shot)
    moved = np.abs(a - b) > 1e-6
    assert moved.sum() == 1, f"{moved.sum()} cells changed, expected 1"
    assert b[moved][0] == pytest.approx(140.0)


def test_the_dtm_command_will_not_guess_the_column_order(tmp_path):
    from pyargus import cli
    shots = tmp_path / "shots.csv"
    shots.write_text("S1,2030.0,1030.0,140.0\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="never guessed"):
        cli.main(["dtm", "nothing.las", "--out", str(tmp_path / "o.asc"),
                  "--add-points", str(shots)])
