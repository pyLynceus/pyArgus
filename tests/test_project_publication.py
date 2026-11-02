from dataclasses import replace
import hashlib
import json
from pathlib import Path
import laspy
import pytest
from pyargus import project,publication
from pyargus.formats.las import assert_extra_bytes_preserved
from tests.test_project import scene


@pytest.mark.parametrize('operation', ['qa','large_qa','align'])
def test_final_publication_failure_retains_verified_project_outputs(scene, tmp_path, monkeypatch, operation):
    target = tmp_path/'result'
    hashes = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in scene.clouds}
    actual = publication._rename_new
    def locked(source, dest):
        if dest.resolve() == target.resolve():raise PermissionError('final target locked')
        return actual(source, dest)
    monkeypatch.setattr(publication, '_rename_new', locked)
    monkeypatch.setattr(publication, 'RETRY_DELAYS', (0.,))
    with pytest.raises(publication.PublicationError) as caught:
        if operation == 'align':project.align(scene,target,solve_boresight=False)
        else:project.qa(replace(scene,max_points=1) if operation == 'large_qa' else scene,target)
    recovery = caught.value.recovery_path
    assert recovery.is_dir()
    assert (recovery/'report.html').is_file()
    assert not target.exists()
    record = json.loads(next(tmp_path.glob('result.job-*.json')).read_text())
    assert record['status'] == 'failed'
    assert record['recovery_path'] == str(recovery)
    if operation == 'align':
        outputs = list(recovery.glob('*.las'))
        assert len(outputs) == len(scene.clouds)
        for source,destination in zip(scene.clouds,sorted(outputs)):
            assert_extra_bytes_preserved(laspy.read(source).header,laspy.read(destination).header)
        assert (recovery/'before/report.html').is_file()
        assert (recovery/'after/report.html').is_file()
    assert {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in scene.clouds} == hashes
