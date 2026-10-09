from threading import Event
import numpy as np
import pytest
from pyargus.viewport_cache import extract
from pyargus.viewer3d import sample_viewport
from pyargus.section_cache_store import CacheStore
from tests.test_review_workspace import cloud,wait
from tests.test_gui import root


@pytest.mark.parametrize('yaw,pitch,depth,bounds',[(0,90,0,(10,20,-1,1)),(30,45,0,(-10,30,-4,10)),(70,5,4,(-5,30,-10,10)),(0,0,6,(500,600,500,600))])
def test_cached_viewport_equals_scan(tmp_path,yaw,pitch,depth,bounds):
    paths=[tmp_path/'a.las',tmp_path/'b.las']
    for i,p in enumerate(paths):cloud(p,dz=i*.25)
    store=CacheStore(tmp_path/'cache');store.build(paths)
    a=extract(store,paths,[1000,2000,100],yaw,pitch,bounds,limit=17,stereo_depth=depth)
    b=sample_viewport(paths,[1000,2000,100],yaw,pitch,bounds,limit=17,stereo_depth=depth)
    for left,right in zip(a[:5],b[:5]):np.testing.assert_array_equal(left,right)
    assert a[5]==b[5]


def test_changed_and_cancelled_cache(tmp_path):
    p=tmp_path/'a.las';cloud(p);store=CacheStore(tmp_path/'cache');store.build([p])
    cancel=Event();cancel.set()
    with pytest.raises(InterruptedError):extract(store,[p],[1000,2000,100],0,90,(0,10,-2,2),cancel=cancel)
    cloud(p,dz=2)
    with pytest.raises(OSError):extract(store,[p],[1000,2000,100],0,90,(0,10,-2,2))


def test_auto_debounce_latest_view_stop_and_stereo(root,tmp_path,monkeypatch):
    from pyargus.viewer3d import Viewer
    import pyargus.viewer3d as module
    import time
    p=tmp_path/'a.las';cloud(p);v=Viewer(root)
    try:
        v.view_cache=CacheStore(tmp_path/'cache');v.view_cache.build([p])
        v.load([str(p)]);wait(root,v)
        v.auto_detail.set(True);v.stereo.set(True);v.reset_auto()
        v.auto_tick();assert not v.busy
        v.auto_moved=time.monotonic()-1;v.auto_tick();assert v.busy
        # Tk may settle canvas geometry after loading; that legitimately cancels
        # the first query and schedules a new one for the final viewport.
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and 'Local cache detail' not in v.detail_note.get():
            root.update();time.sleep(.01)
        assert 'Local cache detail' in v.detail_note.get(), v.status.get()
        v.auto_tick();assert not v.busy
        # Old camera results cannot replace the current scene.
        oldkey=v.view_key();scene=v.scene
        v.pan+=10
        v.messages.put(('done',('refined',scene,oldkey,'old')));v.poll()
        assert 'old'!=v.detail_note.get()
        v.stop_loading();assert not v.auto_detail.get()
        # Missing caches never trigger a full scan in automatic mode.
        v.view_cache=CacheStore(tmp_path/'missing')
        monkeypatch.setattr(module,'sample_viewport',lambda *a,**k:pytest.fail('Automatic full scan'))
        v.refine(automatic=True);wait(root,v)
        assert 'Build view cache' in v.status.get()
    finally:v.close()
