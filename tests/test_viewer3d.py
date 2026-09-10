import numpy as np
import pytest
from tests.test_gui import root
from pyargus.viewer3d import project_points, sample_clouds, colors, Viewer


def test_camera_rotates_height_and_preserves_distances():
    origin=np.array([2400000.,400000.,800.])
    p=origin+np.eye(3)
    front=project_points(p,origin,0,0)
    top=project_points(p,origin,0,90)
    np.testing.assert_allclose(front[2,:2],[0,1],atol=1e-12)
    np.testing.assert_allclose(top[2,:2],[0,0],atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(project_points(p,origin,31,47),axis=1),1)


def cloud(path,n=1000,epsg=6447):
    import laspy
    from pyproj import CRS
    h=laspy.LasHeader(point_format=3,version='1.2'); h.add_crs(CRS.from_epsg(epsg))
    d=laspy.LasData(h)
    d.x=np.arange(n)+2400000.; d.y=np.arange(n)%100+400000.; d.z=np.arange(n)%30+800.
    d.classification=np.full(n,2); d.point_source_id=np.full(n,7)
    d.write(path)


def test_bounded_multifile_sample_and_cancel(tmp_path):
    from threading import Event
    a,b=tmp_path/'a.las',tmp_path/'b.las'
    cloud(a); cloud(b)
    p,c,l,f,total,crs=sample_clouds([a,b],limit=77)
    assert len(p)<=77 and total==2000 and set(f)=={0,1}
    assert np.all(c==2) and np.all(l==7)
    event=Event(); event.set()
    with pytest.raises(InterruptedError): sample_clouds([a],cancel=event)
    cloud(b,epsg=26916)
    with pytest.raises(ValueError,match='differ'): sample_clouds([a,b])


def test_viewer_renders_orbit_and_empty_visibility(root):
    import tkinter as tk
    r=root; r.withdraw()
    v=Viewer(r)
    try:
        p=np.array([[0.,0,0],[1,2,3],[3,2,1]])
        v.scene=(p,np.array([2,5,6]),np.array([1,2,3]),np.zeros(3,dtype=int),3,None)
        v.visible=[tk.BooleanVar(master=v.window,value=True)]
        v.center=np.ones(3); v.span=4
        r.update(); v.draw()
        assert v.photo.width()>0
        v.view(80,20); v.visible[0].set(False); v.draw()
        assert v.canvas.find_all()
    finally: v.close()


def test_background_load_reaches_finished(tmp_path, root):
    import gc
    gc.collect()
    path=tmp_path/'scene.las'; cloud(path)
    v=Viewer(root)
    v.load([str(path)])
    def check():
        if not v.busy: root.quit()
        else: root.after(20,check)
    timer=root.after(10000,root.quit)
    root.after(20,check); root.mainloop()
    try:
        assert not v.busy and v.scene is not None
        assert v.status.get().startswith('Finished')
        assert v.photo.width()>0
    finally:
        root.after_cancel(timer); v.close()
