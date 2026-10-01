"""Five defects in the desktop GUI that came before any layout work.

Found by reading the code against the operator's workflows (the KLT
layout review, 2026-09-30), then widened by an adversarial review of the
fixes. Each test here fails against the code as it stood before its fix,
except the one whose docstring says it is a guard.
"""

from pathlib import Path

import pytest

laspy = pytest.importorskip("laspy")

from tests.test_gui import application, root  # noqa: E402,F401  (fixtures)
from tests.test_review_workspace import cloud, wait  # noqa: E402


def pump(app, workspace):
    """Let queued Tk events run -- the file tree's selection events are
    delivered after the code that caused them returns -- and let any
    viewer load finish."""
    for _ in range(25):
        app.root.update()
    if workspace.viewer.busy:
        wait(app.root, workspace.viewer)
    for _ in range(10):
        app.root.update()


def resolved(path):
    return str(Path(path).resolve())


def row_of(workspace, path):
    return next(str(i) for i, layer in enumerate(workspace.tracker.data["layers"])
                if layer["path"] == resolved(path))


def task_inputs(app):
    """Every place the task input lives: the app's cloud and each stage's
    own override."""
    return {app.cloud_path.get()} | {
        s.cloud_override.get() for s in app.stages if hasattr(s, "cloud_override")}


# ------------------------------------------------ F1: the task input reverted


def test_a_classified_version_stays_the_task_input_after_activation(
        application, tmp_path):
    """The defect: Classify made its output the active version, then the
    file tree was rebuilt with the ORIGINAL row still selected, and the
    selection event that rebuild queued put the original back as the task
    input -- so the next DTM ran on the unclassified cloud."""
    app = application
    w = app.workspace
    original, classified = tmp_path / "line.las", tmp_path / "line_classified.las"
    cloud(original)
    cloud(classified)
    w.project_panel.clouds = [resolved(original)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, original))
    pump(app, w)
    assert task_inputs(app) == {resolved(original)}      # a click sets it

    # what complete() does after a successful Classify
    w.tracker.register_cloud_result(resolved(original), resolved(classified), "job")
    w.activate_cloud_version(resolved(classified))
    w.refresh_layers()
    pump(app, w)
    assert task_inputs(app) == {resolved(classified)}
    # and the tree shows it: the activated version is the selected row
    assert [w.tracker.data["layers"][int(i)]["path"]
            for i in w.layer_tree.selection()] == [resolved(classified)]


def test_rebuilding_the_file_tree_never_changes_the_task_input(
        application, tmp_path):
    """Any programmatic change of input (a batch moving to its next
    flight, say) survives the next rebuild of the tree."""
    app = application
    w = app.workspace
    a, b = tmp_path / "a.las", tmp_path / "b.las"
    cloud(a)
    cloud(b)
    w.project_panel.clouds = [resolved(a), resolved(b)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    w.set_active_cloud(resolved(b))
    w.refresh_layers()
    pump(app, w)
    assert task_inputs(app) == {resolved(b)}
    # and the tree shows it: left on the old row, it showed a cloud that was
    # not the input, and clicking that row to choose it was ignored
    assert [w.tracker.data["layers"][int(i)]["path"]
            for i in w.layer_tree.selection()] == [resolved(b)]
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    assert task_inputs(app) == {resolved(a)}


def test_a_task_input_outside_the_file_tree_survives_a_rebuild(
        application, tmp_path):
    """A cloud picked in the Data panel need not be in the file tree. The
    tree's own selected cloud stayed selected through a rebuild, and its
    select event replaced the picked cloud as the task input."""
    app = application
    w = app.workspace
    a, elsewhere = tmp_path / "a.las", tmp_path / "elsewhere.las"
    cloud(a)
    cloud(elsewhere)
    w.project_panel.clouds = [resolved(a)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    w.set_active_cloud(resolved(elsewhere))
    w.refresh_layers()
    pump(app, w)
    assert task_inputs(app) == {resolved(elsewhere)}
    assert not w.layer_tree.selection()


def test_a_rebuild_keeps_a_cloud_typed_into_a_stage(application, tmp_path):
    """Each rebuild's select events re-ran set_active_cloud on the selected
    row, which reset every stage's 'Classified cloud (blank = main)' field:
    a classified cloud typed there was replaced by the unclassified input,
    and the DTM ran on that."""
    app = application
    w = app.workspace
    a, typed = tmp_path / "a.las", tmp_path / "a_classified.las"
    cloud(a)
    cloud(typed)
    w.project_panel.clouds = [resolved(a)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    dtm = stage_of(app, "DtmStage")
    dtm.cloud_override.set(resolved(typed))
    w.refresh_layers()
    pump(app, w)
    assert dtm.cloud_override.get() == resolved(typed)


def test_a_click_still_on_its_way_survives_a_rebuild(application, tmp_path):
    """A click selects its row at once but its select event is queued; a
    rebuild that runs first (a poll tick) must not put the old input's row
    back before the event arrives."""
    app = application
    w = app.workspace
    a, b = tmp_path / "a.las", tmp_path / "b.las"
    cloud(a)
    cloud(b)
    w.project_panel.clouds = [resolved(a), resolved(b)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    w.layer_tree.selection_set(row_of(w, b))      # the click; event queued
    w.refresh_layers()                            # a tick rebuilds first
    pump(app, w)
    assert task_inputs(app) == {resolved(b)}


def test_a_cloud_chosen_while_classify_runs_stays_the_task_input(
        application, tmp_path):
    """Classify's result became the task input even when the operator had
    chosen another flight during the run; the next DTM then surfaced the
    classified flight, not the one chosen."""
    from types import SimpleNamespace

    app = application
    w = app.workspace
    a, b, a_classified = (tmp_path / n for n in ("a.las", "b.las", "a_ground.las"))
    for path in (a, b, a_classified):
        cloud(path)
    w.project_panel.clouds = [resolved(a), resolved(b)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    w.begin_stage(stage_of(app, "ClassifyStage"))
    w.layer_tree.selection_set(row_of(w, b))      # chosen during the run
    pump(app, w)
    runner = SimpleNamespace(products=[("classified", a_classified)], error=None,
                             cancelled=lambda: False, elapsed=1.0)
    w.complete(runner)
    pump(app, w)
    assert task_inputs(app) == {resolved(b)}
    # the result is still the flight's processing version
    assert resolved(a_classified) in w.project_panel.clouds
    assert resolved(a) not in w.project_panel.clouds


def test_a_cloud_typed_into_a_stage_during_classify_stays(application, tmp_path):
    """When the result does take over the input, a cloud the operator typed
    into a stage's own field during the run was replaced along with the
    rest; it stays."""
    from types import SimpleNamespace

    app = application
    w = app.workspace
    a, typed, a_classified = (tmp_path / n for n in ("a.las", "x.las", "a_ground.las"))
    for path in (a, typed, a_classified):
        cloud(path)
    w.project_panel.clouds = [resolved(a)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    w.begin_stage(stage_of(app, "ClassifyStage"))
    dtm = stage_of(app, "DtmStage")
    dtm.cloud_override.set(resolved(typed))           # typed during the run
    runner = SimpleNamespace(products=[("classified", a_classified)], error=None,
                             cancelled=lambda: False, elapsed=1.0)
    w.complete(runner)
    pump(app, w)
    assert app.cloud_path.get() == resolved(a_classified)
    assert stage_of(app, "ContourStage").cloud_override.get() == resolved(a_classified)
    assert dtm.cloud_override.get() == resolved(typed)


def test_a_click_on_a_cloud_still_sets_the_task_input(application, tmp_path):
    """A guard, not a defect: the contract the sidebar states -- select a
    cloud to set the task input -- is kept for real selections."""
    app = application
    w = app.workspace
    a, b = tmp_path / "a.las", tmp_path / "b.las"
    cloud(a)
    cloud(b)
    w.project_panel.clouds = [resolved(a), resolved(b)]
    w.sync_project_layers()
    w.refresh_layers()
    pump(app, w)
    w.layer_tree.selection_set(row_of(w, b))
    pump(app, w)
    assert task_inputs(app) == {resolved(b)}
    w.layer_tree.selection_set(row_of(w, a))
    pump(app, w)
    assert task_inputs(app) == {resolved(a)}


def test_opening_a_workspace_keeps_its_own_task_input(application, tmp_path):
    """Opening a workspace re-selected the previous session's rows BY
    POSITION in the new workspace's file list, and the queued selection
    event made whatever cloud sat at that position the task input."""
    app = application
    w = app.workspace
    x, y, p, q = (tmp_path / f"{n}.las" for n in "xypq")
    for path in (x, y, p, q):
        cloud(path)
    # the workspace to be opened: clouds x and y, task input x
    w.project_panel.clouds = [resolved(x), resolved(y)]
    w.sync_project_layers()
    w.set_active_cloud(resolved(x))
    saved = tmp_path / "saved.argus.json"
    w.path = saved
    w.persist()
    # the session it is opened from: clouds p and q, the second row selected
    w.tracker.data["layers"] = []
    w.project_panel.clouds = [resolved(p), resolved(q)]
    w.sync_project_layers()
    w.layer_tree.selection_set(row_of(w, q))
    pump(app, w)
    assert task_inputs(app) == {resolved(q)}
    w.restore(saved)
    pump(app, w)
    assert task_inputs(app) == {resolved(x)}


def test_opening_a_workspace_drops_the_previous_selection(application, tmp_path):
    """Several rows selected in the previous session came back selected in
    the opened workspace, at the same positions -- rows the operator never
    picked there, which a right-click Remove would then act on."""
    app = application
    w = app.workspace
    x, y, p, q = (tmp_path / f"{n}.las" for n in "xypq")
    for path in (x, y, p, q):
        cloud(path)
    w.project_panel.clouds = [resolved(x), resolved(y)]
    w.sync_project_layers()
    w.set_active_cloud(resolved(x))
    saved = tmp_path / "saved.argus.json"
    w.path = saved
    w.persist()
    w.tracker.data["layers"] = []
    w.project_panel.clouds = [resolved(p), resolved(q)]
    w.sync_project_layers()
    w.layer_tree.selection_set((row_of(w, p), row_of(w, q)))
    pump(app, w)
    w.restore(saved)
    pump(app, w)
    shown = [w.tracker.data["layers"][int(i)]["path"] for i in w.layer_tree.selection()]
    assert shown in ([], [resolved(x)])


# ------------------------------------------ F2: outputs opened as the wrong kind


def surface_asc(path, lift=0.0):
    """A small ESRI ASCII DTM over the test cloud's area."""
    rows, cols = 5, 50
    lines = [f"ncols {cols}", f"nrows {rows}", "xllcorner 1000",
             "yllcorner 1995", "cellsize 2", "NODATA_value -9999"]
    for _ in range(rows):
        lines.append(" ".join(f"{100 + lift + 0.02 * c:.3f}" for c in range(cols)))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def recorded(application, monkeypatch):
    """The workspace's dialogs recorded instead of shown."""
    from pyargus import workspace_gui

    said = {"error": [], "info": [], "ask": [], "open": []}
    monkeypatch.setattr(workspace_gui.messagebox, "showerror",
                        lambda *a, **k: said["error"].append(a))
    monkeypatch.setattr(workspace_gui.messagebox, "showinfo",
                        lambda *a, **k: said["info"].append(a))
    monkeypatch.setattr(workspace_gui.messagebox, "askyesno",
                        lambda *a, **k: said["ask"].append(a) or True)
    monkeypatch.setattr(workspace_gui, "open_externally",
                        lambda path: said["open"].append(str(path)), raising=False)
    return application, application.workspace, said


@pytest.fixture
def shown(recorded, tmp_path):
    """A workspace with a cloud in the viewer, and the dialogs recorded."""
    app, w, said = recorded
    src = tmp_path / "a.las"
    cloud(src)
    w.project_panel.clouds = [resolved(src)]
    w.sync_project_layers()
    w.load_project_clouds()
    pump(app, w)
    return app, w, said


def double_click(app, w, path, kind="output"):
    w.add_layer(path, kind, "job-1")
    w.refresh_layers()
    w.layer_tree.selection_set(row_of(w, path))
    pump(app, w)
    w.toggle_layer()
    pump(app, w)


def test_a_dtm_output_opens_as_a_surface(shown, tmp_path):
    """The defect: an output's kind is 'output', so a DTM .asc fell through
    to the breakline reader and failed with a JSON error."""
    app, w, said = shown
    asc = tmp_path / "dtm.asc"
    surface_asc(asc)
    double_click(app, w, asc)
    assert not said["error"], said["error"]
    assert resolved(asc) in w.overlay_vars
    assert len(w.viewer.extra_points) == 1


def test_a_files_frame_is_confirmed_once_until_the_file_changes(shown, tmp_path):
    """Every overlay asked the frame question again, however many times the
    same unchanged file had been confirmed."""
    app, w, said = shown
    asc = tmp_path / "dtm.asc"
    surface_asc(asc)
    double_click(app, w, asc)
    assert len(said["ask"]) == 1
    # a viewer reload drops overlays; showing it again asks nothing
    w.overlay_vars.clear()
    w.viewer.extra_points.clear()
    w.toggle_layer()
    pump(app, w)
    assert len(said["ask"]) == 1
    # a changed file is a new question: its size alone (the time kept) ...
    import os

    def show_again():
        w.overlay_vars.clear()
        w.viewer.extra_points.clear()
        w.toggle_layer()
        pump(app, w)

    before = asc.stat()
    surface_asc(asc, lift=1000.0)
    os.utime(asc, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert asc.stat().st_size != before.st_size
    show_again()
    assert len(said["ask"]) == 2
    # ... or its time alone (the size kept)
    later = asc.stat()
    surface_asc(asc, lift=1000.0)
    os.utime(asc, ns=(later.st_atime_ns, later.st_mtime_ns + 2_000_000_000))
    assert asc.stat().st_size == later.st_size
    show_again()
    assert len(said["ask"]) == 3


def test_the_frame_question_returns_for_a_cloud_in_another_frame(shown, tmp_path):
    """The answer is about the file AND the cloud it is drawn over: a cloud
    in another coordinate system asks again."""
    app, w, said = shown
    asc = tmp_path / "dtm.asc"
    surface_asc(asc)
    double_click(app, w, asc)
    assert len(said["ask"]) == 1
    other = tmp_path / "other_frame.las"
    cloud(other, epsg=2264)
    w.viewer.load([resolved(other)])
    pump(app, w)
    w.overlay_vars.clear()
    w.viewer.extra_points.clear()
    w.layer_tree.selection_set(row_of(w, asc))
    pump(app, w)
    w.toggle_layer()
    pump(app, w)
    assert len(said["ask"]) == 2


def test_a_missing_file_says_so(shown, tmp_path):
    """confirm_frame read the file's identity outside overlay's error
    handling, so a deleted or disconnected output failed with no message
    at all in the windowed exe."""
    app, w, said = shown
    asc = tmp_path / "dtm.asc"
    surface_asc(asc)
    w.add_layer(asc, "output", "job-1")
    w.refresh_layers()
    w.layer_tree.selection_set(row_of(w, asc))
    pump(app, w)
    asc.unlink()
    w.toggle_layer()
    pump(app, w)
    # (the title, not the text: this test's own folder name says "missing")
    assert said["error"] and said["error"][-1][0] == "Missing file"
    assert "dtm.asc" in said["error"][-1][1]
    assert not said["ask"]
    # the sidebar's Show path reaches the overlay without that check, and
    # must still report rather than raise
    lines = tmp_path / "edge.geojson"
    lines.write_text("{}", encoding="utf-8")
    w.add_layer(lines, "breaklines", "job-1")
    w.refresh_layers()
    w.layer_tree.selection_set(row_of(w, lines))
    pump(app, w)
    lines.unlink()
    w.show_layers()
    pump(app, w)
    assert "edge.geojson" in str(said["error"][-1])


def test_contours_saved_as_json_still_draw(shown, tmp_path):
    """Contours accepts a .json output and writes GeoJSON to it; it drew
    before the fix sorted outputs by kind, and must still."""
    import json

    app, w, said = shown
    lines = tmp_path / "contours.json"
    lines.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {
            "type": "LineString",
            "coordinates": [[1010, 1996, 100.1], [1010, 2004, 100.1]]}}]}),
        encoding="utf-8")
    double_click(app, w, lines)
    assert not said["error"], said["error"]
    assert resolved(lines) in w.overlay_vars


def test_a_contour_dxf_with_a_one_point_contour_still_draws(shown, tmp_path):
    """A peak cell exactly on a contour level makes a closed contour of one
    repeated point; the strict breakline reader refused the whole DXF for
    it, so the stage's own contours would not display."""
    import numpy as np

    from pyargus.formats import dxf
    from pyargus.surfaces import contours as contours_mod

    app, w, said = shown
    z = np.full((7, 7), 100.0)
    z[3, 3] = 100.5                       # exactly on the 0.5 level
    z[0, :] = 101.2                       # and a real contour along one edge
    edges_x = np.linspace(1000.0, 1014.0, 8)
    edges_y = np.linspace(1995.0, 2009.0, 8)
    lines = contours_mod.contour_grid(z, edges_x, edges_y, 0.5)
    out = tmp_path / "contours.dxf"
    dxf.write_contours_dxf(out, lines)
    double_click(app, w, out)
    assert not said["error"], said["error"]
    assert resolved(out) in w.overlay_vars


def test_an_overlay_with_no_cloud_loaded_says_why(recorded, tmp_path):
    """With no cloud in the viewer an overlay did nothing at all."""
    app, w, said = recorded
    asc = tmp_path / "dtm.asc"
    surface_asc(asc)
    double_click(app, w, asc)
    assert said["info"] and "cloud" in str(said["info"][-1]).lower()
    assert not said["ask"]


def test_a_report_folder_opens_its_report(recorded, tmp_path):
    """Strip QA's report folder is an output row; the missing-file check
    called it missing because it is not a file."""
    app, w, said = recorded
    folder = tmp_path / "qa"
    folder.mkdir()
    (folder / "report.html").write_text("<html></html>", encoding="utf-8")
    double_click(app, w, folder)
    assert not said["error"], said["error"]
    assert said["open"] == [resolved(folder / "report.html")]
    empty = tmp_path / "qa-empty"
    empty.mkdir()
    double_click(app, w, empty)
    assert said["open"][-1] == resolved(empty)


def dxf_of(path, *polylines):
    ezdxf = pytest.importorskip("ezdxf")
    document = ezdxf.new()
    for points in polylines:
        document.modelspace().add_polyline3d(points)
    document.saveas(path)


def test_a_breakline_file_is_still_checked_when_shown(shown, tmp_path):
    """Drawing skips a line with no horizontal length only for outputs; an
    operator's own breakline file is still refused for it when shown, as
    the Contours stage will refuse it."""
    app, w, said = shown
    lines = tmp_path / "edges.dxf"
    dxf_of(lines, [(1010, 1996, 100), (1010, 2004, 100)],
           [(1005, 2000, 100), (1005, 2000, 110)])      # vertical
    double_click(app, w, lines, kind="breaklines")
    assert said["error"] and "horizontal length" in str(said["error"][-1])


def test_a_file_of_only_single_point_lines_says_so(shown, tmp_path):
    app, w, said = shown
    out = tmp_path / "peak_only.dxf"
    dxf_of(out, [(1005, 2000, 100.5)] * 5)
    double_click(app, w, out)
    assert said["error"] and "single point" in str(said["error"][-1])


def test_a_report_opens_outside_and_other_outputs_say_why_not(shown, tmp_path):
    app, w, said = shown
    report = tmp_path / "report.html"
    report.write_text("<html></html>", encoding="utf-8")
    double_click(app, w, report)
    assert said["open"] == [resolved(report)]
    table = tmp_path / "section.csv"
    table.write_text("x,y,z\n", encoding="utf-8")
    double_click(app, w, table)
    assert not said["error"], said["error"]
    assert said["info"] and "section.csv" in str(said["info"][-1])


# ------------------------------------ F3: DTM and Contours overwrote outputs


def stage_of(app, name):
    from pyargus import gui
    return next(s for s in app.stages if isinstance(s, getattr(gui, name)))


@pytest.mark.parametrize("name, product", [("DtmStage", "dtm.asc"),
                                           ("ContourStage", "contours.dxf")])
def test_a_typed_existing_output_is_refused(application, tmp_path, name, product):
    """Classify, Above ground, Align and Colorize refused an output path
    that already exists; these two wrote over it."""
    src = tmp_path / "a.las"
    cloud(src)
    application.cloud_path.set(str(src))
    stage = stage_of(application, name)
    existing = tmp_path / product
    existing.write_text("delivered\n", encoding="utf-8")
    stage.out_path.set(str(existing))
    with pytest.raises(ValueError, match="already exists"):
        stage.prepare()
    assert existing.read_text(encoding="utf-8") == "delivered\n"


def test_strip_qa_refuses_a_folder_that_holds_a_report(application, tmp_path):
    """Strip QA wrote its report into the chosen folder whatever was there:
    a Final QA run into the Initial QA folder replaced the pre-alignment
    report, and both history entries then opened the final one."""
    src = tmp_path / "a.las"
    cloud(src)
    application.cloud_path.set(str(src))
    folder = tmp_path / "qa"
    folder.mkdir()
    (folder / "report.html").write_text("initial\n", encoding="utf-8")
    stage = stage_of(application, "QaStage")
    stage.out_dir.set(str(folder))
    with pytest.raises(ValueError, match="already"):
        stage.prepare()
    # an empty folder, the one the folder picker usually returns, is fine
    fresh = tmp_path / "qa-final"
    fresh.mkdir()
    stage.out_dir.set(str(fresh))
    stage.prepare()


def test_no_save_dialog_offers_to_replace_a_file_it_will_refuse():
    """Every save dialog whose target is refused when it exists passes
    confirmoverwrite=False; only 'Save workspace as', which overwrites on
    purpose, keeps the question."""
    import ast

    allowed = {("workspace_gui.py", "save_as")}
    offending = []
    for source in Path(__file__).resolve().parent.parent.joinpath("pyargus").glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(function):
                if (isinstance(call, ast.Call)
                        and getattr(call.func, "attr", None) == "asksaveasfilename"
                        and (source.name, function.name) not in allowed):
                    flag = next((k.value for k in call.keywords if k.arg == "confirmoverwrite"), None)
                    if not (isinstance(flag, ast.Constant) and flag.value is False):
                        offending.append(f"{source.name}:{call.lineno}")
    assert not offending, offending


def test_the_save_dialog_does_not_offer_to_replace(application, monkeypatch):
    """The save dialog asked 'Do you want to replace it?', and Run then
    refused the file the operator had just agreed to replace. Refusing is
    the one policy, so the dialog no longer offers it."""
    import tkinter as tk
    from tkinter import ttk

    from pyargus import gui

    asked = []
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename",
                        lambda **options: asked.append(options) or "")
    box = ttk.Frame(application.root)
    gui.path_row(box, "Out", tk.StringVar(), 0, save=True)
    [button] = [w for w in box.winfo_children() if isinstance(w, ttk.Button)]
    button.invoke()
    assert asked and asked[0].get("confirmoverwrite") is False


# ------------------------- F4: the solve-only record landed where it started


def test_a_solve_only_align_record_never_lands_where_the_program_started(
        application, tmp_path, monkeypatch):
    """With no corrected cloud to sit beside, the record went under the
    working folder -- the install folder, for the exe. It goes to the
    workspace's own folder."""
    from tests.test_gui import _FakeRunner

    started = tmp_path / "started-here"
    started.mkdir()
    monkeypatch.chdir(started)
    job = tmp_path / "job"
    job.mkdir()
    application.workspace.path = job / "survey.argus.json"
    src = tmp_path / "a.las"
    cloud(src)
    trajectory = tmp_path / "flight.out"
    trajectory.write_bytes(b"")
    application.cloud_path.set(str(src))
    application.sbet_path.set(str(trajectory))
    work = stage_of(application, "AlignStage").prepare()
    runner = _FakeRunner()
    with pytest.raises(Exception):
        work(runner)                   # an empty trajectory fails the run
    assert not list(started.rglob("*"))
    said = [line.split("job record: ", 1)[1] for line in runner.logged
            if line.startswith("job record: ")]
    assert [Path(p).parent for p in said] == [job / ".pyargus" / "records"]
    assert Path(said[0]).is_file()


def test_a_solve_only_align_is_refused_where_no_record_can_be_kept(
        application, tmp_path):
    """A workspace in a folder that cannot hold records failed the Align
    after it started, with no record anywhere; it is refused at Run."""
    job = tmp_path / "job"
    job.mkdir()
    (job / ".pyargus").write_text("a file where the folder would go\n",
                                  encoding="utf-8")
    application.workspace.path = job / "survey.argus.json"
    src = tmp_path / "a.las"
    cloud(src)
    trajectory = tmp_path / "flight.out"
    trajectory.write_bytes(b"")
    application.cloud_path.set(str(src))
    application.sbet_path.set(str(trajectory))
    with pytest.raises(ValueError, match="record"):
        stage_of(application, "AlignStage").prepare()


# ------------------------------------- F5: three stages left no job record


def records_beside(out):
    import json

    out = Path(out)
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in out.parent.glob(out.name + ".job-*.json")]


def test_a_dtm_run_leaves_a_record_of_its_points_and_fill(application, tmp_path):
    from tests.test_gui import _FakeRunner

    src = tmp_path / "a.las"
    cloud(src)
    application.cloud_path.set(str(src))
    stage = stage_of(application, "DtmStage")
    stage.cell.set("2.0")
    for dsm, classes in ((False, [2]), (True, "all")):
        out = tmp_path / f"surface-{dsm}.asc"
        stage.out_path.set(str(out))
        stage.dsm.set(dsm)
        stage.prepare()(_FakeRunner())
        [record] = records_beside(out)
        assert (record["operation"], record["status"]) == ("dtm", "completed")
        settings = record["settings"]
        assert (settings["dsm"], settings["classes_used"]) == (dsm, classes)
        assert (settings["cell"], settings["max_fill"]) == (2.0, 10)
        assert [i["path"] for i in record["inputs"]] == [resolved(src)]
        assert [o["path"] for o in record["outputs"]] == [resolved(out)]
        # the grid's size, as the delivered .asc header states it (the test
        # cloud is long east-west, so a swap shows)
        header = dict(line.split()[:2] for line in
                      out.read_text(encoding="utf-8").splitlines()[:6])
        results = record["results"]
        assert (results["ncols"], results["nrows"]) == (
            int(header["ncols"]), int(header["nrows"]))
        assert results["ncols"] != results["nrows"]


def test_a_solve_only_align_is_refused_where_records_cannot_be_written(
        application, tmp_path, monkeypatch):
    """A records folder that exists but cannot be written (a colleague's
    shared job folder) passed the check and failed the Align after it
    started."""
    import tempfile

    job = tmp_path / "job"
    (job / ".pyargus" / "records").mkdir(parents=True)
    application.workspace.path = job / "survey.argus.json"
    src = tmp_path / "a.las"
    cloud(src)
    trajectory = tmp_path / "flight.out"
    trajectory.write_bytes(b"")
    application.cloud_path.set(str(src))
    application.sbet_path.set(str(trajectory))

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(tempfile, "TemporaryFile", denied)
    with pytest.raises(ValueError, match="record"):
        stage_of(application, "AlignStage").prepare()


def test_load_result_survives_a_malformed_record(recorded, tmp_path):
    import json

    app, w, said = recorded
    record = tmp_path / "odd.job-1.json"
    record.write_text(json.dumps({"schema_version": 1, "operation": ["qa"],
                                  "results": {}}), encoding="utf-8")
    job = w.tracker.begin("Surface", {}, [])
    job["records"] = [str(record)]
    w.tracker.finish(job, "Needs review", [])
    w.selected_job = lambda: job
    w.load_result()
    assert said["error"]


def test_load_result_on_a_job_with_an_unreviewable_record(recorded, tmp_path):
    """'Load selected result' opened every job's record in the QA review,
    which reads only QA, alignment and ground-classification records: the
    records the surface stages now write made it an error dialog."""
    from tests.test_gui import _FakeRunner

    app, w, said = recorded
    src = tmp_path / "a.las"
    cloud(src)
    app.cloud_path.set(str(src))
    stage = stage_of(app, "DtmStage")
    out = tmp_path / "dtm.asc"
    stage.out_path.set(str(out))
    runner = _FakeRunner()
    stage.prepare()(runner)
    record = next(line.split("job record: ", 1)[1] for line in runner.logged
                  if line.startswith("job record: "))
    job = w.tracker.begin("Surface", {}, [])
    job["records"] = [record]
    w.tracker.finish(job, "Needs review", [str(out)])
    w.selected_job = lambda: job
    w.load_result()
    pump(app, w)
    assert not said["error"], said["error"]


def test_a_contour_run_leaves_a_record(application, tmp_path):
    from tests.test_gui import _FakeRunner

    src = tmp_path / "a.las"
    cloud(src)
    application.cloud_path.set(str(src))
    stage = stage_of(application, "ContourStage")
    out = tmp_path / "contours.geojson"
    stage.out_path.set(str(out))
    stage.interval.set("0.2")
    stage.cell.set("2.0")
    stage.prepare()(_FakeRunner())
    [record] = records_beside(out)
    assert (record["operation"], record["status"]) == ("contours", "completed")
    settings = record["settings"]
    assert settings["classes_used"] == [2]
    assert (settings["interval"], settings["cell"], settings["max_fill"],
            settings["index_every"]) == (0.2, 2.0, 10, 5)
    assert [i["path"] for i in record["inputs"]] == [resolved(src)]
    assert [o["path"] for o in record["outputs"]] == [resolved(out)]
    assert record["results"]["lines"] > 0

    # with breaklines the surface is a TIN, and the breakline file is an input
    import json

    lines = tmp_path / "edge.geojson"
    lines.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {
            "type": "LineString",
            "coordinates": [[1020, 1996, 100.2], [1020, 2004, 100.2]]}}]}),
        encoding="utf-8")
    stage.breaklines.set(str(lines))
    out = tmp_path / "contours-tin.geojson"
    stage.out_path.set(str(out))
    stage.prepare()(_FakeRunner())
    [record] = records_beside(out)
    assert record["settings"]["surface"] == "TIN with breaklines"
    assert record["settings"]["max_fill"] == 10
    assert [i["path"] for i in record["inputs"]] == [resolved(src), resolved(lines)]
    assert record["results"]["breaklines"] == 1


def test_above_ground_runs_leave_records(application, tmp_path):
    import laspy
    import numpy as np

    from tests.synthetic import labeled_scene
    from tests.test_gui import _FakeRunner

    points, labels = labeled_scene(seed=4)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    for name, values in points.items():
        data[name] = values
    data.classification = labels
    src = tmp_path / "labeled.las"
    data.write(src)
    application.cloud_path.set(str(src))
    stage = stage_of(application, "AboveStage")
    stage.mode.set("Train model")
    stage.cell.set("2.0")
    model = tmp_path / "model.joblib"
    stage.out_path.set(str(model))
    stage.prepare()(_FakeRunner())
    [trained] = records_beside(model)
    assert (trained["operation"], trained["status"]) == ("train-above", "completed")
    assert trained["settings"]["cell"] == 2.0
    assert trained["settings"]["classes_used"] == [3, 4, 5, 6]
    assert trained["settings"]["xyz_units"] == "US survey feet"
    # the height-above-ground surface that decided every point's features
    hag = {k: trained["settings"].get(k) for k in ("hag_dtm_cell", "hag_max_fill")}
    assert hag == {"hag_dtm_cell": 3.0, "hag_max_fill": 10}

    bare = tmp_path / "bare.las"
    data.classification = np.where(labels == 2, 2, 1).astype(np.uint8)
    data.write(bare)
    stage.mode.set("Apply model")
    stage.model_path.set(str(model))
    stage.cloud_override.set(str(bare))
    out = tmp_path / "full.las"
    stage.out_path.set(str(out))
    stage.prepare()(_FakeRunner())
    [applied] = records_beside(out)
    assert (applied["operation"], applied["status"]) == ("classify-above", "completed")
    assert applied["settings"]["cell"] == 2.0
    assert applied["settings"]["classes_used"] == sorted(
        int(c) for c in np.unique(labels) if c in (3, 4, 5, 6))
    assert {k: applied["settings"].get(k) for k in ("hag_dtm_cell", "hag_max_fill")} == hag
    assert [i["path"] for i in applied["inputs"]] == [resolved(bare), resolved(model)]
    assert [o["path"] for o in applied["outputs"]] == [resolved(out)]


def test_a_cancelled_run_says_so_in_its_record(application, tmp_path):
    from tests.test_gui import _FakeRunner

    src = tmp_path / "a.las"
    cloud(src)
    application.cloud_path.set(str(src))
    runner = _FakeRunner()
    runner.cancelled = lambda: True
    for name, product in (("DtmStage", "dtm.asc"), ("ContourStage", "c.dxf")):
        stage = stage_of(application, name)
        out = tmp_path / product
        stage.out_path.set(str(out))
        if name == "ContourStage":
            stage.interval.set("0.2")
        stage.prepare()(runner)
        assert not out.exists()
        [record] = records_beside(out)
        assert record["status"] == "cancelled"
    stage = stage_of(application, "AboveStage")
    stage.mode.set("Train model")
    model = tmp_path / "model.joblib"
    stage.out_path.set(str(model))
    stage.prepare()(runner)
    assert not model.exists()
    [record] = records_beside(model)
    assert record["status"] == "cancelled"
