from copy import deepcopy
from pathlib import Path
import time
import numpy as np
import pytest
from pyargus.version_comparison import (preferences,recorded_pair,inspect_pair,
    check_sources,role_visibility,section_matches)
from pyargus.workspace_state import Tracker
from pyargus.job_manifest import identity
from tests.test_gui import root,application
from tests.test_review_workspace import cloud,wait


def lineage(t,source,result):
    j=t.begin('Classification',{'cloud':str(source.resolve())},[source]);j['stage_class']='ClassifyStage'
    t.finish(j,'Needs review',[result]);t.register_cloud_result(source,result,j['id']);return j


def settle(app,condition):
    until=time.monotonic()+10
    while time.monotonic()<until:
        app.root.update();app.workspace.poll();time.sleep(.02)
        if condition():return
    raise AssertionError('Comparison timed out')


def setup(app,tmp_path,recorded=True):
    a,b=tmp_path/'original.las',tmp_path/'result.las';cloud(a);cloud(b,.25)
    w=app.workspace;w.add_files([str(a)]);wait(app.root,w.viewer);w.poll()
    app.root.geometry('1400x900');app.root.deiconify();app.root.update()
    if recorded:lineage(w.tracker,a,b);w.add_layer(b,'output','Synthetic completed job')
    c=w.comparison;c.original.set(str(a.resolve()));c.result.set(str(b.resolve()));c.confirmed.set(True)
    r=w.review
    for var,value in zip(r.coords,[1010.,2000.,1050.,2000.]):var.set(str(value))
    r.width.set('3');r.section_source.set(str(a.resolve()));r.set_corridor()
    return w,c,a,b


def prepare(app,c):
    c.prepare();settle(app,lambda:c.pending is None and not c.v.busy)
    assert c.info is not None,c.notice.get()


def test_recorded_descendant_and_manual_pair_without_filename_guessing(tmp_path):
    a,b,d=[tmp_path/n for n in ('a.las','b.las','d.las')]
    for p in (a,b,d):cloud(p)
    t=Tracker();first=lineage(t,a,b);second=lineage(t,b,d)
    assert recorded_pair(t,str(d))==(str(a.resolve()),str(d.resolve()))
    before=deepcopy(t.data);info=inspect_pair(t,str(a),str(d),True)
    assert info['provenance']=='Recorded lineage' and len(info['jobs'])==2 and t.data==before
    manual=inspect_pair(Tracker(),str(a),str(b),True)
    assert manual['provenance'].startswith('Manual pair') and not recorded_pair(Tracker(),str(b))
    b.write_bytes(b'changed');
    with pytest.raises(ValueError,match='lineage changed'):check_sources(info)


def test_pair_identity_crs_completion_and_settings_refusals(tmp_path):
    a,b=tmp_path/'a.las',tmp_path/'b.las';cloud(a);cloud(b)
    with pytest.raises(ValueError,match='different files'):inspect_pair(Tracker(),str(a),str(a),True)
    with pytest.raises(ValueError,match='Confirm'):inspect_pair(Tracker(),str(a),str(b),False)
    cloud(b,epsg=26916)
    with pytest.raises(ValueError,match='CRS differ'):inspect_pair(Tracker(),str(a),str(b),True)
    cloud(b);t=Tracker();j=lineage(t,a,b);j['status']='Failed'
    with pytest.raises(ValueError,match='finish successfully'):inspect_pair(t,str(a),str(b),True)
    j['status']='Needs review';cloud(b,.4)
    with pytest.raises(ValueError,match='changed'):inspect_pair(t,str(a),str(b),True)
    for bad in [dict(schema_version=9),dict(schema_version=1,confirmed='yes',role='Both')]:
        with pytest.raises(ValueError):preferences(bad)
    assert role_visibility('Both')==[True,True]


def test_prepare_preserves_camera_filters_location_overlays_and_inputs(application,tmp_path):
    w,c,a,b=setup(application,tmp_path);v=w.viewer;r=w.review
    v.yaw=38;v.pitch=52;v.zoom=4;v.pan=np.array([18.,-9.]);v.mode.set('Classification');v.stereo.set(True)
    w.class_filter.set('Ground');w.line_filter.set('1');w.filter()
    flag=v.tk.BooleanVar(value=True)
    overlay=('Control',[np.array([[1010.,2000.,100.]])],flag);v.extra_layers=[overlay];w.overlay_vars['Control']=flag
    before=(list(w.project_panel.clouds),application.cloud_path.get(),deepcopy(w.tracker.data['jobs']),deepcopy(w.tracker.data['decisions']))
    camera=v.camera_state();coords=[x.get() for x in r.coords];width=r.width.get();source=identity(a);output=identity(b)
    prepare(application,c)
    assert before==(w.project_panel.clouds,application.cloud_path.get(),w.tracker.data['jobs'],w.tracker.data['decisions'])
    assert v.camera_state()==camera and [x.get() for x in r.coords]==coords and float(r.width.get())==float(width)
    assert v.mode.get()=='Classification' and v.stereo.get() and v.class_filter==(2,) and v.line_filter==1
    assert v.extra_layers==[overlay] and source==identity(a) and output==identity(b)
    assert c.info['provenance']=='Recorded lineage' and v.paths==(str(a.resolve()),str(b.resolve()))
    assert w.visible_var('Control') is flag
    flag.set(False);c.restore_previous()
    assert flag.get() and w.visible_var('Control') is flag


def test_switches_and_restore_are_scan_free_and_processing_read_only(application,tmp_path,monkeypatch):
    w,c,a,b=setup(application,tmp_path);v=w.viewer;r=w.review
    v.yaw=21;v.pitch=45;v.zoom=3;v.pan=np.array([11.,-8.]);old_scene=v.scene;old_camera=v.camera_state()
    prepare(application,c);camera=v.camera_state();scene=v.scene;classes=scene[1].copy();jobs=deepcopy(w.tracker.data['jobs']);project=list(w.project_panel.clouds)
    monkeypatch.setattr(v,'load',lambda *a:pytest.fail('Unexpected scan'))
    monkeypatch.setattr(v,'launch',lambda *a:pytest.fail('Unexpected scan'))
    monkeypatch.setattr(r,'extract',lambda:pytest.fail('Unexpected section extraction'))
    for role,shown in [('Original',[True,False]),('Both',[True,True]),('Result',[False,True])]:
        c.switch(role);assert [x.get() for x in v.visible]==shown and v.camera_state()==camera and v.scene is scene
        assert r.section_source.get()==(str(a.resolve()) if role=='Original' else str(b.resolve()) if role=='Result' else 'Compare all loaded clouds')
    c.swap();assert c.role.get()=='Original'
    np.testing.assert_array_equal(classes,v.scene[1]);assert w.tracker.data['jobs']==jobs and w.project_panel.clouds==project
    c.restore_previous();assert v.scene is old_scene and v.camera_state()==old_camera and v.paths==(str(a.resolve()),)
    assert w.project_panel.clouds==project and not c.info


def test_profile_switch_reuses_same_sample_and_common_camera(application,tmp_path,monkeypatch):
    w,c,a,b=setup(application,tmp_path);v=w.viewer;r=w.review;prepare(application,c)
    c.extract();settle(application,lambda:not r.busy and not c.profile_pending)
    sec=r.section;assert section_matches(sec,c.info,v.corridor)
    c.switch('Both');profile_camera=c.plot_state();count=len(r.profile.xy)
    assert count==len(sec.points)>0 and 'Display: Both.' in r.status.get()
    monkeypatch.setattr(r,'extract',lambda:pytest.fail('Profile rescanned'))
    for role,file_id in [('Original',0),('Result',1)]:
        c.switch(role);assert r.section is sec and len(r.profile.xy)==sum(sec.files==file_id)
        assert f'Display: {role}.' in r.status.get()
        for name in ('center','span','pan'):np.testing.assert_array_equal(c.plot_state()[name],profile_camera[name])
        assert c.plot_state()['zoom']==profile_camera['zoom']
    # A normal scene refresh must not reset the A/B display to Both in the profile.
    r.refresh_files();c.poll();assert len(r.profile.xy)==sum(sec.files==1)
    v.corridor=(v.corridor[0]+[0,5],v.corridor[1]+[0,5],v.corridor[2]);c.switch('Original')
    assert r.section is None


def test_manual_pair_is_review_only_and_saved_settings_do_not_claim_lineage(application,tmp_path):
    w,c,a,b=setup(application,tmp_path,recorded=False);prepare(application,c)
    assert c.info['provenance'].startswith('Manual pair') and w.project_panel.clouds==[str(a.resolve())]
    assert str(b.resolve()) in w.viewer.review_only_paths and not w.tracker.data.get('cloud_versions')
    w.path=tmp_path/'manual.argus.json';w.persist()
    data=deepcopy(w.tracker.data);c.role.set('Original');c.restore(data['version_comparison'])
    assert c.role.get()=='Result' and c.info is None
    w.restore(w.path,load_view=False);assert str(b.resolve()) in w.viewer.review_only_paths
    w.poll();assert w.project_panel.clouds==[str(a.resolve())]


def test_changed_sources_busy_and_other_load_refuse_switch(application,tmp_path):
    w,c,a,b=setup(application,tmp_path);prepare(application,c)
    w.viewer.busy=True
    with pytest.raises(ValueError,match='Finish'):c.switch('Original')
    w.viewer.busy=False;cloud(b,.5)
    with pytest.raises(ValueError,match='changed'):c.switch('Original')
    w.viewer.paths=(str(a.resolve()),)
    with pytest.raises(ValueError,match='Loaded clouds changed'):c.switch('Both')


def test_review_load_preserves_navigation_that_occurs_during_preparation(application,tmp_path):
    w,c,a,b=setup(application,tmp_path);c.prepare()
    w.viewer.yaw=77;w.viewer.pitch=37;w.viewer.pan=np.array([18.,7.]);w.viewer.zoom=6
    camera=w.viewer.camera_state();settle(application,lambda:c.pending is None)
    assert c.info and w.viewer.camera_state()==camera


def test_malformed_comparison_workspace_does_not_replace_tracker(application,tmp_path,monkeypatch):
    import json
    w,c,a,b=setup(application,tmp_path);old=w.tracker
    data=deepcopy(w.tracker.data);data['version_comparison']={'schema_version':3}
    path=tmp_path/'bad.json';path.write_text(json.dumps(data))
    errors=[];monkeypatch.setattr('pyargus.workspace_gui.messagebox.showerror',lambda *a,**k:errors.append(a))
    assert not w.restore(path) and w.tracker is old and errors


def test_cancelled_prepare_keeps_previous_display(application,tmp_path):
    w,c,a,b=setup(application,tmp_path);scene=w.viewer.scene;camera=w.viewer.camera_state()
    c.prepare();w.viewer.cancel.set();settle(application,lambda:c.pending is None and not w.viewer.busy)
    assert c.info is None and w.viewer.scene is scene and w.viewer.camera_state()==camera
    assert w.project_panel.clouds==[str(a.resolve())]


def test_saved_visibility_is_reported_truthfully_and_empty_filter_is_explained(application,tmp_path):
    w,c,a,b=setup(application,tmp_path);prepare(application,c)
    w.viewer.visible[0].set(True);w.viewer.visible[1].set(False);c.poll()
    assert c.role.get()=='Original' and c.label.get().startswith('Original')
    w.class_filter.set('Noise');w.filter();c.switch('Result')
    assert 'no sampled points' in c.notice.get()
