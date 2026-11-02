"""An LP360 stage never publishes partial products or mislabels a committed stage."""
import json
from pathlib import Path
import pytest
from pyargus import lp360_workflow as workflow
from pyargus.publication import PublicationError
from tests.test_lp360_jobs import job


@pytest.mark.parametrize('which', ['surface', 'contours', 'delivery'])
def test_stage_write_failure_leaves_no_partial_final_folder(job, tmp_path, monkeypatch, which):
    _, _, recipe = job
    out = tmp_path/'run'
    if which == 'surface':
        from pyargus.surfaces import dtm
        actual = dtm.write_esri_ascii
        def fail(*args, **kwargs):
            actual(*args, **kwargs);raise OSError('injected surface failure')
        monkeypatch.setattr(dtm, 'write_esri_ascii', fail)
    elif which == 'contours':
        from pyargus.formats import dxf
        actual = dxf.write_contours_dxf
        def fail(*args, **kwargs):
            actual(*args, **kwargs);raise OSError('injected contour failure')
        monkeypatch.setattr(dxf, 'write_contours_dxf', fail)
    else:
        actual = workflow.shutil.copy2
        def fail(source, dest, *args, **kwargs):
            value = actual(source, dest, *args, **kwargs)
            if Path(dest).parent.name == 'final_clouds':raise OSError('injected delivery failure')
            return value
        monkeypatch.setattr(workflow.shutil, 'copy2', fail)
    with pytest.raises(OSError, match='injected'):
        workflow.run(recipe, out)
    final = 'final_clouds' if which == 'delivery' else which
    assert not (out/final).exists()
    assert not list(out.glob('.pyargus-*'))
    assert (out/'alignment'/'report.html').exists()
    assert json.loads((out/'run.json').read_text())['status'] == 'Failed'


def test_stop_inside_contour_write_publishes_no_contours(job, tmp_path, monkeypatch):
    from pyargus.formats import dxf
    _, _, recipe = job;out = tmp_path/'run';stop = [False]
    actual = dxf.write_contours_dxf
    def write(*args, **kwargs):
        result = actual(*args, **kwargs);stop[0] = True;return result
    monkeypatch.setattr(dxf, 'write_contours_dxf', write)
    result = workflow.run(recipe, out, cancel=lambda:stop[0])
    assert result['status'] == 'Cancelled'
    assert not (out/'contours').exists()
    assert not list(out.glob('.pyargus-*'))
    assert (out/'surface'/'summary.json').exists()


def test_stop_after_committed_stage_keeps_its_completed_state(job, tmp_path):
    _, _, recipe = job;out = tmp_path/'run';stop = [False]
    def event(entry):
        if entry['stage'] == 'Contours' and entry['status'].startswith('Completed'):
            stop[0] = True
    result = workflow.run(recipe, out, cancel=lambda:stop[0], on_stage=event)
    assert result['status'] == 'Cancelled'
    assert (out/'contours'/'summary.json').exists()
    state = json.loads((out/'run.json').read_text())
    stage = next(x for x in state['steps'] if x['stage'] == 'Contours')
    assert stage['status'].startswith('Completed') and stage['outputs']
    assert not any(x['stage'] == 'Final QA' for x in state['steps'])


def test_failed_contour_publication_retains_complete_recovery_folder(job, tmp_path, monkeypatch):
    _, _, recipe = job;out = tmp_path/'run'
    actual = workflow.publish_new
    def publish(source, target):
        if Path(target).name == 'contours':
            raise PublicationError(source, target, PermissionError('locked'))
        return actual(source, target)
    monkeypatch.setattr(workflow, 'publish_new', publish)
    with pytest.raises(PublicationError) as caught:
        workflow.run(recipe, out)
    assert (caught.value.recovery_path/'summary.json').exists()
    assert (caught.value.recovery_path/'contours.dxf').exists()
    assert not (out/'contours').exists()
    assert str(caught.value.recovery_path) in json.loads((out/'run.json').read_text())['error']
