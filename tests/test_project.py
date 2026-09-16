"""Multi-file tests use independent native fixtures, never Z: inputs."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import struct

import numpy as np
import pytest
import laspy
from pyproj import CRS

from pyargus import project
from tests.test_gui import root

BASE = 436024721.


def track_file(path, line, *, begin=BASE, reverse=False, gap=False):
    t = begin + np.arange(101)*.1
    if gap: t = t[(t<begin+3)|(t>begin+7)]
    rows = [(v,1000+(100-(v-begin)*10 if reverse else (v-begin)*10),
             2000.,300.,270. if reverse else 90.,0.,0.) for v in t]
    header=bytearray(1376)
    struct.pack_into('<8s4i',header,0,b'TSCANTRJ',20010715,1376,len(rows),64)
    struct.pack_into('<2d2i',header,104,t[0],t[-1],line,line)
    path.write_bytes(header+b''.join(struct.pack('<7d4B2h',*r,0,0,0,0,0,0) for r in rows))
    return str(path)


def cloud_file(path, x, y, z, times, ids, *, crs='EPSG:6447', gps_type=1):
    header=laspy.LasHeader(point_format=8,version='1.4')
    header.scales=np.array([.001,.001,.001])
    header.global_encoding.gps_time_type=gps_type
    if crs: header.add_crs(CRS(crs))
    header.add_extra_dim(laspy.ExtraBytesParams(name='custom',type=np.int16))
    d=laspy.LasData(header)
    d.x,d.y,d.z=x,y,z
    d.gps_time=times; d.point_source_id=np.asarray(ids,dtype=np.uint16)
    d.classification=np.full(len(x),2,dtype=np.uint8)
    d.intensity=np.arange(len(x),dtype=np.uint16)
    d.red=np.full(len(x),1234,dtype=np.uint16); d.custom=np.full(len(x),17,dtype=np.int16)
    d.write(path)
    return str(path)


@pytest.fixture
def scene(tmp_path):
    t1=track_file(tmp_path/'one.trj',1)
    t2=track_file(tmp_path/'two.trj',2,begin=BASE+20,reverse=True)
    x,y=np.meshgrid(np.arange(1005.,1086.,.5),np.arange(1996.,2004.,.5))
    x,y=x.ravel(),y.ravel()
    xs=np.tile(x,2); ys=np.tile(y,2)
    z=100+.02*(xs-1000)+.03*(ys-2000)+np.repeat([0.,.25],len(x))
    ids=np.repeat([1,2],len(x))
    times=np.concatenate([BASE+(x-1000)/10,BASE+20+(1100-x)/10])
    clouds=[]
    for index,mask in enumerate((xs<1045,xs>=1045)):
        folder=tmp_path/str(index); folder.mkdir()
        clouds.append(cloud_file(folder/'tile.las',xs[mask],ys[mask],z[mask],times[mask],ids[mask]))
    return project.Project(clouds,[project.TrajectoryInput(t1,'same',confirmed=True),
                                   project.TrajectoryInput(t2,'same',confirmed=True)],same_vertical=True)


def test_tiles_of_same_flight_unify_without_rewriting_ids(scene):
    d=project.load(scene,keep_points=True)
    assert d.inventory['matched']==d.inventory['points']
    assert len(d.inventory['strips'])==2
    assert all(len(s['clouds'])==2 for s in d.inventory['strips'])
    np.testing.assert_array_equal(d.points['original_point_source_id'],
        np.concatenate([laspy.read(p).point_source_id for p in scene.clouds]))


def test_reused_ids_on_separate_flights_stay_separate(tmp_path):
    clouds=[]; tracks=[]
    for i in range(2):
        begin=BASE+i*20
        p=track_file(tmp_path/f'{i}.trj',7,begin=begin)
        tracks.append(project.TrajectoryInput(p,'same'))
        clouds.append(cloud_file(tmp_path/f'{i}.las',np.arange(20.)+1000,
            np.full(20,2000.),np.full(20,100.),begin+np.arange(20.)*.1,np.full(20,7)))
    d=project.load(project.Project(clouds,tracks,same_vertical=True),keep_points=True)
    assert len(d.inventory['strips'])==2
    assert {s['source_id'] for s in d.inventory['strips']}=={7}
    assert len(np.unique(d.points['point_source_id']))==2


def test_ambiguity_is_reported_and_refused_not_first_match(scene,tmp_path):
    copy=tmp_path/'duplicate.trj'
    copy.write_bytes(Path(scene.trajectories[0].path).read_bytes())
    spec=replace(scene,trajectories=scene.trajectories+[project.TrajectoryInput(str(copy),'same',confirmed=True)])
    d=project.load(spec)
    assert d.inventory['ambiguous']>0
    with pytest.raises(ValueError,match='ambiguous'):
        project.align(spec,tmp_path/'refused',solve_boresight=False)
    assert not (tmp_path/'refused').exists()
    with pytest.raises(ValueError,match='unresolved trajectory matches'):
        project.qa(spec,tmp_path/'qa_refused')
    assert not (tmp_path/'qa_refused').exists()


def test_binding_resolves_overlapping_trajectories(tmp_path):
    tracks=[project.TrajectoryInput(track_file(tmp_path/f'{i}.trj',1),'same') for i in range(2)]
    clouds=[cloud_file(tmp_path/f'{i}.las',np.arange(20.)+1000,np.full(20,2000),
            np.full(20,100),BASE+np.arange(20.)*.1,np.ones(20)) for i in range(2)]
    spec=project.Project(clouds,tracks,same_vertical=True)
    assert project.load(spec).inventory['ambiguous']==40
    spec.bindings=dict(zip(clouds,[t.path for t in tracks]))
    d=project.load(spec)
    assert d.inventory['matched']==40 and len(d.inventory['strips'])==2


def test_internal_gap_and_wrong_line_are_unmatched(scene,tmp_path):
    t=track_file(tmp_path/'gap.trj',1,gap=True)
    spec=replace(scene,trajectories=[project.TrajectoryInput(t,'same'),scene.trajectories[1]])
    d=project.load(spec)
    assert d.inventory['unmatched']>0 and d.inventory['trajectories'][0]['gaps']==1
    t=track_file(tmp_path/'wrong.trj',99)
    d=project.load(replace(scene,trajectories=[project.TrajectoryInput(t,'same')]))
    assert d.inventory['matched']==0


@pytest.mark.parametrize('fault',['duplicate','crs','untagged','week','zero','limit','vertical'])
def test_project_refusals(scene,tmp_path,fault):
    expected=''
    if fault=='duplicate': scene.clouds.append(scene.clouds[0]); expected='duplicate'
    elif fault in ('crs','untagged','week','zero'):
        p=scene.clouds[0]; d=laspy.read(p)
        if fault=='crs': d.header.add_crs(CRS('EPSG:26916')); expected='CRS mismatch'
        elif fault=='untagged':
            d.header.vlrs.clear(); expected='no CRS'
        elif fault=='week': d.header.global_encoding.gps_time_type=0; expected='GPS week'
        else: d.point_source_id=np.zeros(len(d.points),dtype=np.uint16); expected='flight-line'
        d.write(p)
    elif fault=='limit': scene.max_points=1; expected='point.*limit|analysis limit'
    else: scene.same_vertical=False; expected='vertical datum'
    with pytest.raises(ValueError,match=expected): project.load(scene,keep_points=True)


def test_inventory_streams_above_analysis_limit(scene):
    scene.max_points=1
    assert project.load(scene).points is None


def test_no_trajectory_repeated_ids_need_explicit_namespace(scene):
    scene.trajectories=[]
    with pytest.raises(ValueError,match='repeat across clouds'): project.load(scene)
    scene.shared_strip_ids=True
    assert len(project.load(scene).inventory['strips'])==2


def test_confirmation_strings_are_not_booleans(scene):
    scene.trajectories[0].confirmed='false'
    with pytest.raises(ValueError,match='boolean'): project.load(scene)


def test_sbet_week_times_match_adjusted_las(scene,tmp_path):
    from pyargus.formats.sbet import RECORD_DTYPE
    week=int((BASE+1e9)//604800)
    tracks=[]
    for i in range(2):
        d=np.zeros(101,dtype=RECORD_DTYPE)
        d['time']=BASE+i*20+np.arange(101)*.1+1e9-week*604800
        p=tmp_path/f'{i}.out'; d.tofile(p)
        tracks.append(project.TrajectoryInput(str(p),'week',gps_week=week))
    assert project.load(replace(scene,trajectories=tracks)).inventory['unmatched']==0


def test_sbet_vertical_units_must_match_cloud_xyz(scene,tmp_path):
    from pyargus.formats.sbet import RECORD_DTYPE
    week=int((BASE+1e9)//604800)
    data=np.zeros(401,dtype=RECORD_DTYPE)
    data['time']=BASE-(week*604800-1e9)+np.arange(401)*.1
    path=tmp_path/'whole.out'; data.tofile(path)
    spec=replace(scene,trajectories=[project.TrajectoryInput(str(path),'week',gps_week=week)],
                 vertical='EPSG:5703')  # meters, while the LAS uses US survey feet
    with pytest.raises(ValueError,match='vertical CRS units differ'):
        project.align(spec,tmp_path/'wrong_units',solve_boresight=False)
    assert not (tmp_path/'wrong_units').exists()


def test_manifest_roundtrip_and_cli(scene,tmp_path,capsys):
    from pyargus.cli import main
    p=tmp_path/'project.json'; scene.save(p)
    restored=project.Project.load(p)
    assert restored==scene
    assert main(['project-info',str(p)])==0
    assert 'ambiguous' in capsys.readouterr().out
    with pytest.raises(FileExistsError): scene.save(p)


def test_qa_cross_file_pairs_and_provenance(scene,tmp_path):
    out=tmp_path/'qa'
    result=project.qa(scene,out)
    assert len(result['strip_dz'])==1
    assert abs(result['strip_dz'][0]['median']-.25)<.001
    assert (out/'project.json').exists() and (out/'inventory.json').exists()
    assert 'LAS line ID' in (out/'report.html').read_text(encoding='utf-8')


def test_alignment_exports_per_source_and_preserves_every_other_dimension(scene,tmp_path):
    before={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in scene.clouds}
    out=tmp_path/'aligned'
    result=project.align(scene,out,solve_boresight=False,cell=6.,min_points=6)
    assert len(result['outputs'])==2
    assert len({p['output'] for p in result['outputs']})==2  # identical input basenames
    for entry in result['outputs']:
        source=laspy.read(entry['source']); dest=laspy.read(out/entry['output'])
        for name in source.points.array.dtype.names:
            if name not in ('X','Y','Z'):
                np.testing.assert_array_equal(source.points.array[name],dest.points.array[name])
        expected=np.where(source.point_source_id==2,-.25,0)
        np.testing.assert_allclose(np.asarray(dest.z)-np.asarray(source.z),expected,atol=.002)
        assert hashlib.sha256(Path(entry['source']).read_bytes()).hexdigest()==before[entry['source']]
    assert (out/'before/report.html').exists() and (out/'after/report.html').exists()
    with pytest.raises(ValueError,match='already exists'): project.align(scene,out)


def test_cancel_does_not_publish_output(scene,tmp_path):
    with pytest.raises(project.Cancelled): project.qa(scene,tmp_path/'cancelled',cancel=lambda:True)
    assert not (tmp_path/'cancelled').exists()


def test_changed_trajectory_during_alignment_refuses(scene,tmp_path,monkeypatch):
    original=project.trajectory.load_alignment
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        p=Path(args[0]); p.write_bytes(p.read_bytes()+b'!')
        return result
    monkeypatch.setattr(project.trajectory,'load_alignment',changed)
    with pytest.raises(ValueError,match='trajectory changed'):
        project.align(scene,tmp_path/'changed',solve_boresight=False)
    assert not (tmp_path/'changed').exists()


def test_project_window_bulk_selection_and_snapshot(scene,monkeypatch):
    import tkinter as tk
    from pyargus.gui import Application
    from pyargus.project_gui import open_project
    root=tk.Tk(); root.withdraw()
    try:
        app=Application(root); w=open_project(app)
        w.window.update_idletasks()
        w.add_paths(scene.clouds,False); w.add_paths(scene.clouds,False)
        w.add_paths([t.path for t in scene.trajectories],True)
        assert len(w.clouds)==2 and len(w.tracks)==2
        w.track_box.select_set(0,'end'); w.track_time.set('same'); w.apply_track_settings()
        assert all(t.time_mode=='same' and not t.confirmed for t in w.tracks)
        w.same_vertical.set(True)
        assert project.load(w.snapshot()).inventory['matched']>0
        assert open_project(app) is w
        w.inventory=project.load(w.snapshot()).inventory; w.show_inventory()
        assert len(w.result_tree.get_children())==2
    finally: root.destroy()


def test_project_window_runs_qa_in_job_runner(scene,tmp_path,root):
    import gc
    from pyargus.gui import Application
    from pyargus.project_gui import open_project
    try:
        app=Application(root); w=open_project(app); w.window.update_idletasks()
        w.clouds,w.tracks=scene.clouds,scene.trajectories
        w.same_vertical.set(True); w.out.set(str(tmp_path/'gui_qa'))
        gc.collect()  # Finalize prior tests' destroyed Tk roots on the main thread.
        w.start('qa')
        def completed():
            if not app.runner.running and (w.inventory is not None or app.runner.error is not None):
                root.quit()
            else: root.after(50,completed)
        root.after(50,completed)
        root.after(20000,root.quit)
        root.mainloop()
        assert app.runner.error is None and app.runner.status=='Finished'
        assert (tmp_path/'gui_qa/report.html').exists()
        assert app.runner.report.ndim==3 and app.runner.report.shape[2]==4
        assert w.inventory['matched']==w.inventory['points']
        assert len(w.result_tree.get_children())==2
    finally:
        for event in root.tk.call('after','info'):
            root.tk.call('after','cancel',event)


def test_unset_time_is_highlighted_and_bulk_apply_preserves_approval(scene,root):
    from pyargus.gui import Application
    from pyargus.project_gui import open_project
    app=Application(root); w=open_project(app); w.window.update_idletasks()
    w.add_paths([t.path for t in scene.trajectories],True)
    with pytest.raises(ValueError,match='need a time base'): w.check_time_settings()
    assert len(w.track_box.curselection())==len(w.tracks)
    w.track_time.set('same'); w.track_confirm.set(True)
    w.apply_all_time()
    assert all(t.time_mode=='same' and not t.confirmed for t in w.tracks)
    w.check_time_settings()
    assert len(w.track_box.curselection())==len(w.tracks)
    assert 'NEED TIME' not in w.counts.get()
