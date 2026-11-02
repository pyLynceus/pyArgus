import json
from pathlib import Path
import pytest
from pyargus import publication


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(publication, 'RETRY_DELAYS', (0., 0.))


def test_one_transient_rename_failure_is_retried(tmp_path, monkeypatch):
    target = tmp_path/'published'
    actual = publication._rename_new
    attempts = []
    def rename(source, dest):
        attempts.append(1)
        if len(attempts) == 1:raise PermissionError('one temporary lock')
        return actual(source, dest)
    monkeypatch.setattr(publication, '_rename_new', rename)
    with publication.staging_directory(tmp_path, prefix='.stage-') as stage:
        (stage/'complete.txt').write_text('all records verified')
        publication.publish_new(stage, target)
    assert len(attempts) == 2
    assert (target/'complete.txt').read_text() == 'all records verified'
    assert not list(tmp_path.glob('.stage-*'))


def test_persistent_publication_failure_retains_complete_output(tmp_path, monkeypatch):
    target = tmp_path/'published'
    def fail(*args):raise PermissionError('locked')
    monkeypatch.setattr(publication, '_rename_new', fail)
    with pytest.raises(publication.PublicationError, match='retained for recovery') as caught:
        with publication.staging_directory(tmp_path, prefix='.stage-') as stage:
            (stage/'complete.txt').write_text('all records verified')
            publication.publish_new(stage, target)
    assert not target.exists()
    assert (caught.value.recovery_path/'complete.txt').read_text() == 'all records verified'


def test_existing_target_is_never_replaced(tmp_path):
    target = tmp_path/'published';target.mkdir();(target/'old').write_text('original')
    with pytest.raises(publication.PublicationError):
        with publication.staging_directory(tmp_path, prefix='.stage-') as stage:
            (stage/'new').write_text('new output')
            publication.publish_new(stage, target)
    assert (target/'old').read_text() == 'original'
    assert not (target/'new').exists()
    assert (stage/'new').read_text() == 'new output'


def test_cancelled_work_is_cleaned_and_not_published(tmp_path):
    with pytest.raises(InterruptedError):
        with publication.staging_directory(tmp_path, prefix='.stage-') as stage:
            (stage/'partial').write_text('incomplete')
            raise InterruptedError('Stop')
    assert not list(tmp_path.iterdir())


def test_failed_json_replacement_retains_old_record_and_recovery_copy(tmp_path, monkeypatch):
    target = tmp_path/'record.json';publication.atomic_write_json(target, {'status':'previous'})
    def fail(*args):raise PermissionError('locked')
    monkeypatch.setattr(publication.os, 'replace', fail)
    with pytest.raises(publication.PublicationError) as caught:
        publication.atomic_write_json(target, {'status':'completed'})
    assert json.loads(target.read_text()) == {'status':'previous'}
    assert json.loads(caught.value.recovery_path.read_text()) == {'status':'completed'}



def test_destination_race_keeps_file_exists_error_contract(tmp_path):
    source, target = tmp_path/'complete', tmp_path/'existing'
    source.write_bytes(b'complete');target.write_bytes(b'other writer')
    with pytest.raises(FileExistsError) as caught:
        publication.publish_new(source,target)
    assert isinstance(caught.value,publication.PublicationError)
    assert caught.value.recovery_path == source
    assert target.read_bytes() == b'other writer'
