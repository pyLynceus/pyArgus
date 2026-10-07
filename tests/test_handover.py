"""The pyLynceus launcher's handover: read, refused by name, translated.

The envelope is the contract between two repositories; these tests hold
this side of it. The fixture below is written BY HAND -- the version-2
shape the launcher's write_handover produces -- never by importing the
launcher's code: the checkouts stay separate, and the contract is what
is tested, not the other side's implementation.

The seam's acceptance (spec task 8): two clouds listed in a handover load
as active project inputs (the GUI half lives in test_unified_workspace).
"""

import json
import os
from pathlib import Path

import pytest

from pyargus.handover import FORMAT, VERSION, HandoverRefused, read_handover, resolve


def _envelope(job, clouds=(), inputs=None, **overrides):
    """A version-2 handover as the launcher writes one: absolute paths,
    the job's words in context, the launch's own log in outputs."""
    data = {
        "format": FORMAT,
        "version": VERSION,
        "written_utc": "2026-10-07T21:00:00Z",
        "app": "pyargus",
        "project_dir": str(job),
        "job_file": str(job / "job.pyljob"),
        "run_mode": "dev_venv",
        "inputs": dict({"clouds": [str(c) for c in clouds]}, **(inputs or {})),
        "outputs": {"log": str(job / "logs" / "pyargus-20261007T210000Z.log")},
        "context": {"units": "us_survey_feet", "job_id": "S1001",
                    "title": "Synthetic Job", "datum": "corrected ccsm"},
        "block": None,
        "clouds": [],
    }
    data.update(overrides)
    return data


def _write(tmp_path, data, name="pyargus-20261007T210000Z.handover.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def test_a_v2_envelope_translates(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    cloud_a = job / "lidar" / "a.las"
    cloud_a.parent.mkdir()
    cloud_a.write_bytes(b"LASF")
    path = _write(tmp_path, _envelope(job, [cloud_a]))

    read = read_handover(path)
    assert read.path == path
    assert read.project_dir == job
    assert read.job_file == job / "job.pyljob"
    assert read.clouds == [cloud_a]
    assert read.units == "us_survey_feet"
    assert read.job_id == "S1001" and read.title == "Synthetic Job"
    assert read.notes == []


def test_a_relative_cloud_resolves_against_the_job_folder(tmp_path):
    job = tmp_path / "job"
    (job / "lidar").mkdir(parents=True)
    (job / "lidar" / "a.las").write_bytes(b"LASF")
    # the contract's fallback: a relative path re-resolved against project_dir
    path = _write(tmp_path, _envelope(job, ["lidar/a.las"]))
    read = read_handover(path)
    assert read.clouds == [job / "lidar" / "a.las"]


def test_a_version_1_envelope_is_refused_by_its_version(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    data = _envelope(job)
    data["version"] = 1
    del data["job_file"]                      # v1 called it job_plj
    path = _write(tmp_path, data)
    with pytest.raises(HandoverRefused) as refused:
        read_handover(path)
    said = str(refused.value)
    assert "version-1" in said and "does not translate" in said
    assert "job_file" not in said             # by its version, not a missing key


def test_an_unknown_version_is_refused(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    path = _write(tmp_path, _envelope(job, version=3))
    with pytest.raises(HandoverRefused, match="version 3"):
        read_handover(path)


def test_a_foreign_format_is_refused_by_name(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    path = _write(tmp_path, _envelope(job, format="pylynceus-job"))
    with pytest.raises(HandoverRefused, match="not a pyLynceus handover"):
        read_handover(path)


def test_missing_and_unreadable_files_are_refused_by_name(tmp_path):
    with pytest.raises(HandoverRefused, match="cannot be read"):
        read_handover(tmp_path / "not-there.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(HandoverRefused, match="not JSON"):
        read_handover(bad)


def test_a_job_folder_that_is_gone_is_refused(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    path = _write(tmp_path, _envelope(job))
    job.rmdir()
    with pytest.raises(HandoverRefused, match="not there"):
        read_handover(path)


def test_a_cloud_not_on_disk_is_a_note_and_the_others_load(tmp_path):
    job = tmp_path / "job"
    (job / "lidar").mkdir(parents=True)
    there = job / "lidar" / "a.las"
    there.write_bytes(b"LASF")
    gone = job / "lidar" / "b.las"
    path = _write(tmp_path, _envelope(job, [there, gone, job / "notes.txt"]))
    read = read_handover(path)
    assert read.clouds == [there]
    assert any(str(gone) in note for note in read.notes)
    assert any("not a LAS/LAZ" in note for note in read.notes)


def test_control_and_adjustment_are_offered_only_when_on_disk(tmp_path):
    job = tmp_path / "job"
    (job / "control").mkdir(parents=True)
    control = job / "control" / "control.csv"
    control.write_text("n,e,z\n", encoding="utf-8")
    path = _write(tmp_path, _envelope(
        job, inputs={"control": str(control), "adjustment": str(job / "gone.atx")}))
    read = read_handover(path)
    assert read.control == control
    assert read.adjustment is None
    assert any("adjustment" in note for note in read.notes)


def test_resolve_reads_the_launchers_environment(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    path = _write(tmp_path, _envelope(job))
    env = {"PYLYNCEUS_HANDOVER": str(path), "PYLYNCEUS_PROJECT": str(job)}
    read = resolve(environ=env)
    assert read.clouds == [] and read.project_dir == job

    # a --project naming a different job than the handover is refused
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(HandoverRefused, match="not --project's"):
        resolve(handover=str(path), project=str(other))
    # no handover, no project: a plain window
    assert resolve(environ={}) is None
    # a bare --project: the folder must be there
    assert resolve(project=str(job), environ={}).project_dir == job
    with pytest.raises(HandoverRefused, match="not there"):
        resolve(project=str(tmp_path / "gone"), environ={})


def test_the_gui_parser_takes_the_contracts_flags():
    from pyargus.cli import build_parser

    args = build_parser().parse_args(["gui", "--project", "P", "--handover", "H"])
    assert args.project == "P" and args.handover == "H"


def test_the_gui_refuses_a_bad_handover_before_any_window(tmp_path, capsys):
    """Exit 2, the suite's user-facing error, and the reason on stderr --
    before Tk is even asked for a root."""
    from pyargus import gui

    code = gui.main(handover=str(tmp_path / "not-there.json"))
    assert code == 2
    said = capsys.readouterr().err
    assert "pyArgus:" in said and "cannot be read" in said


def test_the_frozen_entry_takes_the_contracts_flags():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "launch_gui", Path(__file__).resolve().parent.parent / "packaging" / "launch_gui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._flag(["--project", "P"], "--project") == "P"
    assert module._flag(["--handover"], "--handover") is None
    assert module._flag([], "--project") is None
