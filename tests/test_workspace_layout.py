from copy import deepcopy
import numpy as np
from tests.test_gui import root,application
from tests.test_review_workspace import cloud,wait
from tests.test_route_sections import make_layer


def test_modes_preserve_view_inputs_and_task_routing(application,tmp_path,monkeypatch):
    app=application;w=app.workspace;layout=w.layout;v=w.viewer
    path=tmp_path/'cloud.las';cloud(path);w.add_files([str(path)]);wait(app.root,v);w.poll()
    scene=v.scene;camera=(v.yaw,v.pitch,v.zoom,v.center.copy(),v.pan.copy());paths=tuple(w.project_panel.clouds)
    calls=[];monkeypatch.setattr(app,'run',lambda:calls.append('single'))
    assert layout.mode=='Review' and not app.task_panel.winfo_manager()
    layout.nav.select(layout.pages['Process']);app.root.update()
    assert layout.mode=='Process' and app.task_panel.winfo_manager()=='pack'
    layout.select_task('Classify');app.stages[1].slope.set('0.21')
    w.run_task();assert calls==['single']
    layout.set_mode('Deliver');assert layout.deliver.winfo_manager()=='pack' and not app.task_panel.winfo_manager()
    layout.set_mode('Review');assert not layout.deliver.winfo_manager()
    assert app.stages[1].slope.get()=='0.21' and paths==tuple(w.project_panel.clouds)
    assert v.scene is scene and (v.yaw,v.pitch,v.zoom)==camera[:3]
    np.testing.assert_array_equal(v.center,camera[3]);np.testing.assert_array_equal(v.pan,camera[4])


def test_reference_layers_share_sidebar_without_becoming_processing_inputs(application,tmp_path):
    w=application.workspace;layer=make_layer(tmp_path)
    w.linework.imported([layer],{})
    item='dxf:'+layer['id'];assert w.layer_tree.parent(item)=='group:Linework'
    w.layer_tree.selection_set(item);w.select_layer()
    assert w.linework.selected()['id']==layer['id'] and not w.selected_layers()
    before=deepcopy(w.project_panel.clouds)
    w.toggle_layer();assert not layer['visible']
    w.toggle_layer();assert layer['visible']
    assert w.project_panel.clouds==before
    w.remove_layers();assert not w.linework.layers and not w.layer_tree.exists(item)
    # Group headings must never be treated as file indexes.
    w.layer_tree.selection_set('group:Point clouds');w.select_layer();assert not w.selected_layers()


def test_drawer_persistence_menus_and_existing_exports(application,monkeypatch):
    w=application.workspace;layout=w.layout;calls=[]
    assert tuple(layout.menus)==('File','View','Tools','Help')
    layout.project_settings();assert layout.mode=='Process' and w.show_dock.get()
    assert w.tabs.select()==str(w.project_tab)
    layout.hide_dock();assert str(w.review_bottom) not in w.review_panes.panes()
    w.show_section_review();application.root.update()
    assert layout.mode=='Review' and w.tabs.select()==str(w.review_tab)
    assert w.show_dock.get()
    saved=layout.snapshot();layout.set_mode('Deliver');layout.hide_dock();layout.restore(saved)
    assert layout.snapshot()==saved
    w.capture();assert w.tracker.data['ui_layout']==saved
    monkeypatch.setattr(w.review,'export',lambda:calls.append('csv'))
    monkeypatch.setattr(w.features,'export',lambda:calls.append('dxf'))
    layout.export_choice.set('Section sample CSV');layout.export()
    layout.export_choice.set('Traced linework DXF');layout.export()
    assert calls==['csv','dxf']
    layout.draw_section();assert not w.viewer.stereo.get() and w.viewer.pitch==90


def test_qa_record_opens_dedicated_page_and_progress_uses_actual_status(application,tmp_path):
    from tests.test_review_workspace import record
    w=application.workspace
    a,b=tmp_path/'a.las',tmp_path/'b.las';cloud(a);cloud(b,.25)
    w.review.open_record(record((a,b),tmp_path));application.root.update()
    assert w.tabs.select()==str(w.qa_tab) and w.show_dock.get()
    job=w.tracker.begin('Inspect',{},[]);w.tracker.finish(job,'Needs review');w.refresh();w.layout.update()
    assert w.layout.progress.item('Inspect','values')==('Needs review',)


def test_toolbar_wraps_without_losing_commands(application):
    layout=application.workspace.layout
    application.root.update_idletasks()
    # Force a narrow geometry independently of the screen resolution.
    layout.toolbar.configure(width=600);layout.toolbar.pack_propagate(False)
    layout.toolbar.winfo_width=lambda:600
    layout.wrap_toolbar()
    assert layout.toolbar_narrow
    assert all(row.pack_info()['side']=='top' for row in layout.toolbar_rows)
    assert layout.sections_menu.index('end')>=4


def test_visible_layout_keeps_viewer_and_profile_usable(application):
    import time
    w=application.workspace;r=application.root
    r.geometry('1400x900');r.deiconify()
    def settle():
        until=time.monotonic()+.5
        while time.monotonic()<until:
            r.update();time.sleep(.01)
    settle();w.show_section_review();settle()
    height=w.review_panes.winfo_height();sash=w.review_panes.sashpos(0)
    assert 150<sash<height-150
    assert w.viewer.canvas.winfo_height()>150
    assert w.review_bottom.winfo_height()>300
    w.layout.set_mode('Process');settle()
    assert len(w.review_panes.panes())==1 and w.viewer.canvas.winfo_height()>500
    assert all(row.winfo_ismapped() for row in w.layout.toolbar_rows)
    w.layout.set_mode('Review');settle()
    assert len(w.review_panes.panes())==2
    assert 150<w.review_panes.sashpos(0)<w.review_panes.winfo_height()-150
    r.withdraw()
