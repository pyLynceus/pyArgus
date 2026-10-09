import json
import threading
import time
from pathlib import Path
import numpy as np
import pytest
from pyargus.classify import tiles,job
from tests.test_tiled_ground import scene,reader_for
from tests.test_gui import application,root
from tests.test_review_workspace import cloud

@pytest.mark.parametrize("seed",[2,17])
def test_parallel_surface_exact_for_seams_and_masks(seed):
    x,y,z=scene(seed=seed,n=20000)
    args=dict(cell=3.,window=12.,tile_size=150.)
    a=tiles.tiled_surface(reader_for(x,y,z),[0,0],[900,900],**args)
    held={}
    b=tiles.tiled_surface(reader_for(x,y,z),[0,0],[900,900],workers=2,stats=held,**args)
    for name in ("dem","dem_slope","object_cells","low_cells"):
        np.testing.assert_array_equal(getattr(a,name),getattr(b,name))
    assert held["workers"]==2 and held["peak_tasks"]==2
    assert held["estimated_peak_bytes"]<=held["memory_mb"]*1024**2

def test_reader_and_progress_are_serial_but_compute_is_parallel(monkeypatch):
    owner=threading.get_ident()
    x,y=np.meshgrid(np.arange(31.),np.arange(31.));x=x.ravel();y=y.ravel();z=np.full(len(x),100.)
    read=reader_for(x,y,z);compute=tiles.ground_mod.ground_surface
    active=0;peak=0;lock=threading.Lock();seen=[]
    def reader(bounds):
        assert threading.get_ident()==owner
        return read(bounds)
    def worker(*args,**kwargs):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active)
        try:
            time.sleep(.015)
            return compute(*args,**kwargs)
        finally:
            with lock:active-=1
    def progress(*args):
        assert threading.get_ident()==owner
        seen.append(args[0])
    monkeypatch.setattr(tiles.ground_mod,"ground_surface",worker)
    tiles.tiled_surface(reader,[0,0],[30,30],cell=1.,window=2.,tile_size=10.,workers=2,progress=progress)
    assert peak==2 and seen==list(range(1,len(seen)+1))

def test_worker_failures_cancel_without_publishing(tmp_path,monkeypatch):
    src=tmp_path/"source.las";cloud(src)
    out=tmp_path/"result.las"
    def fail(*args,**kwargs):
        raise RuntimeError("worker failure")
    monkeypatch.setattr(tiles.ground_mod,"ground_surface",fail)
    with pytest.raises(RuntimeError,match="worker failure"):
        job.classify_ground_tiled(src,out,cell=1.,window=2.,tile_size=10.,workers=2,log=lambda _:None)
    assert not out.exists()
    records=list(tmp_path.glob("*.job-*.json"))
    assert records and json.loads(records[0].read_text())["status"]=="failed"
    assert not list(tmp_path.glob(".pyargus-classify-*"))

def test_stop_during_tiles_leaves_no_output_or_pool_threads(tmp_path):
    src=tmp_path/"source.las";cloud(src)
    out=tmp_path/"result.las"
    stopped=threading.Event()
    def progress(n,total,tile):
        if n>=2:stopped.set()
    with pytest.raises(InterruptedError):
        job.classify_ground_tiled(src,out,cell=1.,window=2.,tile_size=10.,workers=2,
            should_stop=stopped.is_set,progress=progress,log=lambda _:None)
    assert not out.exists()
    assert not [t for t in threading.enumerate() if t.name.startswith("argus-ground")]
    assert json.loads(next(tmp_path.glob("*.job-*.json")).read_text())["status"]=="cancelled"

def test_memory_budget_can_limit_admitted_parallel_tasks():
    x,y=np.meshgrid(np.arange(31.),np.arange(31.));x=x.ravel();y=y.ravel();z=np.full(len(x),100.)
    stats={}
    tiles.tiled_surface(reader_for(x,y,z),[0,0],[30,30],cell=1.,window=2.,
        tile_size=10.,workers=2,memory_mb=.14,stats=stats)
    assert stats["peak_tasks"]==1
    assert stats["estimated_peak_bytes"]<=.14*1024**2
    with pytest.raises(ValueError,match="budget"):
        tiles.tiled_surface(reader_for(x,y,z),[0,0],[30,30],cell=1.,window=2.,
            tile_size=10.,workers=2,memory_mb=.01)

@pytest.mark.parametrize("workers",[0,33,True,1.5])
def test_invalid_worker_count_refused(workers):
    with pytest.raises(ValueError,match="workers"):
        tiles.tiled_surface(lambda _:None,[0,0],[100,100],workers=workers)

def test_gui_tiled_classification_records_workers(application,tmp_path):
    src=tmp_path/"input.las";cloud(src)
    out=tmp_path/"ground.las"
    app=application;app.cloud_path.set(str(src))
    stage=next(s for s in app.stages if type(s).__name__=="ClassifyStage")
    stage.out_path.set(str(out));stage.cell.set("1");stage.window.set("2")
    stage.processing.set("Tiled / multicore");stage.tile_size.set("10");stage.workers.set("2")
    class Runner:
        products=[]
        def log(self,text):pass
        def cancelled(self):return False
    runner=Runner();stage.prepare()(runner)
    assert out.is_file() and runner.products==[("classified",out)]
    record=json.loads(next(tmp_path.glob("*.job-*.json")).read_text())
    assert record["settings"]["workers"]==2
    assert record["results"]["workers"]==2
