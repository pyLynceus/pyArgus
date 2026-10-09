from types import SimpleNamespace as E
from copy import deepcopy
import numpy as np
import pytest
from pyargus.section_interaction import drag_corridor
from tests.test_gui import root,application
from tests.test_review_workspace import cloud,wait
from tests.test_route_sections import make_layer


def test_translation_endpoints_width_rotation_at_large_coordinates():
    a=np.array([2400000.,400000.]);b=a+[100,0]
    moved=drag_corridor('move',a,b,3,a,a+[5,-7])
    np.testing.assert_allclose(moved[0],a+[5,-7]);np.testing.assert_allclose(moved[1],b+[5,-7])
    fixed=drag_corridor('a',a,b,3,a,a+[-10,8]);np.testing.assert_array_equal(fixed[1],b)
    assert drag_corridor('width',a,b,3,a,a+[0,2])[2]==7
    assert drag_corridor('width',a,b,3,a,a+[0,-20],.01)[2]==.01
    mid=(a+b)/2
    rotated=drag_corridor('rotate',a,b,3,mid+[0,50],mid+[50,0])
    np.testing.assert_allclose((rotated[0]+rotated[1])/2,mid)
    np.testing.assert_allclose(rotated[0],mid+[0,50]);np.testing.assert_allclose(rotated[1],mid+[0,-50])
    assert np.linalg.norm(rotated[1]-rotated[0])==pytest.approx(100)
    np.testing.assert_array_equal(a,[2400000,400000])


def test_invalid_drag_refuses_degenerate_geometry():
    for kind,p,q in [('a',[0,0],[10,0]),('rotate',[5,0],[5,0]),('move',[0,0],[np.nan,0]),('unknown',[0,0],[1,1])]:
        with pytest.raises(ValueError):drag_corridor(kind,[0,0],[10,0],2,p,q)


def prepared(app,tmp_path):
    w=app.workspace;v=w.viewer;r=w.review
    path=tmp_path/'cloud.las';cloud(path);w.add_files([str(path)]);wait(app.root,v);w.poll()
    w.path=tmp_path/'review.argus.json'
    w.layout.apply_preset('3D + Profile')
    # Use a mapped canvas to exercise pixel/map conversion and visible handles.
    app.root.geometry('1400x900');app.root.deiconify();app.root.update()
    for var,value in zip(r.coords,[1025,1998,1075,2002]):var.set(str(value))
    r.width.set('3');r.set_corridor();r.use_cache.set(False);r.extract();wait(app.root,r)
    editor=w.layout.corridor;editor.enabled.set(True);editor.toggle();app.root.update()
    return w,v,r,editor


def handle(editor,name,delta=(0,0)):
    xy=editor.screen([editor.handles()[name]])[0]+delta
    return E(x=float(xy[0]),y=float(xy[1]),state=0,num=1)


def test_preview_cancel_keeps_profile_route_camera_and_autosave(application,tmp_path):
    w,v,r,editor=prepared(application,tmp_path)
    layer=make_layer(tmp_path);r.route.layers=lambda:[layer];r.route.activate(layer,0)
    before=deepcopy(r.route.state);section=r.section;original=v.corridor;camera=v.view_key()
    pressed=handle(editor,'move');assert v.press(pressed)=='break'
    moved=E(x=pressed.x+25,y=pressed.y-13,state=0,num=1)
    v.orbit(moved);assert r.section is section and v.corridor is not original
    w.capture();assert w.tracker.data['sections'][-1]['start']==original[0].tolist()
    assert [float(x.get()) for x in r.coords]==[*original[0],*original[1]]
    editor.escape();assert editor.drag is None and v.corridor is original
    assert r.section is section and r.route.state==before and v.view_key()==camera
    assert v.orbit_anchor is None


def test_release_updates_definition_without_scan_or_input_change(application,tmp_path,monkeypatch):
    w,v,r,editor=prepared(application,tmp_path)
    old=v.corridor;camera=v.view_key();source=r.section_source.get();paths=tuple(w.project_panel.clouds)
    calls=[];monkeypatch.setattr(r,'extract',lambda:calls.append('extract'))
    pressed=handle(editor,'width');v.press(pressed)
    unit=(old[1]-old[0])/np.linalg.norm(old[1]-old[0]);normal=np.array([-unit[1],unit[0]])
    target=editor.screen([editor.handles()['width']+normal*1.5])[0]
    end=E(x=target[0],y=target[1],state=0,num=1);v.orbit(end);v.release(end)
    assert float(r.width.get())==pytest.approx(6) and r.section is None and not calls
    assert camera==v.view_key() and source==r.section_source.get() and paths==tuple(w.project_panel.clouds)
    np.testing.assert_allclose(v.corridor[0],old[0]);np.testing.assert_allclose(v.corridor[1],old[1])
    assert len(v.canvas.find_withtag('section-handles'))>=10
    editor.auto_extract.set(True);pressed=handle(editor,'b');v.press(pressed)
    end=E(x=pressed.x+18,y=pressed.y,state=0,num=1);v.release(end)
    assert calls==['extract'] and editor.drag is None


def test_navigation_cancels_drag_and_busy_or_ambiguous_source_refused(application,tmp_path):
    w,v,r,editor=prepared(application,tmp_path);original=v.corridor;section=r.section
    pressed=handle(editor,'move');v.press(pressed);v.orbit(E(x=pressed.x+20,y=pressed.y,state=0,num=1))
    v.wheel(E(x=300,y=120,delta=120));assert v.corridor is original and editor.drag is None and r.section is section
    pressed=handle(editor,'a');r.busy=True
    assert v.press(pressed)=='break' and editor.drag is None;r.busy=False
    editor.auto_extract.set(True);r.section_source.set('')
    assert v.press(pressed)=='break' and editor.drag is None
    assert 'Section source' in v.status.get() or 'Choose' in v.status.get()


def test_presets_persist_without_extracting_changing_camera_or_source(application,tmp_path,monkeypatch):
    w,v,r,editor=prepared(application,tmp_path);layout=w.layout
    calls=[];monkeypatch.setattr(r,'extract',lambda:calls.append('extract'))
    camera=(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan));source=r.section_source.get();section=r.section
    layout.apply_preset('Full 3D');assert not w.show_dock.get()
    layout.apply_preset('Comparison review');assert w.show_dock.get() and v.mode.get()==r.mode.get()=='Dataset'
    editor.auto_extract.set(True);saved=layout.snapshot()
    layout.set_mode('Process');layout.restore(saved)
    assert layout.snapshot()==saved and not editor.enabled.get() and editor.auto_extract.get()
    assert not calls and r.section is section and source==r.section_source.get()
    assert camera==(v.yaw,v.pitch,v.zoom,tuple(v.center),tuple(v.pan))
    layout.restore(dict(split_fraction=float('nan'),preset='unknown'))
    assert layout.split_fraction==.48 and layout.preset.get()=='Custom'


def test_uncommitted_drag_cancelled_when_layout_changes(application,tmp_path):
    w,v,r,editor=prepared(application,tmp_path);original=v.corridor;section=r.section
    pressed=handle(editor,'move');v.press(pressed)
    v.orbit(E(x=pressed.x+30,y=pressed.y+20,state=0,num=1))
    w.layout.apply_preset('Full 3D')
    assert editor.drag is None and v.corridor is original and r.section is section
    w.layout.apply_preset('3D + Profile');application.root.update()
    pressed=handle(editor,'move');v.press(pressed)
    v.orbit(E(x=pressed.x+30,y=pressed.y,state=0,num=1))
    r.busy=True;v.release(E(x=pressed.x+30,y=pressed.y,state=0,num=1));r.busy=False
    assert editor.drag is None and v.corridor is original and r.section is section


def test_click_and_returned_preview_do_not_invalidate_profile(application,tmp_path):
    w,v,r,editor=prepared(application,tmp_path);section=r.section;original=v.corridor
    pressed=handle(editor,'move');v.press(pressed);v.release(pressed)
    assert v.corridor is original and r.section is section
    v.press(pressed);v.orbit(E(x=pressed.x+30,y=pressed.y,state=0,num=1));v.release(pressed)
    assert v.corridor is original and r.section is section
    # Rotated Top view still inverts pointer coordinates correctly.
    v.view(37,90);v.zoom=2;v.pan=np.array([22.,-19.]);v.draw()
    for xy in ([1025.,1998.],[1075.,2002.]):
        pixel=editor.screen([xy])[0];np.testing.assert_allclose(editor.map_xy(E(x=pixel[0],y=pixel[1])),xy)


def test_saved_workspace_restores_layout_and_auto_extract_without_scan(application,tmp_path,monkeypatch):
    w,v,r,editor=prepared(application,tmp_path)
    w.layout.apply_preset('Comparison review');editor.auto_extract.set(True);w.persist()
    coords=[x.get() for x in r.coords];source=r.section_source.get()
    calls=[];monkeypatch.setattr(r,'extract',lambda:calls.append('extract'))
    w.layout.apply_preset('Full 3D');editor.auto_extract.set(False);w.restore(w.path);wait(application.root,v);w.poll()
    assert w.layout.preset.get()=='Comparison review' and editor.auto_extract.get() and not editor.enabled.get()
    assert [float(x.get()) for x in r.coords]==[float(x) for x in coords] and r.section_source.get()==source and not calls
