from copy import deepcopy
import numpy as np
import pytest
from pyargus.route_sections import corridor_at,route_xy
from tests.test_review_workspace import root,pair,wait,record
from tests.test_gui import application


def test_station_is_xy_and_section_left_to_right():
    vertices=[[1000,2000,0],[1000,2000,20],[1030,2040,900]]
    a,b,total=corridor_at(vertices,25,20,3)
    assert total==50
    np.testing.assert_allclose((a+b)/2,[1015,2020])
    np.testing.assert_allclose(a-b,[-16,12])
    assert np.dot(b-a,[30,40])==pytest.approx(0)
    np.testing.assert_allclose(corridor_at(vertices,50,20,3)[0],[1022,2046])


def test_bend_bisector_reverse_and_closed_end():
    points=[[0,0],[10,0],[10,10]]
    a,b,total=corridor_at(points,10,10,2)
    np.testing.assert_allclose((a+b)/2,[10,0])
    assert a[0]<10 and a[1]>0
    reverse_a,reverse_b,_=corridor_at(points[::-1],10,10,2)
    np.testing.assert_allclose(reverse_a,b);np.testing.assert_allclose(reverse_b,a)
    a,b,total=corridor_at([[0,0],[10,0],[10,10],[0,0]],20+np.sqrt(200),10,2)
    np.testing.assert_allclose((a+b)/2,[0,0],atol=1e-12)
    with pytest.raises(ValueError,match='reverses'):corridor_at([[0,0],[10,0],[0,0]],10,10,2)


@pytest.mark.parametrize('station,span,width',[(float('nan'),10,2),(-1,10,2),(11,10,2),(0,0,2),(0,10,-1)])
def test_bad_route_settings(station,span,width):
    with pytest.raises(ValueError):corridor_at([[0,0],[10,0]],station,span,width)


@pytest.mark.parametrize('points',[[[0,0]],[[0,0,0],[0,0,10]],[[0,0],[float('inf'),1]]])
def test_bad_route_geometry(points):
    with pytest.raises(ValueError):route_xy(points)


def make_layer(tmp_path):
    from pyargus.linework import read_dxf
    import ezdxf
    p=tmp_path/'route.dxf';doc=ezdxf.new();doc.units=21
    doc.modelspace().add_polyline3d([(1000,2000,100),(1050,2000,101),(1100,2000,102)])
    doc.modelspace().add_line((5000,5000,100),(5010,5000,100))
    doc.saveas(p)
    return read_dxf(p,6447)[0][0]


def test_route_gui_extraction_endpoints_restore_and_guards(root,pair,tmp_path):
    from pyargus.review_gui import ReviewWorkspace
    w=ReviewWorkspace(root);errors=[];w.error=lambda exc:errors.append(str(exc))
    try:
        w.open_record(record(pair,tmp_path));w.confirm.set(True);w.load_clouds();wait(root,w)
        layer=make_layer(tmp_path);w.route.layers=lambda:[layer]
        w.route.activate(layer,0)
        assert not w.busy and w.route.state['segment']==0
        # Multiple sources require an explicit choice before moving anything.
        before=[v.get() for v in w.coords];w.route.run(w.route.go)
        assert errors and [v.get() for v in w.coords]==before
        w.section_source.set('Compare all loaded clouds');w.use_cache.set(False)
        w.route.span.set('20');w.route.station.set('25');w.width.set('2');w.step_distance.set('25')
        w.route.go();wait(root,w)
        assert w.section.start==[1025.,2010.] and w.section.end==[1025.,1990.]
        assert w.section.matched==66 and len(w.section.inputs)==2
        w.tabs.select(w.inspect_tab);assert w.route.key(1)=='break';wait(root,w)
        assert w.route.state['station']==50 and w.section.start[0]==1050
        previous=deepcopy(w.route.state);w.busy=True;w.route.key(1);w.busy=False
        assert w.route.state==previous
        w.step_distance.set('100');w.route.go(1);wait(root,w)
        assert w.route.state['station']==100
        w.route.go(1);assert not w.busy and 'End' in w.route.note.get()
        saved=deepcopy(w.route.state);w.route.stop();w.route.restore(saved)
        assert w.route.state==saved and not w.busy
        # Manual A/B picking exits route mode.
        w.pick(np.array([1010.,2000.]));assert w.route.state is None
        w.route.restore(saved)
        from pathlib import Path
        Path(layer['source']['path']).write_text('changed')
        w.route.run(w.route.go);assert 'DXF changed' in errors[-1] and not w.busy
        w.route.layers=lambda:[];w.route.run(w.route.go)
        assert 'removed' in errors[-1]
    finally:w.close()


def test_workspace_route_persistence_and_detail_preserves_section(application,tmp_path):
    from tests.test_review_workspace import cloud
    from pyargus.sections import extract_section
    w=application.workspace;v=w.viewer
    p=tmp_path/'cloud.las';cloud(p)
    v.load([str(p)]);wait(application.root,v);w.poll()
    layer=make_layer(tmp_path);w.linework.imported([layer],{})
    w.review.route.activate(layer,0);w.capture()
    assert w.tracker.data['section_route']==w.review.route.state
    w.review.section=extract_section([p],[1025,2010],[1025,1990],2)
    section=w.review.section
    # A fresh display sample with unchanged files must not discard the section.
    v.scene=tuple([v.scene[0].copy(),*v.scene[1:]])
    w.poll();assert w.review.section is section
    cloud(p,dz=2);v.scene=tuple([v.scene[0].copy(),*v.scene[1:]])
    w.poll();assert w.review.section is None
