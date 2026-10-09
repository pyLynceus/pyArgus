import numpy as np
import pytest
from pyargus.gpu_renderer import Renderer
from tests.test_gui import root

@pytest.fixture
def gpu():
    pytest.importorskip("moderngl")
    try:
        renderer=Renderer()
    except Exception as exc:
        pytest.skip("Hardware OpenGL unavailable: "+str(exc))
    yield renderer
    renderer.close()

def image(gpu,points,rgb=None,**kwargs):
    return gpu.render(np.asarray(points,dtype=float),
        np.asarray(rgb if rgb is not None else [[255,0,0]]*len(points),dtype=np.uint8),
        kwargs.pop("center",[0,0,0]),kwargs.pop("yaw",0),kwargs.pop("pitch",90),
        kwargs.pop("scale",10),100,80,[0,0],**kwargs)

def test_nearest_depth_and_large_coordinate_precision(gpu):
    points=np.array([[0.,0.,0.],[0.,0.,1.],[.01,0.,2.]])
    rgb=np.array([[255,0,0],[0,255,0],[0,0,255]],dtype=np.uint8)
    original=image(gpu,points,rgb,scale=100)
    origin=np.array([2400000.,400000.,1000.])
    shifted=image(gpu,points+origin,rgb,scale=100,center=origin)
    np.testing.assert_array_equal(original,shifted)
    assert list(original[40,50])==[0,255,0]
    assert list(original[40,51])==[0,0,255]

def test_empty_filters_resize_and_cached_resident_buffers(gpu):
    points=np.array([[0.,0,0],[1.,0,0]])
    rgb=np.array([[255,0,0],[0,255,0]])
    image(gpu,points,rgb,key="same")
    for yaw in (20,90,140):
        image(gpu,points,rgb,key="same",yaw=yaw)
    assert gpu.uploads==1
    blank=image(gpu,points,rgb,keep=np.zeros(2,dtype=bool),key="hidden")
    assert np.all(blank==[16,25,37])
    resized=gpu.render(points,rgb,[0,0,0],0,90,10,70,55,[0,0])
    assert resized.shape==(55,70,3)

def test_stereo_eye_swap_and_zero_depth(gpu):
    points=np.array([[0.,0.,5.],[2.,1.,-4.]])
    rgb=np.full((2,3),200,dtype=np.uint8)
    a=image(gpu,points,rgb,stereo_depth=5)
    b=image(gpu,points,rgb,stereo_depth=5,swap=True)
    np.testing.assert_array_equal(a[:,:,0],b[:,:,1])
    np.testing.assert_array_equal(a[:,:,1],b[:,:,0])
    assert not np.array_equal(a[:,:,0],a[:,:,1])
    c=image(gpu,points,rgb,stereo_depth=0)
    np.testing.assert_array_equal(c[:,:,0],c[:,:,1])
    with pytest.raises(ValueError):
        image(gpu,points,rgb,stereo_depth=float("nan"))

def test_linework_depth_test_and_on_top(gpu):
    points=np.array([[0.,0,2.]])
    line=np.array([[-2.,0,0],[2.,0,0]])
    a=image(gpu,points,linework=[(line,(0,255,0),3,False)])
    b=image(gpu,points,linework=[(line,(0,255,0),3,True)])
    assert list(a[40,50])==[255,0,0]
    assert list(b[40,50])==[0,255,0]
    assert list(a[40,40])==[0,255,0]

def test_contexts_can_alternate_and_close(gpu):
    second=Renderer()
    try:
        for renderer in (gpu,second,gpu,second):
            assert list(image(renderer,[[0,0,0]])[40,50])==[255,0,0]
    finally:
        second.close()

def setup_view(root):
    import tkinter as tk
    from pyargus.viewer3d import Viewer
    viewer=Viewer(root)
    viewer.scene=(np.array([[0.,0,0],[1,2,3],[3,2,1]]),
                  np.array([2,5,6]),np.array([1,2,3]),np.zeros(3,dtype=int),3,None)
    viewer.visible=[tk.BooleanVar(master=viewer.window,value=True)]
    viewer.center=np.ones(3);viewer.span=4.
    root.update()
    return viewer

def test_missing_gpu_falls_back_once_without_camera_changes(root,monkeypatch):
    import pyargus.gpu_renderer as module
    calls=[]
    def unavailable():
        calls.append(1)
        raise RuntimeError("test driver unavailable")
    monkeypatch.setattr(module,"Renderer",unavailable)
    v=setup_view(root)
    try:
        before=(v.yaw,v.pitch,v.zoom)
        v.draw();v.draw()
        assert len(calls)==1 and "CPU fallback" in v.render_note.get()
        assert (v.yaw,v.pitch,v.zoom)==before and v.photo.width()>0
        v.renderer.set("CPU");v.change_renderer()
        assert v.render_note.get()=="CPU renderer"
    finally:
        v.close()

def test_gpu_picking_filters_and_stereo_share_camera(root):
    from types import SimpleNamespace
    v=setup_view(root)
    try:
        v.draw()
        if v.gpu is None:
            pytest.skip(v.render_note.get())
        v.draw()
        assert v.pick_dirty
        picked=[]
        v.on_point=picked.append
        w,h=v.canvas.winfo_width(),v.canvas.winfo_height()
        v.update_picks(v.scene[0],np.ones(3,dtype=bool),min(w,h)*.85/v.span*v.zoom,w,h)
        xy=v.pick_xy[0].copy();v.draw()
        before=(v.yaw,v.pitch,v.zoom)
        v.pick_point(SimpleNamespace(x=xy[0],y=xy[1]))
        assert picked and picked[0]["classification"]==2
        assert (v.yaw,v.pitch,v.zoom)==before
        v.class_filter=[2];v.draw();assert v.gpu.count==1
        v.stereo.set(True);v.draw();assert v.photo.width()>0
        v.stereo_swap.set(True);v.draw()
    finally:
        v.close()
