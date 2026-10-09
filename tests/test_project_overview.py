from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as E
import time
import numpy as np
import pytest
from pyargus.project_overview import (read_extents,coordinate_groups,combined_bounds,
    map_transform,map_pixels,map_world,camera_plane,workflow_summary)
from pyargus.workspace_state import Tracker,STAGES
from pyargus.job_manifest import identity
from tests.test_gui import root,application
from tests.test_review_workspace import cloud,wait


def rows(states=None):
    return [(s,(states or {}).get(s,'Not started'),'Evidence: '+s) for s in STAGES]


def wait_overview(w):
    w.overview.request(force=True)
    until=time.monotonic()+8
    while time.monotonic()<until:
        w.root.update();time.sleep(.01)
        if w.overview.rows and w.overview.paths_key==w.overview.paths() and not getattr(w.overview,'again',False):return
    raise AssertionError('Header overview timed out')


def load(app,tmp_path):
    path=tmp_path/'a.las';cloud(path)
    w=app.workspace;w.add_files([str(path)]);wait(app.root,w.viewer);w.poll();wait_overview(w)
    return w,str(path.resolve())


def test_header_only_cache_and_changed_source(tmp_path,monkeypatch):
    import laspy
    a=tmp_path/'a.las';cloud(a)
    monkeypatch.setattr(laspy.LasReader,'read_points',lambda *a,**k:pytest.fail('Point data read'))
    before=identity(a);result,cache=read_extents([a])
    assert result[0]['points']==1111 and result[0]['bounds']==[1000.,1995.,100.,1100.,2005.,101.]
    assert identity(a)==before and len(coordinate_groups(result))==1
    with monkeypatch.context() as m:
        m.setattr(laspy,'open',lambda *a,**k:pytest.fail('Cache reread header'))
        assert read_extents([a],cache)[0]==result
    cloud(a,.5);updated,_=read_extents([a],cache)
    assert updated[0]['source']!=before and updated[0]['bounds'][2]==100.5


def test_header_groups_do_not_mix_crs_and_contain_missing_invalid_empty(tmp_path):
    import laspy
    a,b=tmp_path/'a.las',tmp_path/'b.las';cloud(a);cloud(b,epsg=26916)
    unknown=tmp_path/'unknown.las';data=laspy.LasData(laspy.LasHeader());data.x=[1.];data.y=[2.];data.z=[3.];data.write(unknown)
    empty=tmp_path/'empty.las';laspy.LasData(laspy.LasHeader()).write(empty)
    bad=tmp_path/'bad.las';bad.write_bytes(b'not LAS')
    result,_=read_extents([a,b,unknown,empty,bad,tmp_path/'missing.las'])
    assert len(coordinate_groups(result))==2
    assert all(r['error'] for r in result[2:])
    assert result[3]['points']==0 and result[-1]['points'] is None
    assert combined_bounds([]) is None


def test_map_transform_large_coordinates_and_plane_inverse():
    bounds=[2400000,1400000,900,2401000,1400100,1000]
    transform=map_transform(bounds,250,140)
    points=np.array([[2400000,1400000],[2401000,1400100],[2400200,1400070]])
    np.testing.assert_allclose(map_world(map_pixels(points,transform),transform),points)
    center=np.array([2400500,1400050,950]);plane=camera_plane(center,37,45,[12,-7],1000,2,800,400)
    from pyargus.viewer3d import project_points
    q=project_points(np.column_stack([plane,np.full(4,950)]),center,37,45)
    pixel=q[:,:2]*[.68,-.68]+[400,200]+[12,-7]
    np.testing.assert_allclose(pixel,[[0,0],[800,0],[800,400],[0,400]],atol=1e-7)
    assert camera_plane(center,37,0,[0,0],1000,2,800,400) is None


def test_status_prioritizes_review_stale_failure_clocks_and_running(tmp_path):
    t=Tracker();path=tmp_path/'a.las'
    assert workflow_summary(t,rows(),[])['kind']=='add'
    assert workflow_summary(t,rows(),[path],missing_clocks=2)['kind']=='settings'
    for state,kind in [('Needs review','history'),('Outdated','task'),('Failed','task'),('Unverified import','history')]:
        result=workflow_summary(t,rows({'Inspect':state}),[path]);assert result['stage']=='Inspect' and result['kind']==kind
    assert workflow_summary(t,rows(),[path],running='Alignment')['kind']=='busy'
    all_done=workflow_summary(t,rows({s:'Skipped' for s in STAGES}),[path],issues=3)
    assert all_done['reviewed']==9 and all_done['kind']=='delivery' and all_done['open_issues']==3


def test_ground_coverage_handles_new_input_versions_and_above_ground(tmp_path):
    t=Tracker();a,b,out=[tmp_path/n for n in ('a.las','b.las','a_ground.las')]
    j=t.begin('Classification',{'cloud':str(a)},[]);j['stage_class']='ClassifyStage';t.finish(j,'Needs review')
    t.decide('Classification','Accepted','Checked ground',job_id=j['id']);t.register_cloud_result(a,out,j['id'])
    other=t.begin('Classification',{'cloud':str(b)},[]);other['stage_class']='AboveStage';t.finish(other,'Needs review')
    before=deepcopy(t.data)
    result=workflow_summary(t,rows({'Inspect':'Accepted','Initial QA':'Accepted','Classification':'Accepted'}),[out,b])
    assert result['headline']=='Ground classification is partial'
    assert result['ground_recorded']==1 and result['ground_total']==2 and result['ground_accepted']==1
    assert result['kind']=='task' and result['stage']=='Classification' and before==t.data


def test_locator_navigates_without_scan_or_processing_mutation(application,tmp_path,monkeypatch):
    w,path=load(application,tmp_path);v=w.viewer;o=w.overview
    before=(tuple(w.project_panel.clouds),application.cloud_path.get(),w.review.section_source.get(),deepcopy(w.tracker.data['jobs']))
    scene=v.scene;classes=scene[1].copy();source=identity(path)
    v.yaw=31;v.pitch=47;v.zoom=4;v.stereo.set(True);v.draw();o.draw()
    monkeypatch.setattr(v,'load',lambda *a:pytest.fail('Unexpected cloud scan'))
    monkeypatch.setattr(w.review,'extract',lambda:pytest.fail('Unexpected section scan'))
    xy=map_pixels([1060,2001],o.transforms[o.locator]);o.click(E(x=xy[0],y=xy[1]),o.locator)
    np.testing.assert_allclose(v.center[:2],[1060,2001]);assert v.yaw==31 and v.pitch==47 and v.zoom==4 and v.stereo.get()
    assert v.scene is scene and source==identity(path);np.testing.assert_array_equal(v.scene[1],classes)
    assert before==(tuple(w.project_panel.clouds),application.cloud_path.get(),w.review.section_source.get(),w.tracker.data['jobs'])
    v.previous_view();assert v.center[0]!=1060


def test_map_refuses_other_crs_changed_header_busy_and_unloaded(application,tmp_path):
    w,path=load(application,tmp_path);o=w.overview;v=w.viewer
    b=tmp_path/'different.las';cloud(b,epsg=26916);w.project_panel.clouds.append(str(b.resolve()));wait_overview(w)
    o.selection=str(b.resolve());o.select_file() # Set group explicitly without selecting a processing layer.
    o.group.set(o.group_choice.cget('values')[1]);before=v.center.copy();o.fit_selected()
    np.testing.assert_array_equal(before,v.center);assert 'coordinate group' in o.notice.get()
    o.group.set(o.group_choice.cget('values')[0]);o.selection=path
    v.busy=True;o.center_selected();assert 'Wait' in o.notice.get();v.busy=False
    cloud(Path(path),1.);wait_overview(w);o.selection=path;o.fit_selected()
    assert 'identities differ' in o.notice.get();np.testing.assert_array_equal(before,v.center)


def test_status_refresh_is_read_only_and_next_action_does_not_run(application,tmp_path,monkeypatch):
    w,path=load(application,tmp_path);o=w.overview
    j=w.tracker.begin('Inspect',{},[]);w.tracker.finish(j,'Needs review');w.refresh();o.update_status(force=True)
    assert o.headline.get()=='Review Inspect' and o.stages.item('Inspect','values')==('Needs review',)
    before=deepcopy(w.tracker.data);clouds=list(w.project_panel.clouds);camera=w.viewer.center.copy()
    monkeypatch.setattr(application,'run',lambda:pytest.fail('Started processing'))
    o.next_action();assert w.tabs.select()==str(w.progress_tab)
    assert w.tracker.data==before and clouds==w.project_panel.clouds;np.testing.assert_array_equal(camera,w.viewer.center)
    o.show();o.update_status(force=True);application.root.update()
    assert w.tabs.select()==str(o.frame) # Refresh must not synthesize a stage click.


def test_overview_persistence_load_action_and_corridor_overlay(application,tmp_path,monkeypatch):
    w,path=load(application,tmp_path);o=w.overview
    w.viewer.corridor=(np.array([1010.,2000]),np.array([1020.,2000]),3.)
    o.draw();assert o.locator.find_withtag('section') and o.locator.find_withtag('view-plane')
    o.locator_visible.set(False);o.toggle_locator();o.show()
    w.path=tmp_path/'overview.argus.json';w.persist()
    assert w.tracker.data['project_overview']['locator'] is False
    o.locator_visible.set(True);o.toggle_locator();w.restore(w.path,load_view=False)
    assert not o.locator_visible.get() and w.tabs.select()==str(o.frame)
    wait_overview(w);o.selection=path;called=[];monkeypatch.setattr(w.viewer,'load',lambda paths:called.append(paths))
    o.load_selected();assert called==[[path]]


def test_above_ground_acceptance_is_not_ground_coverage(tmp_path):
    t=Tracker();path=tmp_path/'cloud.las'
    j=t.begin('Classification',{'cloud':str(path)},[]);j['stage_class']='AboveStage'
    t.finish(j,'Needs review');t.decide('Classification','Accepted','Reviewed objects')
    status=workflow_summary(t,rows({'Inspect':'Accepted','Initial QA':'Accepted','Classification':'Accepted'}),[path])
    assert status['ground_recorded']==0 and status['headline']=='Ground classification is partial'


def test_stale_header_message_is_discarded_and_no_point_loading(application,tmp_path,monkeypatch):
    w=application.workspace;o=w.overview
    a,b=tmp_path/'a.las',tmp_path/'b.las';cloud(a);cloud(b)
    old,_=read_extents([a]);w.project_panel.clouds=[str(b.resolve())]
    o.paths_key=o.paths();o.generation=7
    o.messages.put((6,(str(a.resolve()),),(old,{},None)))
    monkeypatch.setattr(w.viewer,'load',lambda *args:pytest.fail('Header overview loaded points'))
    o.poll();assert not o.rows
    o.paths_key=None;wait_overview(w);assert [r['path'] for r in o.rows]==[str(b.resolve())]
    assert w.viewer.scene is None and not w.tracker.data['jobs']


def test_status_sidebar_is_compact_and_lists_can_scroll(application):
    w=application.workspace;o=w.overview;application.root.geometry('1400x900');application.root.deiconify();o.show()
    until=time.monotonic()+.3
    while time.monotonic()<until:application.root.update();time.sleep(.01)
    assert not w.layout.progress.winfo_manager()
    assert o.sidebar_next.winfo_ismapped() and o.locator.winfo_ismapped()
    assert o.files.cget('yscrollcommand') and o.stages.cget('yscrollcommand')
    assert w.sidebar.winfo_width()<350 and o.canvas.winfo_height()>=90
    application.root.withdraw()
