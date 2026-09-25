import os
from threading import Event
import laspy
import numpy as np
import pytest
from pyproj import CRS
from pyargus.sections import extract_section
from reference.section_cache import build,extract,load


def cloud(path):
    las=laspy.LasData(laspy.LasHeader(point_format=6,version='1.4'))
    las.header.add_crs(CRS('EPSG:6447'));las.header.scales=[.001]*3
    x,y=np.meshgrid(np.arange(-20.,21.),np.arange(-20.,21.))
    order=np.random.default_rng(3).permutation(x.size)
    las.x=x.ravel()[order];las.y=y.ravel()[order];las.z=100+las.x*.01
    las.classification=np.resize(np.array([0,1,2,7,18],dtype='u1'),x.size)
    las.point_source_id=np.arange(x.size,dtype='u2')%3
    las.write(path)


def equal(a,b):
    assert a.matched==b.matched and a.matched_by_file==b.matched_by_file
    assert a.inputs==b.inputs and a.crs==b.crs
    for field in ('points','classes','lines','files','point_indices'):
        np.testing.assert_array_equal(getattr(a,field),getattr(b,field))


@pytest.mark.parametrize('start,end,width,limit',[
    ([-20,0],[20,0],2,100000),([-20,-20],[20,20],3,17),
    ([20,0],[-20,0],10,7),([100,100],[110,100],1,10),
    ([-20,-20],[20,20],100,1),([-10,-10],[-10,10],.01,100000)])
def test_exact_multi_file_sections(tmp_path,start,end,width,limit):
    paths=[tmp_path/'a.las',tmp_path/'b.las'];caches=[tmp_path/'a',tmp_path/'b']
    for p,c in zip(paths,caches):cloud(p);build(p,c,cell=5,chunk_size=113)
    expected=extract_section(paths,start,end,width,limit=limit,chunk_size=113)
    stats={};actual=extract(caches,start,end,width,limit=limit,stats=stats)
    equal(expected,actual)
    assert stats['candidate_points']<=stats['source_points']


def test_stale_missing_and_corrupt_cache_refused(tmp_path):
    p=tmp_path/'a.las';cloud(p);c=tmp_path/'cache';build(p,c)
    original=p.stat();os.utime(p,ns=(original.st_atime_ns,original.st_mtime_ns+1000000))
    with pytest.raises(ValueError,match='Stale'):load(c)
    os.utime(p,ns=(original.st_atime_ns,original.st_mtime_ns))
    chunk=c/'chunk_000000.npy';chunk.write_bytes(b'invalid')
    with pytest.raises(ValueError,match='chunk changed'):load(c)
    chunk.unlink()
    with pytest.raises(FileNotFoundError):load(c)


def test_cancellation_does_not_publish_or_replace(tmp_path):
    p=tmp_path/'a.las';cloud(p);c=tmp_path/'cache';stop=Event();stop.set()
    with pytest.raises(InterruptedError):build(p,c,cancel=stop)
    assert not c.exists()
    build(p,c)
    with pytest.raises(FileExistsError):build(p,c)
    with pytest.raises(InterruptedError):extract([c],[0,0],[1,1],1,cancel=stop)


def test_duplicate_sources_refused(tmp_path):
    p=tmp_path/'a.las';cloud(p);c=tmp_path/'cache';build(p,c)
    with pytest.raises(ValueError,match='Duplicate'):extract([c,c],[0,0],[1,1],1)


def test_random_oblique_sections_at_large_coordinates(tmp_path):
    p=tmp_path/'a.las';cloud(p)
    data=laspy.read(p);data.x=np.asarray(data.x)+2000000.;data.y=np.asarray(data.y)+1500000.;data.write(p)
    c=tmp_path/'cache';build(p,c,cell=5,chunk_size=113)
    rng=np.random.default_rng(123)
    for _ in range(24):
        start=rng.uniform(-30,30,2)+[2000000,1500000]
        end=rng.uniform(-30,30,2)+[2000000,1500000]
        width=float(rng.choice([.001,.5,3,15,100]));limit=int(rng.choice([1,13,100000]))
        equal(extract_section([p],start,end,width,limit=limit,chunk_size=113),extract([c],start,end,width,limit=limit))


def test_interrupted_build_cleans_partial_cache(tmp_path):
    p=tmp_path/'a.las';cloud(p);c=tmp_path/'cache'
    class StopAfterFirstChunk:
        calls=0
        def is_set(self):
            self.calls+=1
            return self.calls>=3
    with pytest.raises(InterruptedError):build(p,c,chunk_size=113,cancel=StopAfterFirstChunk())
    assert not c.exists() and not list(tmp_path.glob('.section-cache-*'))
