from copy import deepcopy
from types import SimpleNamespace as E
from dataclasses import asdict
import json
import numpy as np
import pytest
from pyargus.review_memory import ReviewMemory,validate_state,context_errors,view_center
from tests.test_gui import root,application
from tests.test_review_workspace import cloud,wait
from tests.test_route_sections import make_layer


def setup(app,tmp_path,pair=False):
    w=app.workspace;n=w.notes;v=w.viewer;r=w.review
    paths=[tmp_path/'ground.las']+([tmp_path/'other_ground.las'] if pair else [])
    for i,path in enumerate(paths):cloud(path,i*.1)
    w.path=tmp_path/'review.argus.json';w.add_files([str(p) for p in paths]);wait(app.root,v);w.poll()
    app.root.geometry('1400x900');app.root.deiconify();app.root.update()
    w.layout.apply_preset('3D + Profile');app.root.update()
    if pair:r.section_source.set('Compare all loaded clouds');r.confirm.set(True)
    return w,n,v,r,paths


def test_memory_roundtrip_independent_records_and_issue_anchor(application,tmp_path):
    w,n,v,r,paths=setup(application,tmp_path)
    v.yaw=27;v.pitch=52;v.zoom=2;v.pan=np.array([11.,-7.]);state=n.capture_view()
    model=ReviewMemory();view=model.save_view('Barrier',state);issue=model.issue('Review wall',state)
    np.testing.assert_allclose(issue['anchor']['xyz'],view_center(state['camera']))
    assert issue['anchor']['kind']=='view-center' and issue['state']=='Open'
    state['camera']['zoom']=9
    assert view['view']['camera']['zoom']==2
    model.update_issue(issue['id'],'Review wall','Ground classification','In review','Verify shoulder and wall separation.')
    assert ReviewMemory(json.loads(json.dumps(model.data))).data==model.data
    assert not context_errors(view['view'])
    old=deepcopy(issue)
    with pytest.raises(ValueError):model.update_issue(issue['id'],'','Noise','Resolved','bad')
    assert model.get('issues',issue['id'])==old
    with pytest.raises(ValueError):model.issue('bad pick',view['view'],dict(x=0,y=0,z=0,file='elsewhere.las',classification=2,line=1))


@pytest.mark.parametrize('change',[
    lambda s:s['camera'].update(zoom=float('nan')),
    lambda s:s['camera'].update(center=[0,1]),
    lambda s:s.update(visible=[]),
    lambda s:s['display'].update(classes='-1'),
    lambda s:s['display'].update(line='70000'),
    lambda s:s['display'].update(depth=8),
    lambda s:s.update(section_source='unknown.las'),
    lambda s:s.update(section=dict(start=[0,0],end=[0,0],width=1)),
    lambda s:s.update(route=dict(layer='missing')),
])
def test_saved_state_refuses_invalid_values(application,tmp_path,change):
    w,n,v,r,paths=setup(application,tmp_path);state=n.capture_view();change(state)
    with pytest.raises(ValueError):validate_state(state)


def test_named_view_restores_camera_filters_route_and_source_without_processing_changes(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path,True)
    layer=make_layer(tmp_path);w.linework.imported([layer],{})
    r.route.activate(layer,0);r.route.station.set('25');r.route.span.set('30');r.use_cache.set(False);r.route.go();wait(application.root,r)
    w.layout.apply_preset('Comparison review');application.root.update()
    v.view(37,50);v.zoom=3;v.pan=np.array([15.,-18.]);v.stereo.set(True);v.stereo_depth.set(3.5);v.stereo_swap.set(True)
    w.class_filter.set('Ground');w.filter();r.mode.set('Classification');r.exaggeration.set('2.5')
    before=n.capture_view();project=asdict(w.project_panel.snapshot());active=application.cloud_path.get();settings=w.stage_settings(application.stages[1]);jobs=deepcopy(w.tracker.data['jobs'])
    monkeypatch.setattr('pyargus.review_memory_gui.simpledialog.askstring',lambda *a,**k:'Barrier check')
    n.save_view();saved=n.model.data['views'][0];assert saved['title']=='Barrier check'
    r.route.stop();r.section_source.set(str(paths[0].resolve()));v.view(0,90);v.pan[:]=0;v.zoom=1;v.stereo.set(False);v.mode.set('Elevation')
    w.class_filter.set('All');w.filter()
    calls=[];monkeypatch.setattr(r,'extract',lambda:calls.append('extract'));monkeypatch.setattr(v,'load',lambda *a,**k:calls.append('load'));monkeypatch.setattr(application,'run',lambda:calls.append('process'))
    application.root.geometry('1550x950');application.root.update()
    n.views.selection_set(saved['id']);n.go_view();application.root.update()
    after=n.capture_view()
    for key in ('camera','display','section','section_source','route','profile','visible'):
        if key=='camera':
            np.testing.assert_allclose(view_center(after[key]),view_center(before[key]),atol=1e-8)
            assert after[key]['yaw']==before[key]['yaw'] and after[key]['zoom']==before[key]['zoom']
        else:assert after[key]==before[key]
    assert not calls and r.section is None and not v.auto_detail.get()
    assert asdict(w.project_panel.snapshot())==project and application.cloud_path.get()==active
    assert w.stage_settings(application.stages[1])==settings and w.tracker.data['jobs']==jobs


def test_issue_point_pick_is_read_only_resolve_and_stereo_marker_behavior(application,tmp_path):
    w,n,v,r,paths=setup(application,tmp_path);v.view(0,90);v.draw();application.root.update()
    original=v.scene[1].copy();camera=(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan));active=application.cloud_path.get()
    # Pick a displayed pixel close to the canvas center.
    center=np.array([v.canvas.winfo_width()/2,v.canvas.winfo_height()/2]);i=np.argmin(np.linalg.norm(v.pick_xy-center,axis=1));x,y=v.pick_xy[i]
    n.arm();assert n.armed and v.press(E(x=x,y=y,num=1,state=0))=='break'
    assert not n.armed and len(n.model.data['issues'])==1 and not w.features.model.items
    row=n.model.data['issues'][0];assert row['anchor']['kind']=='picked-sample' and row['anchor']['file']==str(paths[0].resolve())
    assert camera==(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan)) and active==application.cloud_path.get()
    np.testing.assert_array_equal(v.scene[1],original)
    n.title.set('Possible shoulder artifact');n.category.set('Ground classification');n.state.set('In review');n.note.insert('1.0','Check against adjacent section.');n.apply_issue()
    assert row['note']=='Check against adjacent section.' and row['state']=='In review'
    application.root.update();v.draw();assert len(v.canvas.find_withtag('review-issue'))>=4 and len(n.geometry())==1
    n.set_state('Resolved');assert row['state']=='Resolved' and not n.geometry()
    n.show_resolved.set(True);v.stereo.set(True);v.draw();assert len(n.geometry())==1 and v.photo.width()>0
    with pytest.raises(ValueError,match='Stereo'):n.arm()
    assert not w.tracker.data['decisions']


def test_changed_sources_block_recall_and_hide_pins_without_camera_mutation(application,tmp_path):
    w,n,v,r,paths=setup(application,tmp_path);n.issue_here();row=n.model.data['issues'][0]
    saved=n.model.save_view('Old result',row['view']);camera=(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan));source=r.section_source.get()
    cloud(paths[0],dz=.3);n.refresh(force=True);v.draw()
    assert n.availability[row['id']]=='Changed source' and not n.geometry()
    with pytest.raises(ValueError,match='Changed'):n.recall(saved['view'],'Old')
    assert camera==(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan)) and source==r.section_source.get()
    paths[0].unlink();assert context_errors(saved['view'])[0].startswith('Missing:')


def test_recall_reloads_display_clouds_and_preserves_project_version_selection(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path,True);state=n.capture_view();project=asdict(w.project_panel.snapshot());active=application.cloud_path.get()
    v.load([str(paths[1].resolve())]);wait(application.root,v);w.poll()
    calls=[];monkeypatch.setattr(r,'extract',lambda:calls.append('extract'))
    n.recall(state,'Pair');assert n.pending is not None
    wait(application.root,v);w.poll();application.root.update()
    assert n.pending is None and tuple(v.paths)==tuple(s['path'] for s in state['inputs'])
    assert r.section_source.get()=='Compare all loaded clouds' and asdict(w.project_panel.snapshot())==project
    assert application.cloud_path.get()==active and not calls


def test_resume_checkpoint_survives_process_mode_and_workspace_reopen(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path);v.view(54,31);v.zoom=2.4;n.issue_here();n.title.set('Wall review');n.apply_issue()
    w.persist();last=deepcopy(n.model.data['last_review']);w.layout.set_mode('Process');v.view(0,90);v.zoom=1;w.persist()
    assert n.model.data['last_review']==last
    n.model=ReviewMemory();n.refresh(force=True)
    calls=[];monkeypatch.setattr(r,'extract',lambda:calls.append('extract'));monkeypatch.setattr(application,'run',lambda:calls.append('run'))
    n.resume();wait(application.root,v);w.poll();application.root.update()
    assert not n.resume_pending and (v.yaw,v.pitch,v.zoom)==(54,31,2.4)
    assert n.model.data['issues'][0]['title']=='Wall review' and not calls and w.layout.mode=='Review'


def test_malformed_notes_refused_before_workspace_mutation(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path);w.persist();saved=json.loads(w.path.read_text(encoding='utf-8'))
    state=n.capture_view();view=ReviewMemory().save_view('Bad',state);view['view']['camera']['zoom']=-1
    saved['review_notes']['views']=[view];bad=tmp_path/'bad.argus.json';bad.write_text(json.dumps(saved))
    oldtracker=w.tracker;oldpath=w.path;errors=[]
    monkeypatch.setattr('pyargus.workspace_gui.messagebox.showerror',lambda *a,**k:errors.append(a))
    w.restore(bad);assert errors and w.tracker is oldtracker and w.path==oldpath


def test_export_roundtrip_protects_workspace_and_loaded_sources(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path);n.issue_here();destination=tmp_path/'notes.json'
    monkeypatch.setattr('pyargus.review_memory_gui.filedialog.asksaveasfilename',lambda **k:str(destination));n.export()
    exported=ReviewMemory(json.loads(destination.read_text(encoding='utf-8')));assert len(exported.data['issues'])==1
    before=w.path.read_bytes();monkeypatch.setattr('pyargus.review_memory_gui.filedialog.asksaveasfilename',lambda **k:str(w.path))
    with pytest.raises(ValueError,match='separate'):n.export()
    assert w.path.read_bytes()==before


def test_missing_route_reference_and_busy_load_block_restore_before_mutation(application,tmp_path):
    w,n,v,r,paths=setup(application,tmp_path);layer=make_layer(tmp_path);w.linework.imported([layer],{});r.route.activate(layer,0)
    state=n.capture_view();camera=(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan));record=n.model.save_view('Route location',state)
    w.linework.layers.clear();n.refresh(force=True)
    assert n.availability[record['id']]=='Reference not imported'
    with pytest.raises(ValueError,match='reference layer'):n.recall(state,'Route')
    assert camera==(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan))
    v.busy=True
    with pytest.raises(ValueError,match='load or job'):n.recall(state,'Route')
    v.busy=False


def test_next_open_issue_and_cancelled_placement_preserve_workflow(application,tmp_path):
    w,n,v,r,paths=setup(application,tmp_path);n.issue_here();first=n.model.data['issues'][0];n.set_state('Resolved')
    v.view(20,35);n.issue_here();second=n.model.data['issues'][1]
    n.selected_issue=first['id'];n.next_issue();assert n.selected_issue==second['id'] and (v.yaw,v.pitch)==(20,35)
    n.arm();n.disarm();assert not n.armed and len(n.model.data['issues'])==2
    assert not w.tracker.data['jobs'] and not w.tracker.data['decisions']


def test_issue_numbers_are_not_reused_and_corrupt_layout_refused(application,tmp_path):
    w,n,v,r,paths=setup(application,tmp_path);state=n.capture_view();first=n.model.issue('First',state)
    n.model.data['issues'].remove(first);second=n.model.issue('Second',state)
    assert second['number']==first['number']+1
    restored=ReviewMemory(json.loads(json.dumps(n.model.data)));third=restored.issue('Third',state)
    assert third['number']==second['number']+1
    state['layout']['split_fraction']=float('nan')
    with pytest.raises(ValueError,match='split'):validate_state(state)


def test_cold_resume_loads_only_checkpoint_clouds_once(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path,True)
    v.load([str(paths[0].resolve())]);wait(application.root,v);w.poll();v.view(31,42);w.persist()
    w.layout.set_mode('Process');v.load([str(paths[1].resolve())]);wait(application.root,v);w.poll();w.persist()
    n.model=ReviewMemory();v.scene=None;v.paths=()
    calls=[];original_load=v.load
    def load(paths):calls.append(tuple(paths));return original_load(paths)
    monkeypatch.setattr(v,'load',load)
    n.resume();wait(application.root,v);w.poll()
    assert calls==[(str(paths[0].resolve()),)] and (v.yaw,v.pitch)==(31,42)
    assert application.cloud_path.get()==str(paths[0].resolve())
