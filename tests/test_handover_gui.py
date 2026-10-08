"""The seam's GUI half: a handover's clouds become active project inputs.

Spec task 8's acceptance, pyArgus side: "two test clouds listed in
handover load as active inputs." The envelope is written by hand here --
the version-2 shape the launcher produces -- so this repository's tests
never import the launcher's code.
"""

import json

from pyargus.handover import resolve
from tests.test_gui import application, root          # noqa: F401 (fixtures)
from tests.test_review_workspace import cloud, wait


def _envelope(job, clouds):
    return {
        "format": "pylynceus-handover", "version": 2,
        "written_utc": "2026-10-07T21:00:00Z", "app": "pyargus",
        "project_dir": str(job), "job_file": str(job / "job.pyljob"),
        "run_mode": "dev_venv",
        "inputs": {"clouds": [str(c) for c in clouds]},
        "outputs": {"log": str(job / "logs" / "pyargus-20261007T210000Z.log")},
        "context": {"units": "us_survey_feet", "job_id": "S1001",
                    "title": "Synthetic Job", "datum": "corrected ccsm"},
        "block": None, "clouds": [],
    }


def test_two_handover_clouds_load_as_active_inputs(application, tmp_path):
    app = application
    first, second = tmp_path / "a.las", tmp_path / "b.las"
    cloud(first)
    cloud(second, dz=1.5)
    job = tmp_path / "job"
    (job / "cache").mkdir(parents=True)
    envelope = job / "cache" / "pyargus-x.handover.json"
    envelope.write_text(json.dumps(_envelope(job, [first, second])),
                        encoding="utf-8")

    app.apply_launch(resolve(handover=str(envelope)))
    wait(app.root, app.workspace.viewer)
    app.workspace.poll()

    panel = app.workspace.project_panel
    assert panel.clouds == [str(first.resolve()), str(second.resolve())]
    assert app.cloud_path.get() == str(first.resolve())
    assert "Synthetic Job" in app.root.title()
    assert "Synthetic Job" in app.workspace.here.get()
    # both clouds are displayable project layers, not just filenames
    kinds = {layer["path"]: layer["kind"] for layer in app.workspace.tracker.data["layers"]}
    assert kinds[str(first.resolve())] == "cloud"
    assert kinds[str(second.resolve())] == "cloud"


def test_notes_are_said_in_the_log(application, tmp_path):
    app = application
    missing = tmp_path / "gone.las"
    job = tmp_path / "job"
    (job / "cache").mkdir(parents=True)
    envelope = job / "cache" / "pyargus-y.handover.json"
    envelope.write_text(json.dumps(_envelope(job, [missing])), encoding="utf-8")

    app.apply_launch(resolve(handover=str(envelope)))
    said = "\n".join(str(line) for line in app.runner.lines.queue)
    assert "not on disk" in said
    assert app.workspace.project_panel.clouds == []


# --- review findings (2026-10-08), GUI half --------------------------------

def test_a_handed_over_control_is_reported_with_its_action(application, tmp_path):
    """Finding 3: an offered control vanished silently -- the reader set the
    field, apply_launch ignored it. It must be said, with the manual action."""
    import json as _json

    from pyargus.handover import resolve

    app = application
    control = tmp_path / "control.csv"
    control.write_text("p,n,e,z\n", encoding="utf-8")
    job = tmp_path / "job"
    (job / "cache").mkdir(parents=True)
    envelope = job / "cache" / "x.handover.json"
    envelope.write_text(_json.dumps({
        "format": "pylynceus-handover", "version": 2,
        "project_dir": str(job), "job_file": str(job / "job.pyljob"),
        "inputs": {"clouds": [], "control": str(control)},
        "context": {},
    }), encoding="utf-8")

    app.apply_launch(resolve(handover=str(envelope)))
    said = "\n".join(str(line) for line in app.runner.lines.queue)
    assert str(control) in said and "column order" in said


def test_the_check_door_reports_the_control(application, tmp_path, capsys):
    """The --check report names the control and its required action too."""
    import json as _json

    from pyargus import gui
    from pyargus.handover import resolve

    control = tmp_path / "control.csv"
    control.write_text("p,n,e,z\n", encoding="utf-8")
    job = tmp_path / "job"
    job.mkdir()
    envelope = tmp_path / "x.handover.json"
    envelope.write_text(_json.dumps({
        "format": "pylynceus-handover", "version": 2,
        "project_dir": str(job), "job_file": str(job / "job.pyljob"),
        "inputs": {"clouds": [], "control": str(control)},
        "context": {},
    }), encoding="utf-8")
    code = gui.main(handover=str(envelope), check=True)
    assert code == 0
    said = capsys.readouterr().out
    assert str(control) in said and "column order" in said


def test_the_primary_pickers_start_in_the_launch_folder(monkeypatch, application):
    """Finding 2: PYARGUS_DATA_DIR reached only the legacy dialogs; the
    workspace's own Add files / folder pickers ignored it."""
    import os

    from unittest.mock import patch

    from pyargus import workspace_gui

    app = application
    folder = "C:/some/job/folder"
    monkeypatch.setenv("PYARGUS_DATA_DIR", folder)
    seen = {}

    def _capture(*args, **kwargs):
        seen.update(kwargs)
        return ()

    with patch.object(workspace_gui.filedialog, "askopenfilenames", _capture):
        app.workspace.add_files()
    assert seen.get("initialdir") == folder

    with patch.object(workspace_gui.filedialog, "askdirectory", _capture):
        app.workspace.add_folder()
    assert seen.get("initialdir") == folder
