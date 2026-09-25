import json
from pathlib import Path
import numpy as np
import pytest

from pyargus.workspace_state import Tracker
from pyargus.viewer3d import sample_viewport
from tests.test_gui import root, application
from tests.test_review_workspace import cloud, wait


def test_history_acceptance_stale_settings_and_inputs(tmp_path):
    source=tmp_path/'source';source.write_text('one')
    t=Tracker();j=t.begin('Inspect',{'clock':'same'},[source]);t.finish(j,'Needs review')
    assert t.status('Inspect')=='Needs review'
    with pytest.raises(ValueError):t.decide('Inspect','Accepted','')
    t.decide('Inspect','Accepted','Reviewed matching',{'clock':'same'})
    assert t.status('Inspect',{'clock':'week'})=='Outdated'
    source.write_text('changed')
    assert t.status('Inspect')=='Outdated'
    with pytest.raises(ValueError):t.decide('Inspect','Accepted','Cannot accept stale work')


def test_upstream_rerun_invalidates_dependents_without_erasing_history():
    t=Tracker();a=t.begin('Inspect',{},[]);t.finish(a,'Needs review');t.decide('Inspect','Accepted','checked')
    b=t.begin('Initial QA',{},[]);t.finish(b,'Needs review');t.decide('Initial QA','Accepted','checked')
    assert t.status('Initial QA')=='Accepted'
    t.begin('Inspect',{},[])
    assert t.status('Initial QA')=='Outdated'
    assert len(t.data['jobs'])==3 and len(t.data['decisions'])==2


def test_save_resume_interrupted_import_skip_and_outputs(tmp_path):
    out=tmp_path/'out';out.write_text('result')
    t=Tracker();t.begin('Inspect',{},[])
    j=t.begin('Surface',{},[]);t.finish(j,'Needs review',[out])
    t.decide('Colorization','Skipped','Not required for this delivery')
    path=tmp_path/'workspace.json';t.save(path);loaded=Tracker.load(path)
    assert loaded.status('Inspect')=='Unverified import'
    assert loaded.status('Colorization')=='Skipped'
    assert loaded.status('Surface')=='Needs review'
    out.unlink();assert loaded.status('Surface')=='Outdated'
    loaded.import_output(tmp_path/'legacy.las')
    assert loaded.status('Delivery')=='Unverified import'


def test_refine_scans_full_local_area(tmp_path):
    p=tmp_path/'cloud.las';cloud(p)
    # Top view is E,N relative to center; every one of 11 x 3 returns participates.
    scene=sample_viewport([p],[1000,2000,100],0,90,[10,20,-1,1],limit=7)
    assert scene[4]==33 and len(scene[0])==7
    assert np.all((scene[0][:,0]>=1010)&(scene[0][:,0]<=1020))


def test_main_embeds_one_3d_viewer_and_project_panel(application,tmp_path):
    import tkinter as tk
    from pyargus.project_gui import open_project
    from pyargus.viewer3d import open_viewer
    from pyargus.review_gui import open_review
    app=application;w=app.workspace
    assert app.canvas is w.viewer.canvas
    assert open_project(app) is w.project_panel
    assert open_viewer(app) is w.viewer
    assert open_review(app) is w.review
    assert not isinstance(w.viewer.window,tk.Toplevel)
    assert not isinstance(w.project_panel.window,tk.Toplevel)
    assert not hasattr(w.review.plan,'canvas')
    w.qa_phase.set('Final QA');w.begin_stage(app.stages[0])
    assert w.active['stage']=='Final QA'
    app.runner.error=RuntimeError('injected failure');w.complete(app.runner)
    assert w.tracker.status('Final QA')=='Failed'
    assert w.path.exists()


def test_workspace_restores_project_settings_section_and_camera(application,tmp_path):
    app=application;w=app.workspace;p=tmp_path/'cloud.las';cloud(p)
    w.project_panel.clouds=[str(p)];w.project_panel.same_vertical.set(True)
    w.project_panel.cell.set('12');w.load_project_clouds();wait(app.root,w.viewer)
    w.poll()
    v=w.viewer;v.yaw=30;v.pitch=50;v.zoom=2;v.pan=np.array([13.,17.]);v.visible[0].set(False)
    w.review.plan.corridor=(np.array([1000.,2000]),np.array([1100.,2000]),3.)
    w.path=tmp_path/'saved.json';w.persist()
    v.yaw=0;w.project_panel.cell.set('99')
    w.restore(w.path);wait(app.root,v);w.poll()
    assert v.yaw==30 and v.pitch==50 and v.zoom==2
    assert not v.visible[0].get()
    np.testing.assert_allclose(v.pan,[13,17])
    assert w.project_panel.cell.get()=='12'
    assert w.review.coords[0].get()=='1000.0'


def test_surface_sampling_preserves_xyz(tmp_path):
    from pyargus.workspace_assets import surface_points
    p=tmp_path/'surface.asc';p.write_text('ncols 2\nnrows 2\nxllcorner 100\nyllcorner 200\ncellsize 2\nNODATA_value -9999\n1 2\n3 -9999\n')
    np.testing.assert_allclose(surface_points(p),[[101,203,1],[103,203,2],[101,201,3]])


def test_point_pick_and_top_section_coordinates(application,tmp_path):
    from types import SimpleNamespace
    w=application.workspace;p=tmp_path/'cloud.las';cloud(p)
    w.viewer.load([str(p)]);wait(application.root,w.viewer);w.poll()
    v=w.viewer;v.view(0,90);application.root.update();v.draw()
    index=len(v.pick_xy)//2;x,y=v.pick_xy[index];picked=[];v.on_point=picked.append
    v.pick_point(SimpleNamespace(x=x,y=y))
    assert picked and picked[0]['classification']==2
    coords=[];v.on_section=coords.append;v.pick_section(SimpleNamespace(x=max(2,v.canvas.winfo_width())/2,y=max(2,v.canvas.winfo_height())/2))
    np.testing.assert_allclose(coords[0],v.center[:2])


def test_mixed_import_registers_trajectories_before_display(application,tmp_path,monkeypatch):
    app=application;w=app.workspace
    las=tmp_path/'input.las';track=tmp_path/'flight.trj';cloud(las)
    w.add_files([str(las),str(track),str(track)])
    wait(app.root,w.viewer);w.poll()
    assert w.project_panel.clouds==[str(las)]
    assert [t.path for t in w.project_panel.tracks]==[str(track)]
    assert w.project_panel.tracks[0].time_mode==''
    assert 'NEED TIME BASE' in w.file_summary.get()
    assert 'time base' in w.task_hint.get()
    assert len(w.tracker.data['layers'])==2
    w.persist();saved=json.loads(w.path.read_text())
    assert saved['project']['trajectories'][0]['path']==str(track)
    # Cancelling a coordinate confirmation must not orphan a viewer import.
    another=tmp_path/'another.trj'
    monkeypatch.setattr('tkinter.messagebox.askyesno',lambda *a,**k:False)
    w.viewer.track([str(another)])
    assert str(another) in [t.path for t in w.project_panel.tracks]
    assert not w.viewer.busy


def test_task_scope_routes_project_and_single_cloud(application,tmp_path,monkeypatch):
    app=application;w=app.workspace;called=[]
    monkeypatch.setattr(w.project_panel,'start',called.append)
    monkeypatch.setattr(app,'run',lambda:called.append('single'))
    app.task_name.set('Strip QA');w.select_task();w.run_task()
    assert called==['qa'] and app.task_scope.get()=='Entire project'
    app.task_name.set('Classify');w.select_task()
    assert app.task_scope.get()=='Selected cloud'
    w.set_active_cloud(str(tmp_path/'cloud.las'));w.run_task()
    assert called==['qa','single'] and app.notebook.index(app.notebook.select())==1


def test_remove_cloud_does_not_reimport_on_poll(application,tmp_path):
    w=application.workspace;las=tmp_path/'cloud.las';cloud(las)
    w.add_files([str(las)]);wait(application.root,w.viewer);w.poll()
    w.layer_tree.selection_set('0');w.remove_layers();w.poll()
    assert not w.project_panel.clouds and not w.tracker.data['layers']
    assert not application.cloud_path.get() and w.viewer.scene is None
    assert not w.review.loaded_paths


def test_sidebar_trajectory_selection_drives_settings(application,tmp_path):
    w=application.workspace;track=tmp_path/'flight.trj'
    w.add_files([str(track)]);w.layer_tree.selection_set('0');w.select_layer()
    assert w.project_panel.track_box.curselection()==(0,)
    w.project_panel.track_time.set('same');w.project_panel.apply_track_settings()
    assert w.project_panel.tracks[0].time_mode=='same'
    assert 'NEED TIME BASE' not in w.file_summary.get()


def test_missing_clock_opens_settings_and_selects_sidebar(application,tmp_path):
    w=application.workspace;w.add_files([str(tmp_path/'flight.trj')])
    with pytest.raises(ValueError,match='time base'):w.project_panel.check_time_settings()
    assert w.tabs.select()==str(w.project_tab)
    assert w.layer_tree.selection()==('0',)


def test_single_cloud_trajectory_uses_configured_clock(application,tmp_path):
    app=application;w=app.workspace;path=str(tmp_path/'flight.trj')
    w.add_files([path]);w.layer_tree.selection_set('0');w.select_layer()
    w.project_panel.track_time.set('week');w.project_panel.apply_track_settings()
    app.task_name.set('Align');w.select_task();app.task_scope.set('Selected cloud');w.select_task(reset_scope=False)
    app.sbet_path.set(path);w.sync_single_trajectory()
    assert app.trj_time.get()=='week'
    assert w.single_trajectory.winfo_manager()=='pack'


def test_classification_review_is_per_input_and_ignores_routing(tmp_path):
    a,b=tmp_path/'a.las',tmp_path/'b.las'
    a.write_text('a');b.write_text('b')
    t=Tracker()
    def settings(p,out,slope='0.15'):
        return dict(cloud=str(p),trajectory='',trj_time='same',stage=dict(out_path=out,slope=slope))
    first=t.begin('Classification',settings(a,'a_out'),[a]);t.finish(first,'Needs review')
    second=t.begin('Classification',settings(b,'b_out'),[b]);t.finish(second,'Needs review')
    t.decide('Classification','Accepted','First flight checked',settings(b,'different'),job_id=first['id'])
    assert first['status']=='Accepted' and second['status']=='Needs review'
    assert t.status('Classification')=='Needs review'
    t.decide('Classification','Accepted','Second flight checked',settings(b,'different'),job_id=second['id'])
    assert t.status('Classification')=='Accepted'
    assert t.job_status(first,settings(b,'different','0.2'))=='Outdated'
    rerun=t.begin('Classification',settings(a,'a_new'),[a]);t.finish(rerun,'Needs review')
    assert t.job_status(first)=='Outdated'
    assert t.job_status(second)=='Accepted'
    with pytest.raises(ValueError):
        t.decide('Classification','Accepted','Old run',job_id=first['id'])


def test_downstream_detects_rerun_of_either_classified_input(tmp_path):
    t=Tracker()
    for name in ('a','b'):
        path=tmp_path/name;path.write_text(name)
        job=t.begin('Classification',dict(cloud=str(path)),[path]);t.finish(job,'Needs review')
    downstream=t.begin('Surface',{},[]);t.finish(downstream,'Needs review')
    assert t.status('Surface')=='Needs review'
    job=t.begin('Classification',dict(cloud=str(tmp_path/'a')),[tmp_path/'a'])
    t.finish(job,'Needs review')
    assert t.status('Surface')=='Outdated'


def test_gui_review_targets_selected_flight_and_keeps_selection(application,tmp_path,monkeypatch):
    from pyargus import workspace_gui
    w=application.workspace
    stage=next(s for s in application.stages if type(s).__name__=='ClassifyStage')
    jobs=[]
    for name in ('first','second'):
        path=tmp_path/(name+'.las');cloud(path)
        application.cloud_path.set(str(path))
        stage.out_path.set(str(tmp_path/(name+'_ground.las')))
        w.begin_stage(stage)
        job=w.active
        application.runner.error=None
        w.complete(application.runner)
        jobs.append(job)
    w.stage_tree.selection_set('Classification');w.history()
    w.history_tree.selection_set(jobs[0]['id'])
    monkeypatch.setattr(workspace_gui.simpledialog,'askstring',lambda *a,**k:'Reviewed first flight')
    w.decide('Accepted')
    assert jobs[0]['status']=='Accepted'
    assert jobs[1]['status']=='Needs review'
    assert w.history_tree.selection()==(jobs[0]['id'],)
    assert '1/2 recorded inputs accepted' in w.stage_tree.item('Classification','values')[1]


def test_successful_classification_promotes_one_flight_and_preserves_binding(application,tmp_path):
    app=application;w=app.workspace;p=w.project_panel
    a,b,out=[tmp_path/name for name in ('a.las','b.las','a_ground.las')]
    for path in (a,b,out):cloud(path)
    p.clouds=[str(a),str(b)];p.bindings={str(a):'flight.trj'}
    w.sync_project_layers();app.cloud_path.set(str(a))
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    stage.out_path.set(str(out));w.begin_stage(stage)
    job=w.active
    app.runner.products=[('classified',out)];app.runner.error=None
    w.complete(app.runner);wait(app.root,w.viewer);w.poll()
    assert p.clouds==[str(out),str(b)]
    assert p.bindings=={str(out):'flight.trj'}
    assert app.cloud_path.get()==str(out)
    assert w.tracker.cloud_root(out)==str(a)
    assert any(layer['path']==str(a) for layer in w.tracker.data['layers'])
    assert w.tracker.job_status(job)=='Needs review'
    w.activate_cloud_version(a);wait(app.root,w.viewer);w.poll()
    assert p.clouds==[str(a),str(b)]
    assert p.bindings=={str(a):'flight.trj'}
    w.activate_cloud_version(out);wait(app.root,w.viewer);w.poll()
    # Showing the source for comparison must not re-add it as a project input.
    w.viewer.load([str(a),str(out)]);wait(app.root,w.viewer);w.poll()
    assert p.clouds==[str(out),str(b)]
    saved=tmp_path/'versions.json';w.tracker.save(saved)
    assert Tracker.load(saved).cloud_root(out)==str(a)


def test_failed_classification_does_not_promote_existing_output(application,tmp_path):
    app=application;w=app.workspace
    src,out=tmp_path/'a.las',tmp_path/'a_ground.las'
    cloud(src);cloud(out);w.project_panel.clouds=[str(src)];app.cloud_path.set(str(src))
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    stage.out_path.set(str(out));w.begin_stage(stage)
    app.runner.error=RuntimeError('failed');app.runner.products=[('classified',out)]
    w.complete(app.runner)
    assert w.project_panel.clouds==[str(src)]
    assert not w.tracker.data.get('cloud_versions')


def test_classification_of_derived_version_supersedes_same_flight(tmp_path):
    source,first,second=[tmp_path/name for name in ('a','a1','a2')]
    for p in (source,first,second):p.write_text('cloud')
    t=Tracker();j=t.begin('Classification',dict(cloud=str(source)),[source]);t.finish(j,'Needs review',[first])
    t.register_cloud_result(source,first,j['id'])
    k=t.begin('Classification',dict(cloud=str(first)),[first]);t.finish(k,'Needs review',[second])
    t.register_cloud_result(first,second,k['id'])
    assert t.cloud_root(second)==str(source)
    assert t.current_jobs('Classification')==[k]
    assert t.job_status(j)=='Outdated'


def test_reinspect_promoted_output_does_not_invalidate_unchanged_classification(tmp_path):
    src,out=tmp_path/'src',tmp_path/'out';src.write_text('original');out.write_text('classified')
    t=Tracker();inspect=t.begin('Inspect',{},[src]);t.finish(inspect,'Needs review')
    job=t.begin('Classification',dict(cloud=str(src)),[src]);t.finish(job,'Needs review',[out])
    t.register_cloud_result(src,out,job['id'])
    inspect=t.begin('Inspect',{},[out]);t.finish(inspect,'Needs review')
    assert t.job_status(job)=='Needs review'
    src.write_text('changed original')
    assert t.job_status(job)=='Outdated'


def test_old_workspace_recovers_only_verified_classification_lineage(tmp_path):
    src,out=tmp_path/'src.las',tmp_path/'result.las'
    src.write_text('original');out.write_text('classified')
    t=Tracker();job=t.begin('Classification',dict(cloud=str(src)),[src])
    job['stage_class']='ClassifyStage';t.finish(job,'Needs review',[out])
    t.data['project']={'clouds':[str(src)]}
    saved=tmp_path/'old.json';t.save(saved)
    recovered=Tracker.load(saved)
    assert recovered.cloud_root(out)==str(src)
    assert recovered.data['project']['clouds']==[str(src)]
    out.write_text('modified result')
    assert not Tracker.load(saved).data.get('cloud_versions')
    t.finish(job,'Failed',[out]);t.save(saved)
    assert not Tracker.load(saved).data.get('cloud_versions')


def test_version_promotion_queues_busy_viewer(application,tmp_path):
    w=application.workspace;src,out=tmp_path/'a.las',tmp_path/'out.las'
    cloud(src);cloud(out);w.project_panel.clouds=[str(src)]
    w.tracker.register_cloud_result(src,out,'job')
    w.viewer.busy=True
    w.activate_cloud_version(out)
    assert w.pending_version_view
    assert w.project_panel.clouds==[str(out)]
    w.viewer.busy=False;w.poll();wait(application.root,w.viewer);w.poll()
    assert not w.pending_version_view
    assert list(w.viewer.paths)==[str(out)]
