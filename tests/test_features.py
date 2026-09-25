import json
from copy import deepcopy
import numpy as np
import pytest
from pyargus.features import Features, export_dxf
from pyargus.job_manifest import identity
from tests.test_gui import root, application
from tests.test_review_workspace import cloud, wait


@pytest.fixture
def lines(tmp_path):
    source=tmp_path/'cloud.las';cloud(source)
    m=Features(); fid=m.new('Wall top 1','Wall top')
    for p in ([1000,2000,110],[1001,2000,111],[1002,2000,112]):
        m.vertex(fid,p,identity(source),'EPSG:6447')
    return m,fid,source


def test_edit_split_join_undo_and_review(lines):
    m,fid,source=lines
    m.metadata(fid,'Wall top 1','Wall top','Accepted')
    m.update_xyz(fid,1,[1001,2000,111.5]);assert m.get(fid)['status']=='Candidate'
    m.undo();assert m.get(fid)['status']=='Accepted'
    m.redo();assert m.get(fid)['vertices'][1]['xyz'][2]==111.5
    m.split(fid,1);other=m.items[1]['id']
    assert [len(f['vertices']) for f in m.items]==[2,2]
    m.join(fid,other);assert len(m.items)==1 and len(m.get(fid)['vertices'])==3
    m.reverse(fid);assert m.get(fid)['vertices'][0]['xyz']==[1002,2000,112]
    before=deepcopy(m.items)
    with pytest.raises(ValueError):m.update_xyz(fid,0,[1,2,float('nan')])
    assert m.items==before
    with pytest.raises(ValueError):m.vertex(fid,[1,2,3],identity(source),'EPSG:26916')
    assert m.items==before
    with pytest.raises(ValueError):m.split(fid,0)


def test_export_roundtrip_provenance_units_and_no_overwrite(lines,tmp_path):
    import ezdxf
    from pyproj import CRS
    m,fid,source=lines
    with pytest.raises(ValueError,match='No features'):export_dxf(m.items,tmp_path/'empty.dxf')
    m.metadata(fid,'Wall top 1','Wall top','Accepted')
    path,side=export_dxf(m.items,tmp_path/'features.dxf')
    doc=ezdxf.readfile(path);poly=list(doc.modelspace())[0]
    assert poly.is_3d_polyline and poly.dxf.layer=='WALL_TOP_ACCEPTED'
    assert doc.units==21
    np.testing.assert_allclose([list(v.dxf.location) for v in poly.vertices],[v['xyz'] for v in m.get(fid)['vertices']])
    saved=json.loads(side.read_text());assert CRS(saved['crs'])==CRS(6447)
    assert saved['features']==m.items
    before=path.read_bytes()
    with pytest.raises(ValueError,match='new DXF'):export_dxf(m.items,path)
    assert path.read_bytes()==before
    source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='source'):export_dxf(m.items,tmp_path/'stale.dxf')
    assert not (tmp_path/'stale.dxf').exists()


def test_workspace_feature_pick_save_restore_and_tab_gating(application,tmp_path):
    from pyargus.viewer3d import sample_clouds
    app=application;w=app.workspace;f=w.features
    path=tmp_path/'cloud.las';cloud(path)
    # Load through the existing worker and allow workspace synchronization.
    w.viewer.load([str(path.resolve())]);wait(app.root,w.viewer)
    w.poll();app.root.update()
    w.tabs.select(w.features_tab);f.name.set('Barrier');f.kind.set('Barrier top');f.new()
    value=dict(x=1010.,y=2000.,z=100.,file=str(path.resolve()))
    w.picked_point(value);value.update(x=1020.,z=101.);w.picked_point(value)
    assert len(f.model.items[0]['vertices'])==2
    fid=f.selected
    w.tabs.select(w.review_tab);w.picked_point(value)
    assert len(f.model.items[0]['vertices'])==2
    f.status.set('Accepted');f.properties()
    out=tmp_path/'features.argus.json';w.path=out;w.persist()
    saved=json.loads(out.read_text());assert saved['features'][0]['status']=='Accepted'
    w.path=tmp_path/'other.argus.json'
    f.delete();assert not f.model.items
    w.restore(out);assert w.features.model.get(fid)['status']=='Accepted'
    if w.viewer.busy:wait(app.root,w.viewer)


def test_invalid_restore_and_incomplete_acceptance(lines):
    m,fid,source=lines
    bad=deepcopy(m.items);bad[0]['vertices'][0]['xyz']=[float('nan'),0,0]
    with pytest.raises(ValueError):Features(bad)
    empty=m.new('Empty','Other')
    with pytest.raises(ValueError):m.metadata(empty,'Empty','Other','Accepted')
