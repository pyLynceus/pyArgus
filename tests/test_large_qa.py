import json
import sqlite3
from dataclasses import replace
import numpy as np
import pytest
from pyargus import project
from pyargus.large_qa import Store,qa
from tests.test_project import scene


def test_disk_medians_cross_chunks_and_tile_edges(tmp_path):
    s=Store(tmp_path/'scratch.db',lambda:False,lambda x:None)
    try:
        # Both signs of tile boundary, duplicate returns across chunks, even/odd medians.
        for x in (-1536.,-1535.,1535.,1536.,1537.):
            for sid,z in [(1,[10,12,100]),(2,[12,14,16,18])]:
                for value in z:
                    p=dict(x=np.array([x]),y=np.array([1.]),z=np.array([value]),
                        classification=np.array([2]),point_source_id=np.array([sid]))
                    s.ingest(p,np.array([-1]))
        s.reduce()
        rows=s.db.execute('SELECT x,dz FROM dz ORDER BY x').fetchall()
        assert rows==[(-256,3.),(255,3.),(256,3.)]
        assert s.db.execute('SELECT sum(n) FROM density').fetchone()[0]==35
    finally: s.db.close()


def test_automatic_large_project_matches_in_memory_statistics(scene,tmp_path):
    small=project.qa(scene,tmp_path/'small')
    large=project.qa(replace(scene,max_points=1),tmp_path/'large')
    assert large['mode']=='disk-backed'
    assert large['points']==small['points'] and large['ground_points']==small['ground_points']
    # Fixture does not land on the outermost cell edge; exact parity is expected.
    for key in ('median','p5','p95','covered_cells'):
        assert large['density'][key]==pytest.approx(small['density'][key])
    assert len(large['strip_dz'])==len(small['strip_dz'])
    for a,b in zip(large['strip_dz'],small['strip_dz']):
        for key in ('median','rmse','p95_abs','cells'): assert a[key]==pytest.approx(b[key])
    assert json.loads((tmp_path/'large/inventory.json').read_text())['unmatched']==0
    assert (tmp_path/'large/tiles.json').exists()
    assert not list(tmp_path.glob('.pyargus-large-qa-*'))
    assert not (tmp_path/'large/scratch.sqlite').exists()


def test_cancel_removes_scratch_and_never_publishes(scene,tmp_path):
    calls=0
    def cancel():
        nonlocal calls
        calls+=1
        return calls>4
    with pytest.raises(project.Cancelled): qa(scene,tmp_path/'cancelled',cancel=cancel)
    assert not (tmp_path/'cancelled').exists()
    assert not list(tmp_path.glob('.pyargus-large-qa-*'))


def test_missing_matches_refuse_before_publication(scene,tmp_path):
    changed=replace(scene,trajectories=scene.trajectories[:1])
    with pytest.raises(ValueError,match='unresolved trajectory'): qa(changed,tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def test_low_disk_space_refuses_before_scan(scene,tmp_path,monkeypatch):
    import shutil
    monkeypatch.setattr(shutil,'disk_usage',lambda p:shutil._ntuple_diskusage(100,99,1))
    with pytest.raises(ValueError,match='scratch disk space'): qa(scene,tmp_path/'low')
    assert not (tmp_path/'low').exists()


def test_control_disk_median_and_empty_ground(scene,tmp_path):
    import laspy
    d=laspy.read(scene.clouds[0])
    control=(['mark'],np.array([float(d.x[0])]),np.array([float(d.y[0])]),np.array([float(d.z[0])]))
    a=project.qa(scene,tmp_path/'csmall',control=control)
    b=qa(scene,tmp_path/'clarge',control=control)
    assert b['control']['residuals']==pytest.approx(a['control']['residuals'])
    for path in scene.clouds:
        data=laspy.read(path); data.classification=np.ones(len(data.points),dtype='uint8'); data.write(path)
    result=qa(scene,tmp_path/'noground')
    assert result['ground_points']==0 and result['strip_dz']==[]


def test_sql_reduction_can_be_interrupted(tmp_path):
    stopped=False
    store=Store(tmp_path/'cancel.db',lambda:stopped,lambda s:None)
    try:
        store.db.executemany('INSERT INTO ground VALUES(?,?,?,?)',((i//10,0,1,float(i)) for i in range(20000)))
        store.db.commit(); stopped=True
        with pytest.raises(sqlite3.OperationalError,match='interrupted'): store.reduce()
    finally: store.db.close()


def test_input_change_during_reduction_refuses_publication(scene,tmp_path,monkeypatch):
    original_reduce=Store.reduce
    original_unchanged=project._unchanged
    reduced=False
    def changed(self):
        nonlocal reduced
        original_reduce(self); reduced=True
    def metadata_check(metadata):
        if reduced:
            # Change only the expected in-memory size, leaving every LAS file alone.
            original_unchanged(dict(metadata,size=metadata['size']+1))
        else: original_unchanged(metadata)
    monkeypatch.setattr(Store,'reduce',changed)
    monkeypatch.setattr(project,'_unchanged',metadata_check)
    with pytest.raises(ValueError,match='input changed'): qa(scene,tmp_path/'changed')
    assert not (tmp_path/'changed').exists()
    assert not list(tmp_path.glob('.pyargus-large-qa-*'))
