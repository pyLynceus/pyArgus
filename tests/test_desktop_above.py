import numpy as np
import pytest
from tests.test_gui import application, root, _FakeRunner
from tests.synthetic import labeled_scene
from pyargus import gui
from pyargus.classify import above


def test_desktop_training_and_application(application, tmp_path):
    import laspy
    points, labels = labeled_scene(seed=4)
    header = laspy.LasHeader(point_format=6, version='1.4')
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    for name, values in points.items():
        data[name] = values
    data.classification = labels
    src = tmp_path / 'labeled.las'
    data.write(src)
    stage = _stage_of(application, gui.AboveStage)
    application.cloud_path.set(str(src))
    stage.mode.set('Train model')
    stage.cell.set('2.0')
    model_path = tmp_path / 'model.joblib'
    stage.out_path.set(str(model_path))
    runner = _FakeRunner()
    work = stage.prepare()
    stage.cell.set('99')  # preparation captures settings before the worker
    work(runner)
    assert above.load(model_path).feature_cell == 2.0
    application._adopt_products(runner)
    assert stage.mode.get() == 'Apply model'
    assert stage.model_path.get() == str(model_path)
    bare = tmp_path / 'bare.las'
    data.classification = np.where(labels == 2, 2, 1).astype(np.uint8)
    data.write(bare)
    stage.cloud_override.set(str(bare))
    out = tmp_path / 'full.las'
    stage.out_path.set(str(out))
    stage.prepare()(_FakeRunner())
    result = laspy.read(out)
    assert (np.asarray(result.classification)[labels == 2] == 2).all()
    assert (np.asarray(result.classification)[labels != 2] == labels[labels != 2]).mean() > .9
    assert np.array_equal(result.X, data.X)
    with pytest.raises(ValueError, match='exists'):
        stage.prepare()
    stage.out_path.set(str(tmp_path / 'wrong.las'))
    stage.units.set('metres')
    with pytest.raises(ValueError, match='units'):
        stage.prepare()(_FakeRunner())


def test_cancel_before_training_writes_nothing(application, tmp_path):
    src = tmp_path / 'source.las'
    src.write_bytes(b'not read when cancelled')
    application.cloud_path.set(str(src))
    stage = _stage_of(application, gui.AboveStage)
    stage.mode.set('Train model')
    out = tmp_path / 'model.joblib'
    stage.out_path.set(str(out))
    runner = _FakeRunner()
    runner.cancelled = lambda: True
    stage.prepare()(runner)
    assert not out.exists()
    assert not runner.products


def _stage_of(application, stage_class):
    """Pick a stage BY TYPE. Positional lookup breaks the moment a
    stage is added, which is how adding Colorize broke these."""
    for stage in application.stages:
        if isinstance(stage, stage_class):
            return stage
    raise AssertionError(f'no {stage_class.__name__} registered')
