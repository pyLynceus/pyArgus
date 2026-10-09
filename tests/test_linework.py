from copy import deepcopy
from types import SimpleNamespace as E
import numpy as np
import pytest
from pyargus.linework import read_dxf,paint,validate
from tests.test_gui import root,application


def drawing(path, units=21):
    import ezdxf
    doc=ezdxf.new();doc.units=units
    doc.layers.new('WALL',dxfattribs={'color':3})
    m=doc.modelspace();m.add_polyline3d([(0,0,10),(10,0,11)],dxfattribs={'layer':'WALL'})
    m.add_arc((5,5,10),2,0,180,dxfattribs={'layer':'WALL'})
    m.add_point((1,2,10),dxfattribs={'layer':'WALL'})
    m.add_text('Not linework');doc.saveas(path)


def test_dxf_geometry_layers_units_and_planar(tmp_path):
    import ezdxf
    p=tmp_path/'test.dxf';drawing(p)
    layers,skipped=read_dxf(p,'EPSG:6447')
    assert skipped=={'TEXT':1} and layers[0]['name']=='WALL'
    assert len(layers[0]['segments'])==3 and len(layers[0]['segments'][1])>3
    assert layers[0]['source']['path']==str(p.resolve())
    validate(layers)
    drawing(p,6)
    with pytest.raises(ValueError,match='units'):read_dxf(p,6447)
    doc=ezdxf.new();doc.units=21
    doc.modelspace().add_lwpolyline([(0,0),(10,0),(10,10)])
    doc.saveas(p)
    with pytest.raises(ValueError,match='zero-elevation'):read_dxf(p,6447)
    layers,_=read_dxf(p,6447,planar=True,elevation=1100)
    assert layers[0]['planar']
    assert np.all(np.array(layers[0]['segments'][0])[:,2]==1100)


def test_linework_depth_and_on_top():
    cloud=np.array([[0.,0.,10.]])
    line=np.array([[-1.,0.,0.],[1.,0.,0.]])
    pixels=np.zeros((20,20,3),dtype=np.uint8)
    paint(pixels,cloud,[(line,(255,0,0),1,False)],5,[0,0])
    assert pixels[10,10,0]==0 and pixels[10,9,0]==255
    paint(pixels,cloud,[(line,(255,0,0),1,True)],5,[0,0])
    assert pixels[10,10,0]==255
    # Huge offscreen segments are clipped rather than allocating a huge sample.
    paint(pixels,cloud,[(np.array([[-1e8,0,0],[1e8,0,0]]),(0,255,0),2,True)],5,[0,0])
    assert pixels[10,10,1]==255


def test_review_layout_layers_and_cursor_zoom(application,tmp_path):
    import tkinter as tk
    from pyproj import CRS
    w=application.workspace;v=w.viewer
    v.scene=(np.array([[0.,0,10],[10,10,11]]),np.array([2,2]),np.array([1,1]),np.array([0,0]),2,CRS(6447))
    v.center=np.array([5.,5.,10]);v.span=20;v.visible=[tk.BooleanVar(value=True)]
    application.root.update()
    p=tmp_path/'test.dxf';drawing(p)
    layers,skipped=read_dxf(p,6447)
    w.linework.imported(layers,skipped);assert len(w.linework.geometry())==3
    w.linework.tree.selection_set(layers[0]['id']);w.linework.toggle();assert not w.linework.geometry()
    w.linework.show_all();v.draw();v.stereo.set(True);v.draw();v.stereo.set(False)
    w.review_mode.set(True);w.layout_review();application.root.update()
    assert not application.task_panel.winfo_manager()
    w.show_dock.set(False);w.layout_review();assert str(w.review_bottom) not in w.review_panes.panes()
    w.show_dock.set(True);w.layout_review();assert str(w.review_bottom) in w.review_panes.panes()
    w.review_mode.set(False);w.layout_review()
    packed=application.root.pack_slaves()
    assert packed.index(application.task_panel)<packed.index(w.workspace_host)
    old=v.zoom;pan=v.pan.copy();x,y=100,50
    a=np.array([x-v.canvas.winfo_width()/2,y-v.canvas.winfo_height()/2])
    v.wheel(E(x=x,y=y,delta=120))
    np.testing.assert_allclose((a-v.pan)/v.zoom,(a-pan)/old)
    v.previous_view();assert v.zoom==old
    w.capture();assert w.tracker.data['linework']==layers
    changed=deepcopy(layers);p.write_text('changed')
    w.linework.restore(changed);assert not w.linework.layers[0]['visible']


def test_pivot_preserves_screen_position(application):
    import tkinter as tk
    from pyargus.viewer3d import project_points
    w=application.workspace;v=w.viewer
    pts=np.array([[10.,20.,30.],[20.,30.,40.]])
    v.scene=(pts,np.array([2,2]),np.array([1,1]),np.array([0,0]),2,None)
    v.center=np.zeros(3);v.span=50;v.visible=[tk.BooleanVar(value=True)]
    application.root.update();v.draw()
    scale=min(v.canvas.winfo_width(),v.canvas.winfo_height())*.85/v.span*v.zoom
    before=project_points(pts,v.center,v.yaw,v.pitch)[:,:2]*[scale,-scale]+v.pan
    v.pick_xy=np.array([[50.,50.]]);v.pick_ids=np.array([0]);v.pick_depth=np.array([1.])
    v.choose_pivot=True;v.pick_point(E(x=50,y=50))
    after=project_points(pts,v.center,v.yaw,v.pitch)[:,:2]*[scale,-scale]+v.pan
    np.testing.assert_allclose(before,after)
    np.testing.assert_array_equal(v.center,pts[0])
    v.previous_view();np.testing.assert_array_equal(v.center,[0,0,0])
