"""Task input is explicit, alignment results are promoted, and the window fits its screen.

Acceptance tests for the October 21, 2026 review items: selecting a layer row
must never change what a task will read or mark any stage Outdated; corrected
clouds from Align become the project inputs for their flights with the
originals retained and the camera untouched; the main window and its Run row
stay on a 1366x768 display.
"""
import json
import time
from pathlib import Path

import pytest

from pyargus import gui as gui_module
from pyargus import project
from pyargus.workspace_gui import TASK_BADGE
from tests.test_gui import root, application
from tests.test_review_workspace import cloud, wait


def cloud_rows(w):
    return {w.layer_tree.item(i,'text')[2:]:i for i in w.layer_tree.get_children('group:Point clouds')}


def badge_rows(w):
    return [i for i in w.layer_tree.get_children('group:Point clouds') if w.layer_tree.item(i,'values')[1]==TASK_BADGE]


def test_tree_selection_never_changes_task_input_or_stage_status(application,tmp_path):
    app=application;w=app.workspace
    a,b=tmp_path/'a.las',tmp_path/'b.las';cloud(a);cloud(b)
    w.add_files([str(a),str(b)]);wait(app.root,w.viewer);w.poll()
    rows=cloud_rows(w)
    assert app.cloud_path.get()==str(a.resolve()) and badge_rows(w)==[rows['a.las']]
    assert all(w.layer_tree.item(i,'values')[0]=='Project input' for i in rows.values())
    stage=next(s for s in app.stages if type(s).__name__=='DtmStage')
    stage.out_path.set(str(tmp_path/'dtm.asc'));w.begin_stage(stage);job=w.active
    app.runner.error=None;app.runner.products=[];w.complete(app.runner)
    assert w.tracker.job_status(job,w.current_settings(job))=='Needs review'
    # Click, select and show/hide another cloud: none of it is a processing action.
    w.layer_tree.selection_set(rows['b.las']);w.select_layer();app.root.update()
    w.toggle_layer();w.poll();w.toggle_layer()
    assert app.cloud_path.get()==str(a.resolve())
    assert all(s.cloud_override.get()==str(a.resolve()) for s in app.stages if hasattr(s,'cloud_override'))
    assert w.tracker.job_status(job,w.current_settings(job))=='Needs review'
    assert badge_rows(w)==[cloud_rows(w)['a.las']]
    # Only the explicit action moves the task input, and exactly one row carries the badge.
    w.layer_tree.selection_set(cloud_rows(w)['b.las']);w.set_task_input_from_selection()
    assert app.cloud_path.get()==str(b.resolve())
    assert badge_rows(w)==[cloud_rows(w)['b.las']]
    assert all(s.cloud_override.get()==str(b.resolve()) for s in app.stages if hasattr(s,'cloud_override'))
    app.task_name.set('DTM / DSM');w.select_task()
    assert 'b.las' in app.scope_summary.get()


def test_project_align_completion_promotes_each_flight_and_keeps_camera(application,tmp_path):
    app=application;w=app.workspace;p=w.project_panel
    a,b=tmp_path/'a.las',tmp_path/'b.las';cloud(a);cloud(b,.25)
    out=tmp_path/'aligned';out.mkdir();corrected={}
    for index,source in enumerate((a,b),1):
        name=f'{index:04d}_{source.stem}_adjusted.las';cloud(out/name);corrected[str(source.resolve())]=str((out/name).resolve())
    (out/'alignment.json').write_text(json.dumps(dict(outputs=[dict(source=s,output=Path(d).name) for s,d in corrected.items()])))
    w.add_files([str(a),str(b)]);wait(app.root,w.viewer);w.poll()
    p.bindings={str(a.resolve()):'flight.trj'}
    v=w.viewer;v.yaw=33;v.pitch=48;v.zoom=1.7;v.draw()
    spec=project.Project(list(p.clouds),[],same_vertical=True)
    w.begin_project('align',spec,str(out));job=w.active
    app.runner.error=None;app.runner.products=[('report',str(out/'report.html'))]
    w.complete(app.runner);wait(app.root,v);w.poll()
    new_a,new_b=corrected[str(a.resolve())],corrected[str(b.resolve())]
    assert p.clouds==[new_a,new_b]
    assert p.bindings=={new_a:'flight.trj'}
    assert app.cloud_path.get()==new_a                 # the task input followed its own flight
    assert w.tracker.cloud_root(new_b)==str(b.resolve())
    assert w.tracker.job_status(job)=='Needs review'
    assert (v.yaw,v.pitch,v.zoom)==(33,48,1.7) and tuple(v.paths)==tuple(p.clouds)
    states={name:w.layer_tree.item(i,'values')[0] for name,i in cloud_rows(w).items()}
    assert states['a.las']=='Retained version' and states[Path(new_a).name]=='Project input'
    assert badge_rows(w)==[cloud_rows(w)[Path(new_a).name]]
    # Activating an already active version changes nothing; switching back restores the original and its binding.
    w.activate_cloud_version(new_a);wait(app.root,v);w.poll()
    assert p.clouds==[new_a,new_b]
    w.activate_cloud_version(a);wait(app.root,v);w.poll()
    assert p.clouds==[str(a.resolve()),new_b] and p.bindings=={str(a.resolve()):'flight.trj'}
    assert app.cloud_path.get()==str(a.resolve())


def test_single_cloud_align_write_output_is_promoted(application,tmp_path):
    app=application;w=app.workspace;p=w.project_panel
    source,out=tmp_path/'a.las',tmp_path/'a_aligned.las';cloud(source);cloud(out)
    p.clouds=[str(source)];w.sync_project_layers();w.set_active_cloud(str(source))
    stage=next(s for s in app.stages if type(s).__name__=='AlignStage')
    stage.write_path.set(str(out));w.begin_stage(stage);job=w.active
    app.runner.error=None;app.runner.products=[('classified',out)]
    w.complete(app.runner);wait(app.root,w.viewer);w.poll()
    assert p.clouds==[str(out)] and app.cloud_path.get()==str(out)
    assert w.tracker.cloud_root(out)==str(source)
    assert w.tracker.job_status(job)=='Needs review'


def test_failed_or_cancelled_align_does_not_promote(application,tmp_path):
    app=application;w=app.workspace;p=w.project_panel
    source,out=tmp_path/'a.las',tmp_path/'a_aligned.las';cloud(source);cloud(out)
    p.clouds=[str(source)];w.sync_project_layers();w.set_active_cloud(str(source))
    stage=next(s for s in app.stages if type(s).__name__=='AlignStage')
    stage.write_path.set(str(out));w.begin_stage(stage)
    app.runner.error=RuntimeError('solver refused');app.runner.products=[('classified',out)]
    w.complete(app.runner)
    assert p.clouds==[str(source)] and not w.tracker.data.get('cloud_versions')


def test_unregistered_output_is_not_activated_as_a_second_input(application,tmp_path):
    app=application;w=app.workspace;p=w.project_panel
    source,stray=tmp_path/'a.las',tmp_path/'stray.las';cloud(source);cloud(stray)
    p.clouds=[str(source)];w.sync_project_layers();w.add_layer(stray,'output','imported')
    with pytest.raises(ValueError,match='not a registered version'):w.activate_cloud_version(stray)
    assert p.clouds==[str(source)]
    w.tracker.register_cloud_result(source,stray,'job');w.activate_cloud_version(stray);wait(app.root,w.viewer);w.poll()
    assert p.clouds==[str(stray)]


def test_initial_geometry_fits_small_and_large_screens():
    assert gui_module.initial_geometry(2560,1440)==(1530,1000)
    assert gui_module.initial_geometry(1366,768)==(1326,678)
    width,height=gui_module.initial_geometry(800,600)
    assert width<=800 and height<=600


def test_process_button_everywhere_and_run_row_on_screen_at_1366x768(application):
    app=application;w=app.workspace;layout=w.layout;r=app.root
    width,height=gui_module.initial_geometry(r.winfo_screenwidth(),r.winfo_screenheight())
    assert tuple(r.minsize())==(min(1024,width),min(640,height))
    def settle():
        until=time.monotonic()+.5
        while time.monotonic()<until:
            r.update();time.sleep(.01)
    r.geometry('1366x768+0+0');r.deiconify()
    try:
        settle()
        for mode in ('Review','Deliver','Process'):
            layout.set_mode(mode);settle()
            assert layout.process_button.winfo_ismapped(),mode
        layout.set_mode('Review');settle()
        layout.open_process();settle()
        assert layout.mode=='Process' and app.task_dock.winfo_manager()=='pack'
        top,bottom=r.winfo_rooty(),r.winfo_rooty()+r.winfo_height()
        for widget in (app.run_button,app.stop_button,layout.stop_job,layout.statusbar):
            assert widget.winfo_ismapped(),widget
            assert top<=widget.winfo_rooty() and widget.winfo_rooty()+widget.winfo_height()<=bottom,widget
    finally:r.withdraw()
