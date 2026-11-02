import os
from types import SimpleNamespace
from pathlib import Path
import pytest
from pyargus import publication


@pytest.fixture(autouse=True)
def no_delays(monkeypatch):
    monkeypatch.setattr(publication, 'RETRY_DELAYS', (0.,))


def test_successful_posix_file_publication_survives_old_link_cleanup_failure(tmp_path, monkeypatch, caplog):
    source, target = tmp_path/'source', tmp_path/'target'
    source.write_text('complete output')
    real_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path == source:raise PermissionError('cleanup lock')
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', unlink)
    monkeypatch.setattr(publication, 'os', SimpleNamespace(name='posix', link=os.link))
    publication.publish_new(source, target)
    assert target.read_text() == 'complete output'
    assert source.exists()
    assert str(source) in caplog.text


def test_failed_cleanup_keeps_original_cancellation(tmp_path, monkeypatch, caplog):
    def locked(*args, **kwargs):raise PermissionError('cleanup lock')
    monkeypatch.setattr(publication.shutil, 'rmtree', locked)
    with pytest.raises(InterruptedError, match='operator Stop'):
        with publication.staging_directory(tmp_path, prefix='.stage-') as stage:
            (stage/'partial').write_text('partial output')
            raise InterruptedError('operator Stop')
    assert stage.exists()
    assert str(stage) in caplog.text


def test_failed_cleanup_after_commit_does_not_fail_completed_output(tmp_path, monkeypatch, caplog):
    target = tmp_path/'published.las'
    def locked(*args, **kwargs):raise PermissionError('cleanup lock')
    monkeypatch.setattr(publication.shutil, 'rmtree', locked)
    with publication.staging_directory(tmp_path, prefix='.stage-') as stage:
        source = stage/'complete.las';source.write_bytes(b'complete')
        publication.publish_new(source, target)
    assert target.read_bytes() == b'complete'
    assert str(stage) in caplog.text
