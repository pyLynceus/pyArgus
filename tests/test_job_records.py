import json
import pytest
from pyargus.imagery.job import colorize_cloud
from pyargus.job_manifest import JobRecord
from tests.test_cli_colorize import scene


def records(out):
    return [json.loads(p.read_text()) for p in out.parent.glob(out.name + ".job-*.json")]


def test_success_and_cancel_keep_separate_records(scene, tmp_path):
    cloud, eo, images, _ = scene
    out = tmp_path / "rgb.las"
    stats = colorize_cloud(cloud, eo, images, out, quarter_turns=0)
    before = out.read_bytes()
    record = records(out)[0]
    assert record["status"] == "completed"
    assert record["results"]["pct_colored"] == 100
    assert record["output"]["size_bytes"] == len(before)
    assert record["inputs"][1]["sha256"]
    assert record["calibration_provenance"][0]["sha256"]
    assert record["matched_images"][0]["identity_method"] == "size_and_mtime"
    assert stats["job_manifest"]
    colorize_cloud(cloud, eo, images, out, quarter_turns=0, should_stop=lambda: True)
    assert sorted(r["status"] for r in records(out)) == ["cancelled", "completed"]
    assert out.read_bytes() == before


def test_failed_calibration_records_reason_without_cloud(scene, tmp_path):
    cloud, eo, images, _ = scene
    (images / "0001.png.cal").unlink()
    out = tmp_path / "failed.las"
    with pytest.raises(ValueError, match="calibration"):
        colorize_cloud(cloud, eo, images, out)
    record = records(out)[0]
    assert record["status"] == "failed"
    assert record["error"]["type"] == "ValueError"
    assert "output" not in record
    assert not out.exists()


def test_write_failure_is_not_success(scene, tmp_path, monkeypatch):
    from pyargus.formats import las
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(las, "stream_update", fail)
    cloud, eo, images, _ = scene
    out = tmp_path / "failed.las"
    with pytest.raises(OSError, match="disk full"):
        colorize_cloud(cloud, eo, images, out, quarter_turns=0)
    assert records(out)[0]["status"] == "failed"


def test_running_record_and_incomplete_exit(tmp_path):
    out = tmp_path / "out.las"
    with JobRecord("test", out, {}) as record:
        assert json.loads(record.path.read_text())["status"] == "running"
    assert records(out)[0]["status"] == "failed"
    assert not list(tmp_path.glob("*.tmp"))
