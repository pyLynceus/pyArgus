import json
import os
import pytest
from tests.test_cli_colorize import scene
from pyargus.imagery.job import colorize_cloud
from pyargus.formats import las


def record(out):
    return json.loads(next(out.parent.glob(out.name+'.job-*.json')).read_text())


@pytest.mark.parametrize('input_kind', ['cloud', 'eo', 'calibration', 'image'])
def test_inputs_changed_between_projection_and_writing_are_refused(scene, tmp_path, monkeypatch, input_kind):
    from pyargus.imagery import colorize as module
    cloud, eo, images, _ = scene
    path = {'cloud':cloud, 'eo':eo, 'calibration':images/'0001.png.cal', 'image':images/'0001.png'}[input_kind]
    original = module.colorize
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if input_kind == 'eo':
            stamp = path.stat();content = path.read_bytes()
            path.write_bytes(content.replace(b'100.0,', b'101.0,', 1))
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        else:
            with path.open('ab') as stream:stream.write(b' ')
        return result
    monkeypatch.setattr(module, 'colorize', changed)
    out = tmp_path/'rgb.las'
    with pytest.raises(ValueError, match='changed during colorization'):
        colorize_cloud(cloud, eo, images, out, quarter_turns=0)
    assert not out.exists()
    assert record(out)['status'] == 'failed'


def test_cloud_change_during_second_read_does_not_replace_destination(scene, tmp_path, monkeypatch):
    cloud, eo, images, _ = scene
    original = las.preserving_writer
    from contextlib import contextmanager
    @contextmanager
    def changed(*args, **kwargs):
        with original(*args, **kwargs) as writer:
            yield writer
        with cloud.open('ab') as stream:stream.write(b'changed')
    monkeypatch.setattr(las, 'preserving_writer', changed)
    out = tmp_path/'rgb.las';out.write_bytes(b'existing destination')
    with pytest.raises(ValueError, match='changed during colorization'):
        colorize_cloud(cloud, eo, images, out, quarter_turns=0)
    assert out.read_bytes() == b'existing destination'
    assert not list(tmp_path.glob('rgb.las.*.partial'))
