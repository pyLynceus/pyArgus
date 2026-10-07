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
