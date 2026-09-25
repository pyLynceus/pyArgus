import json
import time
import numpy as np
import pytest
import laspy
from pyargus.classify import job
from tests.test_gui import application, root
from tests.test_review_workspace import cloud, wait


def noisy_cloud(path):
    data=laspy.LasData(laspy.LasHeader(point_format=6,version='1.4'))
    x,y=np.meshgrid(np.arange(15.),np.arange(15.))
    data.x=np.r_[x.ravel(),7,7];data.y=np.r_[y.ravel(),7,7]
    data.z=np.r_[np.full(x.size,100.),-100,500]
    data.return_number=np.ones(x.size+2,dtype=np.uint8)
    data.number_of_returns=np.ones(x.size+2,dtype=np.uint8)
    codes=np.zeros(x.size+2,dtype=np.uint8);codes[0]=7;codes[1]=18
    data.classification=codes;data.write(path)


def test_noise_excluded_and_preserved_whole_and_tiled(tmp_path):
    src=tmp_path/'src.las';noisy_cloud(src)
    # 2 of 227 points screened is 0.9%: far above the 0.1% default budget
    # that stops a window from catching the site, so raised here on purpose
    params=dict(cell=1.,window=3.,threshold=.5,noise_min=90.,noise_max=110.,
                noise_max_fraction=.02,log=lambda _:None)
    a,b=tmp_path/'whole.las',tmp_path/'tiled.las'
    job.classify_ground_whole(src,a,**params)
    job.classify_ground_tiled(src,b,tile_size=1000,**params)
    first,second=laspy.read(a),laspy.read(b)
    np.testing.assert_array_equal(first.classification,second.classification)
    assert list(np.asarray(first.classification)[[0,1,-2,-1]])==[7,18,7,18]
    assert np.all(np.asarray(first.classification)[2:-2]==2)
    original=laspy.read(src)
    for name in ('X','Y','Z','return_number','number_of_returns'):
        np.testing.assert_array_equal(first[name],original[name])
    assert list(np.asarray(original.classification)[-2:])==[0,0]


def test_noise_stays_excluded_even_with_any_return():
    points=dict(x=np.arange(4),z=np.ones(4),classification=np.array([7,18,0,0]),
                return_number=np.ones(4),number_of_returns=np.array([1,1,2,1]))
    assert job.candidates(points).tolist()==[False,False,False,True]
    assert job.candidates(points,True).tolist()==[False,False,True,True]
    with pytest.raises(ValueError):job.validate_noise_bounds(110,90)
    with pytest.raises(ValueError):job.validate_noise_bounds(float('nan'),None)


def pump(app,w):
    deadline=time.monotonic()+25
    while w.classify_batch['status']=='Running' and time.monotonic()<deadline:
        app.root.update();time.sleep(.01)
    assert w.classify_batch['status']!='Running'
    if w.viewer.busy:wait(app.root,w.viewer)


def test_batch_classifies_sequentially_and_keeps_duplicate_stems(application,tmp_path):
    app=application;w=app.workspace;paths=[]
    for name in ('first','second'):
        folder=tmp_path/name;folder.mkdir();path=folder/'flight.las';cloud(path);paths.append(str(path))
    w.project_panel.clouds=paths.copy();w.sync_project_layers()
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    stage.batch_dir.set(str(tmp_path));stage.cell.set('1');stage.window.set('3')
    w.start_classify_batch();pump(app,w)
    batch=w.classify_batch
    assert batch['status']=='Completed'
    assert [i['status'] for i in batch['items']]==['Needs review','Needs review']
    outputs=[i['output'] for i in batch['items']]
    assert len(set(outputs))==2 and w.project_panel.clouds==outputs
    assert all(i['records'] for i in batch['items'])
    assert json.loads(__import__('pathlib').Path(batch['manifest']).read_text())['status']=='Completed'


@pytest.mark.parametrize('cancel',[False,True])
def test_batch_stops_and_keeps_unstarted_flights(application,tmp_path,monkeypatch,cancel):
    app=application;w=app.workspace;paths=[]
    for name in ('a.las','b.las'):
        path=tmp_path/name;cloud(path);paths.append(str(path))
    w.project_panel.clouds=paths.copy()
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage');stage.batch_dir.set(str(tmp_path))
    def fail(*a,**k):
        if cancel:
            app.runner.cancel();return {'cancelled':True}
        raise RuntimeError('injected failure')
    monkeypatch.setattr(job,'classify_ground_whole',fail)
    w.start_classify_batch();pump(app,w)
    assert w.classify_batch['status']=='Stopped'
    assert w.classify_batch['items'][0]['status']==('Cancelled' if cancel else 'Failed')
    assert w.classify_batch['items'][1]['status']=='Waiting'
    assert w.project_panel.clouds==paths


def test_batch_second_failure_retains_first_result(application,tmp_path,monkeypatch):
    app=application;w=app.workspace;paths=[]
    for name in ('a.las','b.las'):
        path=tmp_path/name;cloud(path);paths.append(str(path))
    w.project_panel.clouds=paths.copy()
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    stage.batch_dir.set(str(tmp_path));stage.cell.set('1');stage.window.set('3')
    real=job.classify_ground_whole
    def classify(path,*args,**kwargs):
        if str(path)==paths[1]:raise RuntimeError('second flight failed')
        return real(path,*args,**kwargs)
    monkeypatch.setattr(job,'classify_ground_whole',classify)
    w.start_classify_batch();pump(app,w)
    first,second=w.classify_batch['items']
    assert w.classify_batch['status']=='Stopped'
    assert first['status']=='Needs review' and second['status']=='Failed'
    assert __import__('pathlib').Path(first['output']).is_file()
    assert not __import__('pathlib').Path(second['output']).exists()
    assert w.project_panel.clouds==[first['output'],paths[1]]


def test_the_three_fraction_defaults_are_one_number(application):
    """noise-cut's --max-fraction, classify-ground's --noise-max-fraction,
    the desktop field and the text the workspace compares against must
    not drift apart."""
    from pyargus import cli
    from pyargus.classify import noise
    from pyargus.workspace_state import NOISE_MAX_FRACTION_TEXT

    stage=next(s for s in application.stages if type(s).__name__=='ClassifyStage')
    parser=cli.build_parser()
    assert parser.parse_args(['classify-ground','a','--out','b']).noise_max_fraction==noise.DEFAULT_MAX_FRACTION
    assert parser.parse_args(['noise-cut','a','--out','b']).max_fraction==noise.DEFAULT_MAX_FRACTION
    assert job.NOISE_MAX_FRACTION==noise.DEFAULT_MAX_FRACTION
    assert stage.noise_max_fraction.get()==NOISE_MAX_FRACTION_TEXT
    assert float(NOISE_MAX_FRACTION_TEXT)==noise.DEFAULT_MAX_FRACTION


def test_classify_stage_passes_the_fraction_and_refuses_a_bad_one(application,tmp_path,monkeypatch):
    from tests.test_gui import _FakeRunner

    app=application
    src=tmp_path/'src.las';cloud(src);app.cloud_path.set(str(src))
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    stage.out_path.set(str(tmp_path/'out.las'));stage.noise_max.set('500')
    seen={}
    def capture(path,out,**kwargs):
        seen.update(kwargs);return {'cancelled':True}
    monkeypatch.setattr(job,'classify_ground_whole',capture)
    stage.noise_max_fraction.set('0.02')
    stage.prepare()(_FakeRunner())
    assert seen['noise_max_fraction']==0.02 and seen['noise_max']==500.
    for bad in ('0','1.5','nan','lots'):
        stage.noise_max_fraction.set(bad)
        with pytest.raises(ValueError,match='[Ff]raction'):
            stage.prepare()


def test_batch_refuses_a_bad_fraction_before_making_its_folder(application,tmp_path,monkeypatch):
    from pyargus import workspace_gui

    app=application;w=app.workspace
    path=tmp_path/'a.las';cloud(path);w.project_panel.clouds=[str(path)]
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    stage.batch_dir.set(str(tmp_path));stage.noise_max.set('500');stage.noise_max_fraction.set('0')
    said=[]
    monkeypatch.setattr(workspace_gui.messagebox,'showerror',lambda *a,**k:said.append(a))
    w.start_classify_batch()
    assert said and 'fraction' in said[0][1].lower()
    assert not list(tmp_path.glob('classification_*'))


def test_a_workspace_saved_before_the_fraction_field_restores_the_default(application,tmp_path):
    """restore() set only the fields a saved workspace names, so a field
    it predates kept whatever the previously open workspace held -- and
    its windowed jobs then read as outdated against that value."""
    app=application;w=app.workspace
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    w.path=tmp_path/'saved.json';w.persist()
    data=json.loads(w.path.read_text(encoding='utf-8'))
    data['settings']['ClassifyStage'].pop('noise_max_fraction')
    w.path.write_text(json.dumps(data),encoding='utf-8')
    stage.noise_max_fraction.set('0.5')      # what the last workspace left
    w.restore(w.path)
    assert stage.noise_max_fraction.get()=='0.001'
