import numpy as np
import pytest
from tests.test_gui import root,application
from tests.test_review_workspace import cloud,wait
from pyargus.review_shortcuts import parse_classes


def test_class_groups_validate_without_guessing():
    assert parse_classes('All') is None
    assert parse_classes('Vegetation')==(3,4,5)
    assert parse_classes('Noise')==(7,18)
    assert parse_classes('2, 5,2')==(2,5)
    for value in ('','2,','-1','256','ground-ish'):
        with pytest.raises(ValueError):parse_classes(value)


def load_pair(app,tmp_path):
    paths=[tmp_path/'a.las',tmp_path/'b.las']
    for path in paths:cloud(path)
    w=app.workspace;w.add_files([str(p) for p in paths]);wait(app.root,w.viewer);w.poll()
    return w,[str(p.resolve()) for p in paths]


def test_solo_compare_restore_preserve_inputs_section_and_camera(application,tmp_path):
    w,paths=load_pair(application,tmp_path);v=w.viewer;s=w.layout.shortcuts
    w.layer_tree.selection_set('0');w.select_layer()
    before=(tuple(w.project_panel.clouds),application.cloud_path.get(),w.review.section_source.get(),v.yaw,v.pitch,v.zoom)
    original=[x.get() for x in v.visible];original_mode=v.mode.get()
    s.show_selected();assert [x.get() for x in v.visible]==[True,False]
    w.layer_tree.selection_set(('0','1'));s.show_selected(True)
    assert all(x.get() for x in v.visible) and v.mode.get()=='Dataset'
    s.restore();assert [x.get() for x in v.visible]==original and v.mode.get()==original_mode
    assert before==(tuple(w.project_panel.clouds),application.cloud_path.get(),w.review.section_source.get(),v.yaw,v.pitch,v.zoom)
    w.layer_tree.selection_set('group:Point clouds');s.show_selected()
    assert 'exactly one' in s.visibility_note.get()


def test_filters_atomic_and_workspace_restore(application,tmp_path,monkeypatch):
    w,paths=load_pair(application,tmp_path);v=w.viewer
    original_classes=v.scene[1].copy();inputs=tuple(w.project_panel.clouds)
    w.class_filter.set('Vegetation');w.filter();assert v.class_filter==(3,4,5)
    np.testing.assert_array_equal(v.scene[1],original_classes)
    errors=[];monkeypatch.setattr('pyargus.workspace_gui.messagebox.showerror',lambda *a,**k:errors.append(a))
    w.class_filter.set('bad');w.line_filter.set('wrong');w.filter()
    assert errors and v.class_filter==(3,4,5) and v.line_filter is None
    w.class_filter.set('Noise');w.line_filter.set('All');w.filter()
    w.path=tmp_path/'review.argus.json';w.persist();w.class_filter.set('All');w.filter()
    w.restore(w.path);wait(application.root,v);w.poll()
    assert v.class_filter==(7,18) and tuple(w.project_panel.clouds)==inputs


def test_project_context_and_collapsed_options(application,tmp_path):
    w,paths=load_pair(application,tmp_path);s=w.layout.shortcuts;r=w.review
    w.path=tmp_path/'Example_Project.argus.json';s.update()
    assert 'Example_Project' in s.project.get() and str(tmp_path) in s.location.get()
    assert s.context()['units']!='unknown'
    assert not r.advanced.winfo_manager()
    coords=[x.get() for x in r.coords];source=r.section_source.get()
    r.details_visible.set(True);r.toggle_details();assert r.advanced.winfo_manager()=='pack'
    r.details_visible.set(False);r.toggle_details();assert not r.advanced.winfo_manager()
    assert coords==[x.get() for x in r.coords] and source==r.section_source.get()
