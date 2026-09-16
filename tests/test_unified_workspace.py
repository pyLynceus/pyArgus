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
