"""The GUI's testable parts: stage validation, the work seam, the
launcher trio, the preview array half. The window itself is not driven
here -- these are the pieces a window is made of, exercised without a
mainloop (the pyLynceus pattern, kept)."""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

tk = pytest.importorskip("tkinter")

import pyargus.gui as gui_module
from pyargus.gui import (Application, StageRunner, find_pylynceus,
                         preview_image, pylynceus_command)


@pytest.fixture()
def root():
    # Creating several Tk roots back to back occasionally fails on the
    # first try while the previous one is still tearing down; one
    # retry settles it, and a machine with no display still skips.
    import time

    window = None
    for _ in range(2):
        try:
            window = tk.Tk()
            break
        except tk.TclError:
            time.sleep(0.5)
    if window is None:
        pytest.skip("no display for Tk")
    window.withdraw()
    yield window
    window.destroy()


class _FakeRunner:
    """A stage's work run synchronously: log lines kept, never
    cancelled."""

    def __init__(self):
        self.logged = []
        self.progress = (0, 1)
        self.report = None
        self.products = []

    def log(self, text):
        self.logged.append(str(text))

    def cancelled(self):
        return False


# --- the launcher trio (no root needed) ---------------------------------

def _pylynceus_checkout(base, with_venv=True):
    home = base / "pyLynceus"
    (home / "pylynceus").mkdir(parents=True)
    (home / "pylynceus" / "gui.py").write_text("# marker\n")
    if with_venv:
        python = (home / ".venv" / "Scripts" / "python.exe"
                  if os.name == "nt" else home / ".venv" / "bin" / "python")
        python.parent.mkdir(parents=True)
        python.write_text("")
    return home


def test_find_pylynceus_honours_the_env_var(tmp_path, monkeypatch):
    home = _pylynceus_checkout(tmp_path)
    monkeypatch.setenv("PYLYNCEUS_HOME", str(home))
    assert find_pylynceus() == home


def test_find_pylynceus_anchors_on_the_exe_when_frozen(tmp_path,
                                                       monkeypatch):
    home = _pylynceus_checkout(tmp_path)
    fake_exe = tmp_path / "bundle" / "pyArgus.exe"
    fake_exe.parent.mkdir()
    fake_exe.write_text("")
    monkeypatch.delenv("PYLYNCEUS_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert find_pylynceus() == home


def test_pylynceus_command_uses_its_own_venv_never_ours(tmp_path):
    home = _pylynceus_checkout(tmp_path)
    command = pylynceus_command(home)
    assert str(home) in command[0]
    assert command[0] != sys.executable
    assert command[1:] == ["-m", "pylynceus", "gui"]


def test_pylynceus_command_without_a_venv_says_how_to_make_one(tmp_path):
    home = _pylynceus_checkout(tmp_path, with_venv=False)
    with pytest.raises(ValueError, match="uv venv"):
        pylynceus_command(home)


# --- the preview seam ---------------------------------------------------

def test_preview_image_decimates_but_never_upscales():
    big = np.zeros((3000, 1500, 4), dtype=np.uint8)
    small = preview_image(big, size=760)
    assert max(small.shape[:2]) <= 760
    tiny = np.zeros((10, 10, 4), dtype=np.uint8)
    assert preview_image(tiny, size=760).shape == (10, 10, 4)


# --- stage validation and the work seam ---------------------------------

@pytest.fixture()
def application(root):
    return Application(root)


def test_every_stage_refuses_without_a_cloud(application, monkeypatch):
    complaints = []
    monkeypatch.setattr(gui_module.messagebox, "showerror",
                        lambda title, text: complaints.append(text))
    for index in range(len(application.stages)):
        application.notebook.select(index)
        application.run()
    assert len(complaints) == len(application.stages)
    assert any("point cloud" in text for text in complaints)


def test_classify_refuses_writing_over_its_input(application, tmp_path):
    cloud = tmp_path / "cloud.las"
    cloud.write_text("")
    application.cloud_path.set(str(cloud))
    stage = application.stages[1]
    stage.out_path.set(str(cloud))
    with pytest.raises(ValueError, match="NEW file"):
        stage.prepare()


def test_contours_refuse_a_wrong_extension(application, tmp_path):
    cloud = tmp_path / "cloud.las"
    cloud.write_text("")
    application.cloud_path.set(str(cloud))
    stage = application.stages[3]
    stage.out_path.set(str(tmp_path / "contours.txt"))
    with pytest.raises(ValueError, match=".dxf or .geojson"):
        stage.prepare()


def test_align_requires_sbet_and_a_vertical_story(application, tmp_path):
    cloud = tmp_path / "cloud.las"
    cloud.write_text("")
    application.cloud_path.set(str(cloud))
    stage = application.stages[4]
    with pytest.raises(ValueError, match="SBET"):
        stage.prepare()
    sbet = tmp_path / "traj.out"
    sbet.write_text("")
    application.sbet_path.set(str(sbet))
    stage.vertical.set("")
    with pytest.raises(ValueError, match="vertical"):
        stage.prepare()


def test_classify_work_runs_and_feeds_downstream(application, tmp_path):
    laspy = pytest.importorskip("laspy")
    from tests.synthetic import classification_scene

    points, _ = classification_scene(seed=6)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    cloud = tmp_path / "scene.las"
    data.write(str(cloud))

    application.cloud_path.set(str(cloud))
    stage = application.stages[1]
    out = tmp_path / "classified.las"
    stage.out_path.set(str(out))
    stage.cell.set("1.0")
    stage.window.set("18.0")
    stage.threshold.set("0.5")

    runner = _FakeRunner()
    stage.prepare()(runner)
    assert out.exists()
    assert any("ground:" in line for line in runner.logged)
    assert runner.products == [("classified", out)]

    # the finished product fills EMPTY downstream override fields
    application.runner.products = runner.products
    application._adopt_products(application.runner)
    assert application.stages[2].cloud_override.get() == str(out)
    assert application.stages[3].cloud_override.get() == str(out)


def test_bad_numbers_name_their_field(application, tmp_path):
    cloud = tmp_path / "cloud.las"
    cloud.write_text("")
    application.cloud_path.set(str(cloud))
    stage = application.stages[1]
    stage.out_path.set(str(tmp_path / "out.las"))
    stage.window.set("wide")
    with pytest.raises(ValueError, match="Window"):
        stage.prepare()


def test_completion_fires_through_a_live_tick(application):
    import time

    def work(runner):
        runner.log("working")

    application.run_button.configure(state="disabled")
    application.stop_button.configure(state="normal")
    application.runner.start(work)
    application._stage_open = True
    deadline = time.time() + 5.0
    while application.runner.running and time.time() < deadline:
        time.sleep(0.02)
    assert not application.runner.running
    application._tick()
    assert application._stage_open is False


def test_preview_draws_even_when_the_report_lands_after_the_last_log(
        application, monkeypatch):
    """The review panel proved the old 'drained' gate never drew on a
    real cloud: the worker logs its last line, then computes the
    preview for seconds, then sets report -- and no later tick drains.
    The draw must fire on report identity, not on log traffic."""
    drawn = []
    monkeypatch.setattr(application, "_draw_preview",
                        lambda rgba: drawn.append(rgba))
    application.runner.lines.put("report: done")
    application._tick()                       # drains; report still None
    assert drawn == []
    late = np.zeros((4, 4, 4), dtype=np.uint8)
    application.runner.report = late
    application._tick()                       # nothing drained; must draw
    assert len(drawn) == 1 and drawn[0] is late
    application._tick()                       # same report: no redraw churn
    assert len(drawn) == 1


def test_stop_prevents_every_stages_write(application, tmp_path):
    """After Stop, nothing lands on disk: the shared gate, exercised
    through the DTM and Contour stages' real work closures."""
    laspy = pytest.importorskip("laspy")
    from tests.synthetic import classification_scene

    points, truth = classification_scene(seed=7)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    data.classification = np.where(truth, 2, 1).astype(np.uint8)
    cloud = tmp_path / "scene.las"
    data.write(str(cloud))
    application.cloud_path.set(str(cloud))

    class _CancelledRunner(_FakeRunner):
        def cancelled(self):
            return True

    dtm_stage = application.stages[2]
    dtm_out = tmp_path / "dtm.asc"
    dtm_stage.out_path.set(str(dtm_out))
    dtm_stage.prepare()(_CancelledRunner())
    assert not dtm_out.exists()

    contour_stage = application.stages[3]
    contour_out = tmp_path / "contours.dxf"
    contour_stage.out_path.set(str(contour_out))
    contour_stage.prepare()(_CancelledRunner())
    assert not contour_out.exists()


def test_outputs_that_already_exist_are_refused(application, tmp_path):
    cloud = tmp_path / "cloud.las"
    cloud.write_text("")
    application.cloud_path.set(str(cloud))
    existing = tmp_path / "already.las"
    existing.write_text("")
    stage = application.stages[1]
    stage.out_path.set(str(existing))
    with pytest.raises(ValueError, match="already exists"):
        stage.prepare()
    sbet = tmp_path / "traj.out"
    sbet.write_text("")
    application.sbet_path.set(str(sbet))
    align = application.stages[4]
    align.write_path.set(str(existing))
    with pytest.raises(ValueError, match="already exists"):
        align.prepare()


def test_gui_align_solves_with_the_cli_defaults():
    """A GUI run and a CLI run on the same data must answer alike; the
    panel caught min_points=5 typed where the CLI says 6."""
    from pyargus.cli import build_parser

    args = build_parser().parse_args(
        ["align", "cloud.las", "--sbet", "traj.out"])
    assert gui_module.ALIGN_CELL == args.cell
    assert gui_module.ALIGN_MIN_POINTS == args.min_points


# --- the Colorize stage ----------------------------------------------

def _colorize_scene(tmp_path):
    """A checkerboard world, one synthetic camera, and a pf6 cloud --
    the same fixture shape the CLI colorize test uses."""
    import json

    import laspy
    import numpy as np
    from PIL import Image

    from tests.test_colorize import checker, render_nadir_image, simple_camera

    cam = simple_camera(width=600, height=400)
    origin = np.array([50.0, 80.0, 100.0])
    imgdir = tmp_path / "imagery"
    imgdir.mkdir()
    Image.fromarray(render_nadir_image(cam, origin, checker)).save(
        imgdir / "0001.png")
    (imgdir / "0001.png.cal").write_text(json.dumps([{
        "CalibratedFocalLength": cam.focal_mm / cam.pixel_mm,
        "ImageWidth": cam.width_px, "ImageHeight": cam.height_px}]))

    eo = tmp_path / "eo.csv"
    eo.write_text(
        "Timestamp, Filename, Origin, , , Direction, , , Up, , \n"
        f"100.0,0001.png,50.0,80.0,100.0,0.0,0.0,-1.0,0.0,1.0,0.0\n")

    gx, gy = np.meshgrid(np.arange(35.0, 76.0, 10.0),
                         np.arange(65.0, 96.0, 10.0))
    xyz = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    cloud = tmp_path / "cloud.las"
    data.write(str(cloud))
    return cloud, eo, imgdir, xyz


def _colorize_stage(application):
    for stage in application.stages:
        if type(stage).__name__ == "ColorizeStage":
            return stage
    raise AssertionError("no ColorizeStage registered")


def test_colorize_defaults_come_from_the_cli(application):
    """The Phase-7 panel found the GUI's alignment settings had drifted
    from the CLI's. These are READ from the parser, so a difference can
    only ever be deliberate."""
    from pyargus.cli import build_parser

    args = build_parser().parse_args(
        ["colorize", "c.las", "--eo", "e.csv", "--images", "i",
         "--out", "o.las"])
    stage = _colorize_stage(application)
    assert int(stage.quarter_turns.get()) == args.quarter_turns
    assert float(stage.occlusion_tol.get()) == args.occlusion_tol
    assert float(stage.min_coverage.get()) == args.min_coverage


def test_colorize_names_each_missing_input(application, tmp_path):
    stage = _colorize_stage(application)
    cloud, eo, imgdir, _ = _colorize_scene(tmp_path)
    application.cloud_path.set(str(cloud))
    stage.out_path.set(str(tmp_path / "rgb.las"))

    with pytest.raises(ValueError, match="EO csv"):
        stage.prepare()
    stage.eo_path.set(str(tmp_path / "nope.csv"))
    with pytest.raises(ValueError, match="no such EO csv"):
        stage.prepare()
    stage.eo_path.set(str(eo))
    with pytest.raises(ValueError, match="imagery folder"):
        stage.prepare()
    stage.images_dir.set(str(tmp_path / "nowhere"))
    with pytest.raises(ValueError, match="no such imagery folder"):
        stage.prepare()
    stage.images_dir.set(str(imgdir))
    stage.quarter_turns.set("sideways")
    with pytest.raises(ValueError, match="Quarter turns"):
        stage.prepare()
    stage.quarter_turns.set("0")
    assert callable(stage.prepare())


def test_colorize_refuses_writing_over_its_input(application, tmp_path):
    stage = _colorize_stage(application)
    cloud, eo, imgdir, _ = _colorize_scene(tmp_path)
    application.cloud_path.set(str(cloud))
    stage.eo_path.set(str(eo))
    stage.images_dir.set(str(imgdir))
    stage.out_path.set(str(cloud))
    with pytest.raises(ValueError, match="NEW file"):
        stage.prepare()
    existing = tmp_path / "taken.las"
    existing.write_text("")
    stage.out_path.set(str(existing))
    with pytest.raises(ValueError, match="already exists"):
        stage.prepare()


def test_colorize_work_paints_the_cloud_and_feeds_downstream(application,
                                                             tmp_path):
    import laspy
    import numpy as np

    from tests.test_colorize import checker

    stage = _colorize_stage(application)
    cloud, eo, imgdir, xyz = _colorize_scene(tmp_path)
    out = tmp_path / "rgb.las"
    application.cloud_path.set(str(cloud))
    stage.eo_path.set(str(eo))
    stage.images_dir.set(str(imgdir))
    stage.out_path.set(str(out))
    stage.quarter_turns.set("0")

    work = stage.prepare()
    runner = _FakeRunner()
    work(runner)

    assert out.is_file()
    result = laspy.read(str(out))
    assert result.header.point_format.id == 7        # pf6 carries no RGB
    want = checker(xyz[:, 0], xyz[:, 1]).astype(np.uint16) << 8
    got = np.column_stack([result.red, result.green, result.blue])
    assert np.array_equal(got, want)
    assert any("colored:" in line for line in runner.logged)
    # the coloured cloud is offered to the stages downstream
    assert ("classified", out) in runner.products


def test_colorize_writes_nothing_after_stop(application, tmp_path):
    stage = _colorize_stage(application)
    cloud, eo, imgdir, _ = _colorize_scene(tmp_path)
    out = tmp_path / "rgb.las"
    application.cloud_path.set(str(cloud))
    stage.eo_path.set(str(eo))
    stage.images_dir.set(str(imgdir))
    stage.out_path.set(str(out))
    stage.quarter_turns.set("0")

    work = stage.prepare()
    runner = _FakeRunner()
    runner.cancelled = lambda: True          # Stop pressed mid-run
    work(runner)
    assert not out.exists()
    assert runner.products == []


def test_colorize_passes_every_field_through_to_the_job(application,
                                                        tmp_path,
                                                        monkeypatch):
    """Each widget the stage collects must arrive at colorize_cloud.
    Asserting only the happy-path colours leaves most of the plumbing
    free to be dropped on the floor: the cloud override, the
    calibration, the quarter turns, the tolerances."""
    from pyargus.imagery import job as job_mod

    stage = _colorize_stage(application)
    cloud, eo, imgdir, _ = _colorize_scene(tmp_path)
    other = tmp_path / "override.las"
    other.write_bytes(cloud.read_bytes())
    cal = imgdir / "0001.png.cal"
    out = tmp_path / "rgb.las"

    application.cloud_path.set(str(tmp_path / "ignored.las"))
    stage.cloud_override.set(str(other))
    stage.eo_path.set(str(eo))
    stage.images_dir.set(str(imgdir))
    stage.cal_path.set(str(cal))
    stage.out_path.set(str(out))
    stage.quarter_turns.set("2")
    stage.occlusion_tol.set("4.5")
    stage.min_coverage.set("1.5")

    seen = {}

    def spy(cloud_arg, eo_arg, images_arg, out_arg, **kwargs):
        seen.update(cloud=cloud_arg, eo=eo_arg, images=images_arg,
                    out=out_arg, **kwargs)
        return {"n_colored": 1, "n_points": 1, "pct_colored": 100.0}

    monkeypatch.setattr(job_mod, "colorize_cloud", spy)
    stage.prepare()(_FakeRunner())

    assert Path(seen["cloud"]) == other          # the override, not the panel
    assert Path(seen["eo"]) == eo
    assert Path(seen["images"]) == imgdir
    assert Path(seen["out"]) == out
    assert Path(seen["cal"]) == cal
    assert seen["quarter_turns"] == 2
    assert seen["occlusion_tol"] == 4.5
    assert seen["min_coverage"] == 1.5
    assert callable(seen["should_stop"]) and callable(seen["log"])


def test_colorize_offers_nothing_downstream_when_no_file_appears(
        application, tmp_path, monkeypatch):
    """products must follow the FILE, not the intention."""
    from pyargus.imagery import job as job_mod

    stage = _colorize_stage(application)
    cloud, eo, imgdir, _ = _colorize_scene(tmp_path)
    out = tmp_path / "never.las"
    application.cloud_path.set(str(cloud))
    stage.eo_path.set(str(eo))
    stage.images_dir.set(str(imgdir))
    stage.out_path.set(str(out))

    monkeypatch.setattr(job_mod, "colorize_cloud",
                        lambda *a, **k: {"n_colored": 0, "n_points": 1})
    runner = _FakeRunner()
    stage.prepare()(runner)
    assert runner.products == []
