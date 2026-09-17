from dataclasses import replace
import json
from pathlib import Path
import numpy as np
import pytest

from pyargus import project, cli
from pyargus.analysis_records import analysis_job, finish
from tests.test_project import scene
from tests.test_cli_align import scene_files, GEOID
from tests.test_gui import application, root, _FakeRunner


def read_record(out):
    paths = list(out.parent.glob(out.name + ".job-*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text())


@pytest.mark.parametrize("large", [False, True])
def test_project_qa_records_both_engines(scene, tmp_path, large):
    out = tmp_path / "qa"
    summary = project.qa(replace(scene, max_points=1) if large else scene, out)
    record = read_record(out)
    assert record["status"] == "completed"
    assert record["results"]["points"] == summary["points"]
    assert len(record["inputs"]) == 4
    assert record["settings"]["project"]["trajectories"][0]["time_mode"] == "same"
    assert all(Path(p["path"]).exists() for p in record["outputs"])


def test_project_alignment_records_exported_qa_and_corrections(scene, tmp_path):
    out = tmp_path / "align"
    summary = project.align(scene, out, solve_boresight=False)
    record = read_record(out)
    result = record["results"]
    assert record["status"] == "completed"
    assert result["corrections_written"]
    assert result["offsets"] == summary["offsets"]
    assert result["before_qa"]["strip_dz"][0]["rmse"] > result["after_qa"]["strip_dz"][0]["rmse"]
    assert len(record["outputs"]) == 5


@pytest.mark.parametrize("operation", [project.qa, project.align])
def test_project_cancel_retains_record_without_publishing(scene, tmp_path, operation):
    out = tmp_path / "cancel"
    with pytest.raises(project.Cancelled):
        operation(scene, out, cancel=lambda: True)
    assert read_record(out)["status"] == "cancelled"
    assert not out.exists()


def test_failed_alignment_keeps_existing_output(scene, tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    (out / "keep").write_text("unchanged")
    with pytest.raises(ValueError, match="exists"):
        project.align(scene, out)
    assert read_record(out)["status"] == "failed"
    assert (out / "keep").read_text() == "unchanged"


def test_cli_solve_only_uses_working_directory(scene_files, tmp_path, monkeypatch):
    cloud, trajectory = scene_files
    monkeypatch.chdir(tmp_path)
    cli.main(["align", str(cloud), "--sbet", str(trajectory), "--map-crs", "EPSG:6447",
              "--vertical", str(GEOID), "--no-boresight", "--cell", "20", "--min-points", "6"])
    record = read_record(tmp_path / "pyargus-job-records" / "alignment-solve")
    assert record["status"] == "completed"
    assert record["intended_output"] is None
    assert not record["results"]["corrections_written"]
    assert record["results"]["offsets_by_strip"]
    assert record["outputs"] == []


def test_cli_qa_records_summary(scene, tmp_path):
    out = tmp_path / "single"
    cli.main(["qa-report", scene.clouds[0], "--out", str(out)])
    assert read_record(out)["results"]["strip_dz"]


def test_gui_qa_records_success_and_cancel(scene, tmp_path, application):
    application.cloud_path.set(scene.clouds[0])
    stage = application.stages[0]
    out = tmp_path / "gui"
    stage.out_dir.set(str(out))
    stage.prepare()(_FakeRunner())
    assert read_record(out)["status"] == "completed"
    out = tmp_path / "gui-cancel"
    stage.out_dir.set(str(out))
    runner = _FakeRunner()
    runner.cancelled = lambda: True
    stage.prepare()(runner)
    assert read_record(out)["status"] == "cancelled"
    assert not out.exists()


def test_missing_input_and_null_metrics(tmp_path):
    out = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        with analysis_job("qa", out, {}, inputs=[tmp_path / "absent"]):
            pass
    assert read_record(out)["status"] == "failed"
    out = tmp_path / "null"
    with analysis_job("qa", out, {}) as record:
        finish(record, {"empty": np.float64(float("nan")), "values": np.array([1, 2])})
    assert read_record(out)["results"] == {"empty": None, "values": [1, 2]}


def test_gui_alignment_records_written_corrections(scene_files, tmp_path, application, monkeypatch):
    import laspy
    from pyproj import CRS
    from pyargus import align
    cloud, trajectory = scene_files
    local = tmp_path / "tagged.las"
    data = laspy.read(cloud)
    data.header.add_crs(CRS("EPSG:6447"))
    data.write(local)
    from pyargus import gui
    monkeypatch.setattr(gui, "ALIGN_CELL", 20.)
    original = align.solve_alignment
    # This parallel-heading fixture only observes offsets. Keep the GUI job
    # path real while restricting the test solver to its observable parameters.
    def solve(bundles, **kwargs):
        return original(bundles, **dict(kwargs, solve_boresight=False))
    monkeypatch.setattr(align, "solve_alignment", solve)
    application.cloud_path.set(str(local))
    application.sbet_path.set(str(trajectory))
    stage = application.stages[4]
    stage.vertical.set(str(GEOID))
    out = tmp_path / "gui-fixed.las"
    stage.write_path.set(str(out))
    stage.prepare()(_FakeRunner())
    record = read_record(out)
    assert record["status"] == "completed"
    assert record["results"]["corrections_written"]
    assert CRS(record["resolved_frame"]["map_crs"]).to_epsg() == 6447
    assert record["outputs"][0]["size_bytes"] == out.stat().st_size
