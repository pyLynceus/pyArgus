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
    params=dict(cell=1.,window=3.,threshold=.5,noise_min=90.,noise_max=110.,log=lambda _:None)
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
