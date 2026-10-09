import numpy as np
import pytest
from pyargus.anaglyph import eye_pixels,render
from tests.test_gui import root,application


def test_eye_geometry_center_and_depth():
    q=np.array([[0.,0.,0.],[0,0,10],[0,0,-10]])
    left=eye_pixels(q,10,100,80,[0,0],4,1)
    right=eye_pixels(q,10,100,80,[0,0],4,-1)
    np.testing.assert_allclose(left[0],right[0])
    np.testing.assert_allclose(left[:,1],right[:,1])
    assert left[1,0]>right[1,0] and left[2,0]<right[2,0]
    np.testing.assert_allclose((left+right)/2,[[50,40]]*3)
    with pytest.raises(ValueError):eye_pixels(q,10,100,80,[0,0],float('nan'),1)


def test_channels_swap_zero_depth_and_occlusion():
    q=np.array([[0.,0.,0.],[0,0,5.]])
    rgb=np.array([[80,80,80],[240,240,240]])
    image=render(q,rgb,10,80,60,[0,0],0)
    assert image[30,40,0]>=239
    np.testing.assert_array_equal(image[:,:,0],image[:,:,1])
    image=render(q,rgb,10,80,60,[0,0],6)
    flipped=render(q,rgb,10,80,60,[0,0],6,True)
    np.testing.assert_array_equal(image[:,:,0],flipped[:,:,1])
    np.testing.assert_array_equal(image[:,:,1],flipped[:,:,0])
    np.testing.assert_array_equal(image[:,:,1],image[:,:,2])
    # Near return occupies different pixels per eye; original pixel retains the far return.
    assert image[30,43,0]>=239 and image[30,37,1]>=239
    assert image[30,40,0]==80


def test_empty_cloud_and_stereo_overlay():
    image=render(np.empty((0,3)),np.empty((0,3)),10,80,60,[0,0],4,
                 overlays=[(np.array([[0.,-1,5],[0,1,5]]),2,True)])
    assert image.shape==(60,80,3)
    assert not np.array_equal(image[:,:,0],image[:,:,1])


def test_viewer_stereo_gates_picks_and_preserves_settings(application):
    import tkinter as tk
    from types import SimpleNamespace
    from pyproj import CRS
    w=application.workspace;v=w.viewer
    v.scene=(np.array([[0.,0,0],[1.,2,3]]),np.array([2,5]),np.array([1,2]),np.zeros(2,dtype=int),2,CRS(6447))
    v.visible=[tk.BooleanVar(value=True)];v.center=np.zeros(3);v.span=5
    v.stereo.set(True);v.stereo_depth.set(3);v.stereo_swap.set(True)
    v.draw();assert len(v.pick_ids)==0 and v.photo.width()>0
    captured=[];v.on_point=captured.append;v.on_section=captured.append
    assert v.pick_point(SimpleNamespace(x=0,y=0))=='break'
    assert v.pick_section(SimpleNamespace(x=0,y=0))=='break'
    assert not captured
    w.capture();assert w.tracker.data['view']['stereo']
    assert w.tracker.data['view']['stereo_depth']==3
    assert w.tracker.data['view']['stereo_swap']
    v.visible[0].set(False);v.draw()
    v.stereo.set(False);v.draw()


def test_picking_motion_never_reuses_orbit_anchor(root):
    from pyargus.viewer3d import Viewer
    from types import SimpleNamespace as E
    v=Viewer(root)
    try:
        v.press(E(x=0,y=0,num=1,state=0))
        v.orbit(E(x=10,y=10,state=0))
        before=(v.yaw,v.pitch,v.zoom,v.pan.copy())
        v.pick_point(E(x=500,y=500,state=1))
        v.orbit(E(x=501,y=501,state=1))
        v.orbit(E(x=502,y=502,state=0))
        assert (v.yaw,v.pitch,v.zoom)==before[:3]
        np.testing.assert_array_equal(v.pan,before[3])
        v.double_click(E(state=1))
        assert v.zoom==before[2]
        v.press(E(x=20,y=20,num=1,state=0))
        v.orbit(E(x=25,y=20,state=0))
        assert v.yaw==before[0]+2
        assert v.canvas.bind('<Shift-Double-Button-1>')
        assert v.canvas.bind('<Control-Double-Button-1>')
    finally:v.close()


def test_feature_pick_keeps_workflow_header_and_camera(application):
    from types import SimpleNamespace as E
    w=application.workspace;v=w.viewer
    header=w.here.get();camera=(v.yaw,v.pitch,v.zoom)
    w.picked_point(dict(x=1,y=2,z=3,file='long-path/'*100+'cloud.las'))
    assert w.here.get()==header
    assert (v.yaw,v.pitch,v.zoom)==camera
