import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace as E
import numpy as np
import pytest
import laspy
from pyargus.area_cleanup import AreaEditSession, extract_area, screen_to_map
from tests.test_editing import make_session
from tests.test_gui import root, application
from tests.test_review_workspace import cloud, wait


POLYGON = [[1002,1998],[1007,1998],[1007,2002],[1002,2002]]


@pytest.mark.parametrize('fmt,ext', [(3,'.las'),(6,'.laz')])
def test_area_changes_only_selected_classification_bytes(tmp_path,fmt,ext):
    source,_=make_session(tmp_path,fmt)
    original=source.read_bytes()
    area=extract_area(source,POLYGON,classes=[2],z_min=100.3,z_max=100.6,chunk_size=7)
    assert area.matched==20 and area.in_polygon==30
    assert area.point_indices.tolist()==sorted(area.point_indices.tolist())
    session=AreaEditSession(area);session.assign(np.arange(area.matched),1)
    session.undo();assert session.changed==0
    session.redo();assert session.changed==20
    output=tmp_path/('clean'+ext);record=session.export(output,chunk_size=11)
    expected=laspy.read(source);after=laspy.read(output)
    classes=np.asarray(expected.classification).copy();classes[area.point_indices]=1
    expected.classification=classes
    assert expected.points.array.tobytes()==after.points.array.tobytes()
    assert original==source.read_bytes()
    assert 'section' not in record and record['area']['full_resolution']
    assert record['area']['z_min']==100.3 and record['area']['class_filter']==[2]
    assert record['changed']==20 and record['points']==100
    sidecar=json.loads(output.with_suffix(ext+'.edits.json').read_text(encoding='utf-8'))
    assert [e['point_index'] for e in sidecar['edits']]==area.point_indices.tolist()


def test_concave_large_coordinate_area_and_explicit_line_filter(tmp_path):
    source,_=make_session(tmp_path)
    d=laspy.read(source);d.x=np.asarray(d.x)+2_000_000;d.y=np.asarray(d.y)+1_000_000
    d.point_source_id=np.where(np.asarray(d.y)<=1_002_000,8,9);d.write(source)
    polygon=np.asarray([[1002,1998],[1007,1998],[1007,2002],[1004,2002],[1004,2000],[1002,2000]])+[2_000_000,1_000_000]
    area=extract_area(source,polygon[::-1],line_id=8,chunk_size=13)
    assert area.matched==18 and area.in_polygon==26
    assert np.all(area.lines==8)
    assert np.all(area.points[:,1]<=1_002_000)


def test_empty_invalid_and_oversized_selections_never_become_sampled_edits(tmp_path):
    source,_=make_session(tmp_path)
    for options in [dict(classes=[]),dict(classes=[256]),dict(line_id=-1),dict(z_min=np.nan),dict(z_min=102,z_max=100),dict(limit=0)]:
        with pytest.raises(ValueError):extract_area(source,POLYGON,**options)
    with pytest.raises(ValueError,match='nonzero'):extract_area(source,[[0,0],[1,1],[2,2]])
    with pytest.raises(ValueError,match='No points'):extract_area(source,POLYGON,classes=[6])
    with pytest.raises(ValueError,match='no sampled edits'):extract_area(source,POLYGON,limit=5,chunk_size=3)
    assert sorted(p.name for p in tmp_path.iterdir())==['input.las']


def test_cancel_and_source_change_refuse_area_and_export(tmp_path):
    source,_=make_session(tmp_path);cancel=Event()
    def stop(s):cancel.set()
    with pytest.raises(InterruptedError):extract_area(source,POLYGON,cancel=cancel,progress=stop,chunk_size=7)
    cancel.clear();stamp=source.stat()
    changed=False
    def mutate(s):
        nonlocal changed
        if not changed:os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+2_000_000_000));changed=True
    with pytest.raises(ValueError,match='changed'):extract_area(source,POLYGON,progress=mutate,chunk_size=7)
    area=extract_area(source,POLYGON);session=AreaEditSession(area);session.assign([0],1)
    stamp=source.stat();os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+2_000_000_000))
    with pytest.raises(ValueError,match='changed'):session.export(tmp_path/'clean.las')
    assert not (tmp_path/'clean.las').exists()


def prepared(app,tmp_path):
    w=app.workspace;v=w.viewer
    w.path=tmp_path/'workspace.argus.json'
    path=tmp_path/'cloud.las';cloud(path);w.add_files([str(path)]);wait(app.root,v);w.poll()
    app.root.geometry('1400x900');app.root.deiconify();app.root.update()
    tool=w.layout.cleanup;tool.open();app.root.update()
    tool.polygon=[[1020,1998],[1030,1998],[1030,2002],[1020,2002]];tool.finish()
    return w,v,tool,path


def test_polygon_clicks_pan_zoom_and_finish_never_orbit_or_fit(application,tmp_path):
    w,v,tool,path=prepared(application,tmp_path)
    v.yaw=37;v.zoom=2;v.pan=np.array([22.,-19.]);tool.start();application.root.update()
    before=v.camera_state()
    event=E(x=350,y=100,num=1,state=0)
    point=screen_to_map(v,event.x,event.y)
    assert v.press(event)=='break'
    v.orbit(E(x=400,y=130,num=1,state=0));v.release(event);v.double_click(event)
    assert v.camera_state()==before
    np.testing.assert_allclose(tool.polygon[0],point)
    # Pan/zoom preserves polygon world coordinates and makes the next corner correct.
    v.press(E(x=350,y=100,num=3,state=0));v.move(E(x=362,y=92,num=3,state=0))
    v.wheel(E(x=200,y=120,delta=120))
    np.testing.assert_allclose(tool.polygon[0],point)
    for xy in [(400,130),(400,200)]:v.press(E(x=xy[0],y=xy[1],num=1,state=0))
    tool.finish();assert not tool.drawing
    assert v.yaw==37 and v.pitch==90
    assert v.canvas.find_withtag('cleanup-polygon')
    tool.close()


def test_full_resolution_scan_ignores_viewer_filters_and_refuses_changed_definition(application,tmp_path,monkeypatch):
    w,v,tool,path=prepared(application,tmp_path)
    v.class_filter=[7];v.line_filter=99;v.draw()
    tool.scan();wait(application.root,tool)
    assert tool.session.area.matched==55
    assert tool.session.area.class_filter==[2]
    tool.assign();assert tool.session.changed==55
    tool.undo();assert tool.session.changed==0
    errors=[];monkeypatch.setattr(tool,'error',lambda e:errors.append(str(e)))
    tool.z_min.set('100.5');tool.assign()
    assert tool.session.changed==0 and 'changed' in errors[-1]
    tool.close()


def accepted_chain(w,path,other):
    t=w.tracker
    job=t.begin('Classification',dict(cloud=str(other)),[other]);job.update(source='imported',stage_class='ClassifyStage')
    t.finish(job,'Needs review',[other]);t.decide('Classification','Accepted','Other flight reviewed')
    original=t.begin('Classification',dict(cloud=str(path)),[path]);original.update(source='imported',stage_class='ClassifyStage')
    t.finish(original,'Needs review',[path]);t.decide('Classification','Accepted','Original ground reviewed')
    for stage in ('Alignment','Surface','Contours','Final QA','Delivery'):
        j=t.begin(stage,{},[path]);j['source']='imported';t.finish(j,'Needs review',[path]);t.decide(stage,'Accepted','Fixture reviewed')
    w.persist()


def test_verified_gui_export_promotes_one_cloud_preserves_camera_and_invalidates_dependents(application,tmp_path):
    w,v,tool,path=prepared(application,tmp_path)
    other=tmp_path/'other.las';cloud(other);w.project_panel.clouds.append(str(other))
    w.project_panel.bindings[str(path)]='flight.trj'
    accepted_chain(w,path,other)
    before=path.read_bytes();camera=v.camera_state()
    tool.scan();wait(application.root,tool);tool.assign()
    output=tmp_path/'clean.las';tool.export(str(output));wait(application.root,tool)
    wait(application.root,v);w.poll()
    assert path.read_bytes()==before
    assert w.project_panel.clouds==[str(output),str(other)]
    assert w.project_panel.bindings[str(output)]=='flight.trj'
    assert str(path) not in w.project_panel.bindings
    assert v.camera_state()==camera
    assert w.tracker.status('Classification')=='Needs review'
    for stage in ('Alignment','Surface','Contours','Final QA','Delivery'):assert w.tracker.status(stage)=='Outdated'
    assert w.tracker.cloud_root(str(output))==str(path)
    jobs=w.tracker.current_jobs('Classification');assert len(jobs)==2
    edited=next(j for j in jobs if j['settings']['cloud']==str(path))
    untouched=next(j for j in jobs if j['settings']['cloud']==str(other))
    assert w.tracker.job_status(untouched)=='Accepted'
    record=json.loads(Path(edited['records'][0]).read_text(encoding='utf-8'))
    assert record['status']=='completed' and record['results']['changed']==55
    assert str(output)+'.edits.json' in [o[0] for o in edited['outputs']]
    assert all(w.tracker.latest(stage)['status']=='Accepted' for stage in ('Contours','Delivery'))
    tool.close()


def test_workspace_change_and_close_protect_unsaved_cleanup(application,tmp_path,monkeypatch):
    w,v,tool,path=prepared(application,tmp_path)
    tool.scan();wait(application.root,tool);tool.assign()
    monkeypatch.setattr('tkinter.messagebox.askyesno',lambda *a,**k:False)
    assert not tool.close() and tool.window.winfo_exists()
    assert w.restore(w.path,load_view=False) is False
    assert tool.session.changed==55
    tool.busy=True
    assert not tool.close() and tool.cancel.is_set()
    tool.busy=False;tool.undo();assert tool.close()



def test_cleanup_export_cancel_and_failure_leave_active_source_intact(application,tmp_path,monkeypatch):
    w,v,tool,path=prepared(application,tmp_path)
    tool.scan();wait(application.root,tool);tool.assign()
    before=path.read_bytes();output=tmp_path/'cancel.las'
    def cancelled(*args,**kwargs):raise InterruptedError('Fixture cancelled')
    monkeypatch.setattr(tool.session,'export',cancelled)
    tool.export(str(output));wait(application.root,tool)
    assert w.tracker.latest('Classification')['status']=='Cancelled'
    native=json.loads(Path(w.tracker.latest('Classification')['records'][0]).read_text(encoding='utf-8'))
    assert native['status']=='cancelled' and not output.exists()
    assert w.project_panel.clouds==[str(path)] and path.read_bytes()==before
    def failed(*args,**kwargs):raise ValueError('Fixture verification failed')
    monkeypatch.setattr(tool.session,'export',failed)
    tool.export(str(output));wait(application.root,tool)
    assert w.tracker.latest('Classification')['status']=='Failed'
    assert w.project_panel.clouds==[str(path)] and not output.exists()
    tool.undo();tool.close()


def test_cleanup_blocks_processing_until_background_job_stops(application,tmp_path,monkeypatch):
    w,v,tool,path=prepared(application,tmp_path)
    notices=[];monkeypatch.setattr('tkinter.messagebox.showinfo',lambda *a,**kw:notices.append(a))
    tool.busy=True
    w.run_task();w.app.run()
    assert len(notices)==2 and not w.app.runner.running
    tool.busy=False;tool.close()


def test_stereo_review_renders_selected_source_positions(application,tmp_path):
    w,v,tool,path=prepared(application,tmp_path)
    tool.scan();wait(application.root,tool)
    from PIL import ImageTk
    v.renderer.set('CPU');v.stereo.set(True);v.draw()
    highlighted=np.asarray(ImageTk.getimage(v.photo)).copy()
    session=tool.session;tool.session=None;v.draw()
    plain=np.asarray(ImageTk.getimage(v.photo))
    assert np.any(highlighted!=plain)
    tool.session=session;tool.close()
