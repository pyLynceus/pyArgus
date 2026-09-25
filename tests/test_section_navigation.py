import numpy as np
import pytest
from pyargus.section_navigation import stepped_corridor
from tests.test_review_workspace import root, pair, wait, record


@pytest.mark.parametrize("start,end", [([0,0],[10,0]),([0,0],[0,10]),([2600000,1200000],[2600003,1200004])])
def test_step_preserves_geometry_and_round_trip(start,end):
    a,b=stepped_corridor(start,end,3,10,1)
    delta=np.subtract(end,start)
    np.testing.assert_allclose(b-a,delta)
    assert np.linalg.norm(a-start)==pytest.approx(10)
    assert np.dot(a-start,delta)==pytest.approx(0,abs=1e-8)
    shift=a-start
    assert delta[0]*shift[1]-delta[1]*shift[0]>0
    aa,bb=stepped_corridor(a,b,3,10,-1)
    np.testing.assert_allclose(aa,start,atol=1e-9)
    np.testing.assert_allclose(bb,end,atol=1e-9)


@pytest.mark.parametrize("distance",[0,-1,float('nan'),float('inf')])
def test_invalid_distance(distance):
    with pytest.raises(ValueError,match="Step distance"):
        stepped_corridor([0,0],[10,0],3,distance,1)


def test_invalid_corridor():
    with pytest.raises(ValueError): stepped_corridor([0,0],[0,0],3,10,1)
    with pytest.raises(ValueError): stepped_corridor([0,0],[10,0],0,10,1)


def test_gui_step_extract_busy_invalid_and_empty(root,pair,tmp_path):
    from pyargus.review_gui import ReviewWorkspace
    w=ReviewWorkspace(root)
    errors=[];w.error=lambda exc:errors.append(str(exc))
    try:
        w.open_record(record(pair,tmp_path));w.confirm.set(True);w.load_clouds();wait(root,w)
        w.section_source.set('Compare all loaded clouds')
        w.pick(np.array([1010.,2000.]));w.pick(np.array([1020.,2000.]))
        w.width.set('2');w.step_distance.set('2');w.use_cache.set(False)
        w.step_section(1);wait(root,w)
        assert w.section.start==[1010.,2002.] and w.section.matched==66
        assert w.section.width==2 and len(w.section.inputs)==2
        w.step_section(-1);wait(root,w)
        assert w.section.start==[1010.,2000.]
        previous=w.section;coords=[v.get() for v in w.coords]
        w.step_distance.set('nan');w.step_section(1)
        assert errors and w.section is previous and [v.get() for v in w.coords]==coords
        w.busy=True;w.step_section(1);w.extract();w.busy=False
        assert w.section is previous and [v.get() for v in w.coords]==coords
        w.step_distance.set('100');w.step_section(1);wait(root,w)
        assert w.section.matched==0 and len(w.profile.xy)==0
    finally:w.close()
