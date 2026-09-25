import json
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import laspy
import numpy as np
import pytest
from pyargus.section_cache_store import CacheStore,CacheBusy
from pyargus.sections import extract_section
from tests.test_review_workspace import cloud,wait
from tests.test_gui import root
from tests.test_section_cache import equal


@pytest.fixture
def cache_case(tmp_path):
    p=tmp_path/'source.las';cloud(p)
    data=laspy.read(p);data.x=1000+(np.asarray(data.x)-1000)*10;data.write(p)
    return p,CacheStore(tmp_path/'cache-root')


def test_reuse_exact_query_and_explicit_disabled_fallback(cache_case):
    p,store=cache_case;messages=[]
    assert '1 built' in store.build([p],progress=messages.append)
    assert messages and '1 reused' in store.build([p])
    expected=extract_section([p],[1010,2000],[1030,2000],2)
    actual,method=store.extract([p],[1010,2000],[1030,2000],2)
    assert method=='Spatial cache';equal(expected,actual)
    broad,method=store.extract([p],[1000,2000],[2000,2000],20)
    assert method.startswith('Full scan — broad')
    equal(extract_section([p],[1000,2000],[2000,2000],20),broad)


def test_stale_damaged_missing_cache_falls_back(cache_case):
    p,store=cache_case
    for damage in ('missing','manifest','chunk','source'):
        store.clear();store.build([p]);target=store.path(p)
        if damage=='missing':(target/'manifest.json').unlink()
        if damage=='manifest':(target/'manifest.json').write_text('{}')
        if damage=='chunk':(target/'chunk_000000.npy').write_bytes(b'damaged')
        if damage=='source':
            s=p.stat();os.utime(p,ns=(s.st_atime_ns,s.st_mtime_ns+1000000))
        actual,method=store.extract([p],[1010,2000],[1030,2000],2)
        assert method.startswith('Full scan')
        equal(extract_section([p],[1010,2000],[1030,2000],2),actual)


def test_low_space_cancel_and_busy_refuse_or_fallback(cache_case,monkeypatch):
    p,store=cache_case
    with monkeypatch.context() as context:
        context.setattr('pyargus.section_cache_store.shutil.disk_usage',lambda _:SimpleNamespace(free=0))
        with pytest.raises(OSError,match='Insufficient'):store.build([p])
        assert not store.path(p).exists()
    store.build([p]);stop=Event();stop.set()
    with pytest.raises(InterruptedError):store.extract([p],[1010,2000],[1030,2000],2,cancel=stop)
    with store.locked():
        with pytest.raises(CacheBusy):store.clear()
        result,method=store.extract([p],[1010,2000],[1030,2000],2)
        assert method=='Full scan — cache busy' and result.matched>0


def test_cleanup_retains_sources_and_unrelated_files(cache_case):
    p,store=cache_case;before=p.read_bytes();store.build([p])
    unrelated=store.root/'personal-notes';unrelated.mkdir();(unrelated/'keep.txt').write_text('keep')
    outside=p.parent/'outside';outside.mkdir();(outside/'keep.txt').write_text('keep')
    with pytest.raises(ValueError):store.remove_owned(outside)
    assert '1 local' in store.clear()
    assert p.read_bytes()==before and (unrelated/'keep.txt').exists() and (outside/'keep.txt').exists()


def test_gui_build_extract_disable_and_clear(root,cache_case):
    from pyargus.review_gui import ReviewWorkspace
    p,store=cache_case;w=ReviewWorkspace(root);w.cache_store=store
    try:
        w.layers=[dict(path=str(p.resolve()),role='Manual',state='available')]
        w.refresh_files();w.filelist.selection_set(0);w.confirm.set(True);w.load_clouds();wait(root,w)
        for var,value in zip(w.coords,[1010,2000,1030,2000]):var.set(str(value))
        w.width.set('2');w.build_section_cache();wait(root,w)
        assert 'Cache ready' in w.cache_status.get()
        w.extract();wait(root,w);assert w.cache_status.get()=='Spatial cache'
        expected=w.section
        w.use_cache.set(False);w.extract();wait(root,w)
        assert 'disabled' in w.cache_status.get();equal(expected,w.section)
        w.clear_section_caches();wait(root,w)
        assert 'Cleared 1' in w.cache_status.get() and p.exists()
    finally:w.close()
