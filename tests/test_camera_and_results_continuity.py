"""Camera and results continuity (review item 4, October 22, 2026).

The camera stays where the operator left it when a classification result is
activated, when a retained cloud is shown beside the loaded ones, when Reset
detail returns to the overview sample, and when the review pane changes the
canvas size. A finished LP360 job shows its delivered clouds; a finished
Inspect opens its matching results instead of leaving them in a closed dock.
"""
import time
from pathlib import Path

import numpy as np

from pyargus.lp360_workflow import run as run_lp360
from tests.test_gui import root, application
from tests.test_lp360_jobs import job
from tests.test_project import scene
from tests.test_review_workspace import cloud, wait


def camera(v):
    """The camera as the viewer records it: pan in map units, not pixels."""
    state=v.camera_state()
    return (tuple(state['center']),state['yaw'],state['pitch'],state['zoom'],state['span'],tuple(np.round(state['pan_units'],9)))


def centre_world(v):
    """Map XY under the canvas centre, by the viewer's own Ctrl-click mapping (Top view)."""
    w,h=max(2,v.canvas.winfo_width()),max(2,v.canvas.winfo_height())
    scale=min(w,h)*.85/v.span*v.zoom
    return tuple(np.round(-v.pan/[scale,-scale]+v.center[:2],6))


def look(v):
    v.yaw,v.pitch,v.zoom=33,48,1.7;v.pan=np.array([40.,-25.]);v.draw()
    return camera(v)


def settle(r,seconds=.5):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        r.update();time.sleep(.01)


def test_classification_completion_keeps_camera(application,tmp_path):
    app=application;w=app.workspace;v=w.viewer
    source,out=tmp_path/'a.las',tmp_path/'a_ground.las';cloud(source);cloud(out)
    w.add_files([str(source)]);wait(app.root,v);w.poll()
    before=look(v)
    stage=next(s for s in app.stages if type(s).__name__=='ClassifyStage')
    stage.out_path.set(str(out));w.begin_stage(stage)
    app.runner.error=None;app.runner.products=[('classified',out)]
    w.complete(app.runner);wait(app.root,v);w.poll()
    assert [Path(p).name for p in v.paths]==['a_ground.las'] and v.mode.get()=='Classification'
    assert camera(v)==before
    # An activation deferred behind a busy viewer keeps the camera when it finally loads.
    w.pending_version_view=dict(keep_camera=True);w.poll();wait(app.root,v);w.poll()
    assert w.pending_version_view is None and camera(v)==before


def test_showing_a_retained_cloud_keeps_camera(application,tmp_path):
    app=application;w=app.workspace;v=w.viewer
    source,out=tmp_path/'a.las',tmp_path/'a_ground.las';cloud(source);cloud(out,.5)
    w.add_files([str(source)]);wait(app.root,v);w.poll()
    w.tracker.register_cloud_result(str(source),str(out),'job');w.activate_cloud_version(str(out));wait(app.root,v);w.poll()
    assert [Path(p).name for p in v.paths]==['a_ground.las']
    before=look(v)
    rows={w.layer_tree.item(i,'text')[2:]:i for i in w.layer_tree.get_children('group:Point clouds')}
    assert w.layer_tree.item(rows['a.las'],'values')[0]=='Retained version'
    w.layer_tree.selection_set(rows['a.las']);w.toggle_layer();wait(app.root,v);w.poll()
    assert sorted(Path(p).name for p in v.paths)==['a.las','a_ground.las']
    assert camera(v)==before
    assert w.project_panel.clouds==[str(out.resolve())]   # showing it did not re-add it to the project


def test_switching_versions_by_hand_keeps_camera(application,tmp_path):
    app=application;w=app.workspace;v=w.viewer
    source,out=tmp_path/'a.las',tmp_path/'a_ground.las';cloud(source);cloud(out,.5)
    w.add_files([str(source)]);wait(app.root,v);w.poll()
    w.tracker.register_cloud_result(str(source),str(out),'job');w.add_layer(out,'output','job');w.refresh_layers();before=look(v)
    rows={w.layer_tree.item(i,'text')[2:]:i for i in w.layer_tree.get_children('group:Point clouds')}
    w.layer_tree.selection_set(rows['a_ground.las']);w.activate_selected_version();wait(app.root,v);w.poll()
    assert w.project_panel.clouds==[str(out.resolve())] and camera(v)==before


def test_reset_detail_restores_overview_without_reloading_or_moving(application,tmp_path):
    app=application;w=app.workspace;v=w.viewer
    source=tmp_path/'a.las';cloud(source)
    w.add_files([str(source)]);wait(app.root,v);w.poll()
    before=look(v);history=list(v.view_history)
    overview=v.overview_scene;pts,cls,lines,files,*rest=overview
    v.scene=(pts[:10],cls[:10],lines[:10],files[:10],*rest)   # a local-detail sample is on screen
    v.reset_detail()
    assert v.scene is overview and not v.busy
    assert camera(v)==before and v.view_history==history


def test_review_pane_changes_keep_world_point_under_centre(application,tmp_path):
    app=application;w=app.workspace;v=w.viewer;r=app.root
    source=tmp_path/'a.las';cloud(source)
    r.geometry('1366x768+0+0');r.deiconify()
    try:
        settle(r)
        w.add_files([str(source)]);wait(r,v);w.poll();settle(r)
        v.view(0,90);v.zoom=1.7;v.pan=np.array([40.,-25.]);v.draw();settle(r)
        before,point,size=camera(v),centre_world(v),v.canvas_size
        for _ in range(2):                              # the toolbar's Review pane toggle, there and back
            w.show_dock.set(not w.show_dock.get());w.layout.apply_dock();settle(r)
            assert v.canvas_size!=size,'the review pane change did not resize the canvas';size=v.canvas_size
            assert camera(v)==before and centre_world(v)==point
        w.layout.request_split(.25);settle(r)
        assert camera(v)==before and centre_world(v)==point
    finally:r.withdraw()


def test_lp360_completion_shows_the_delivered_clouds(application,job,tmp_path):
    from pyargus.lp360_gui import LP360Shortcut
    app=application;w=app.workspace;v=w.viewer
    _,_,recipe=job
    result=run_lp360(recipe,tmp_path/'run')
    assert result['status'].startswith('Completed') and len(result['final_clouds'])==2
    w.add_files(list(recipe.clouds));wait(app.root,v);w.poll()
    before=look(v)
    LP360Shortcut(w.layout).show_results(result);wait(app.root,v);w.poll()
    final=[str(Path(p).resolve()) for p in result['final_clouds']]
    assert list(v.paths)==final
    assert all(w.visible_var(p) is not None and w.visible_var(p).get() for p in final)
    assert camera(v)==before                      # the job covered the area on screen
    assert w.layout.mode=='Review' and w.tabs.select()==str(w.progress_tab)
    assert str(w.path)==str(Path(result['workspace']))


def test_inspect_completion_opens_matching_results(application,scene):
    app=application;w=app.workspace;p=w.project_panel;layout=w.layout;r=app.root
    p.clouds,p.tracks=list(scene.clouds),list(scene.trajectories);p.same_vertical.set(True);w.sync_project_layers()
    layout.set_mode('Process');w.show_dock.set(False);layout.apply_dock();r.update()
    assert not w.show_dock.get()
    p.start('inspect')
    def completed():
        if not app.runner.running and (p.inventory is not None or app.runner.error is not None):r.quit()
        else:r.after(50,completed)
    r.after(50,completed);timeout=r.after(20000,r.quit);r.mainloop();r.after_cancel(timeout)
    assert app.runner.error is None and p.inventory is not None
    assert layout.mode=='Process' and w.show_dock.get() and w.tabs.select()==str(w.project_tab)
    assert p.tabs.select()==p.tabs.tabs()[2] and len(p.result_tree.get_children())==2
