"""Publication failures must never expose partial classification deliverables."""
import json
from pathlib import Path
import laspy
import numpy as np
import pytest
from pyargus.classify.recording import recorded_classification


def source(tmp_path):
    path = tmp_path / 'source.las'
    cloud = laspy.LasData(laspy.LasHeader(point_format=3, version='1.2'))
    cloud.x = np.arange(3.)
    cloud.y = np.arange(3.)
    cloud.z = np.arange(3.)
    cloud.write(path)
    return path


def record(tmp_path):
    return json.loads(next(tmp_path.glob('out.las.job-*.json')).read_text())


@pytest.mark.parametrize('failure', ['raise', 'cancel', 'truncated'])
def test_failed_output_is_not_published(tmp_path, failure):
    src = source(tmp_path)
    @recorded_classification
    def process(path, out):
        Path(out).write_bytes(b'incomplete')
        if failure == 'raise':
            raise RuntimeError('interrupted write')
        if failure == 'cancel':
            return {'cancelled': True}
        return {'total': 3}
    if failure == 'cancel':
        assert process(src, tmp_path/'out.las')['cancelled']
    else:
        with pytest.raises(Exception):
            process(src, tmp_path/'out.las')
    assert not (tmp_path/'out.las').exists()
    assert not list(tmp_path.glob('.pyargus-classify-*'))
    assert record(tmp_path)['status'] == ('cancelled' if failure == 'cancel' else 'failed')


def test_success_records_final_output_and_refuses_overwrite(tmp_path):
    src = source(tmp_path)
    @recorded_classification
    def process(path, out):
        laspy.read(path).write(out)
        return {'total': 3, 'points': (np.arange(3),)}
    out = tmp_path/'out.las'
    assert 'points' in process(src, out)
    data = record(tmp_path)
    assert data['status'] == 'completed'
    assert data['outputs'][0]['path'] == str(out.resolve())
    assert 'points' not in data['results']
    with pytest.raises(FileExistsError):
        process(src, out)


def test_target_created_during_processing_is_preserved(tmp_path):
    src = source(tmp_path)
    out = tmp_path/'out.las'
    @recorded_classification
    def process(path, staged):
        laspy.read(path).write(staged)
        out.write_bytes(b'another writer')
        return {'total': 3}
    with pytest.raises(FileExistsError):
        process(src, out)
    assert out.read_bytes() == b'another writer'
    assert record(tmp_path)['status'] == 'failed'


def test_source_mutation_prevents_publication(tmp_path):
    src = source(tmp_path)
    @recorded_classification
    def process(path, out):
        laspy.read(path).write(out)
        with Path(path).open('ab') as stream:
            stream.write(b'changed')
        return {'total': 3}
    with pytest.raises(ValueError, match='Input changed'):
        process(src, tmp_path/'out.las')
    assert not (tmp_path/'out.las').exists()
    assert record(tmp_path)['status'] == 'failed'


def test_count_mismatch_prevents_publication(tmp_path):
    src = source(tmp_path)
    @recorded_classification
    def process(path, out):
        laspy.read(path).write(out)
        return {'total': 4}
    with pytest.raises(ValueError, match='point count'):
        process(src, tmp_path/'out.las')
    assert not (tmp_path/'out.las').exists()


def test_cancellation_after_write_prevents_publication(tmp_path):
    src = source(tmp_path)
    @recorded_classification
    def process(path, out, *, should_stop=None):
        laspy.read(path).write(out)
        return {'total': 3}
    assert process(src, tmp_path/'out.las', should_stop=lambda: True)['cancelled']
    assert not (tmp_path/'out.las').exists()
    assert record(tmp_path)['status'] == 'cancelled'


def test_classification_record_opens_in_review(tmp_path):
    from pyargus.review import load_review, review_rows
    src = source(tmp_path)
    @recorded_classification
    def classify_ground_whole(path, out):
        laspy.read(path).write(out)
        return {'total': 3, 'ground': 2, 'ground_fraction': 2/3}
    classify_ground_whole(src, tmp_path/'out.las')
    data = load_review(next(tmp_path.glob('out.las.job-*.json')))
    rows = {row['label']: row for row in review_rows(data)}
    assert rows['Ground points']['after'] == 2
    assert 'not accuracy' in rows['Ground fraction']['note']
