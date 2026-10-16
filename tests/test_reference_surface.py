import numpy as np
import pytest
from pyargus.formats.landxml import read_landxml
from pyargus.surfaces.reference import ReferenceTin


def xml_surface(tmp_path,pnts='1:0 0 0;2:0 2 0;3:2 2 10;4:1 0 0',faces='<F>1 2 3</F><F>1 3 4</F>',extra='',unit='USSurveyFoot'):
    points=''.join('<P id="'+p.split(':')[0]+'">'+p.split(':')[1]+'</P>' for p in pnts.split(';'))
    body=f'<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2"><Units><Imperial linearUnit="{unit}"/></Units><Surfaces><Surface name="test">{extra}<Definition surfType="TIN"><Pnts>{points}</Pnts><Faces>{faces}</Faces></Definition></Surface></Surfaces></LandXML>'
    p=tmp_path/'surface.xml';p.write_text(body);return p


def test_nez_order_and_exact_nondelaunay_faces(tmp_path):
    s=read_landxml(xml_surface(tmp_path));np.testing.assert_array_equal(s.points[1],[2,0,0]);m=ReferenceTin(s.points,s.faces)
    assert m.metadata['fallback_faces']==2
    assert m.z_at(.4,.2)==pytest.approx(1.)
    assert np.isnan(m.z_at(2.1,1.))
    assert np.isnan(m.z_at(.1,1.8))
    assert s.metadata['linear_unit']=='USSurveyFoot'


def test_hidden_faces_do_not_fill_convex_hull(tmp_path):
    s=read_landxml(xml_surface(tmp_path,faces='<F>1 2 3</F><F i="1">1 3 4</F>'));m=ReferenceTin(s.points,s.faces)
    assert s.metadata['hidden_faces']==1
    assert np.isnan(m.z_at(.1,.3))
    assert m.z_at(1.5,.5)==pytest.approx(2.5)


def test_plane_large_coordinates_scalar_broadcast_and_missing():
    xy=np.array([[0.,0.],[3.,0.],[3.,4.],[0.,4.]])+[945000.,790000.];z=.25*(xy[:,0]-945000)+.5*(xy[:,1]-790000)+17
    m=ReferenceTin(np.column_stack((xy,z)),[[0,1,2],[0,2,3]])
    result=m.z_at(np.array([945001.,945002.,945004.,np.nan]),790001.)
    np.testing.assert_allclose(result[:2],[17.75,18.]);assert np.isnan(result[2:]).all();assert np.isnan(m.z_at(np.inf,790001.))


@pytest.mark.parametrize('pnts,faces,expected',[
 ('1:0 0 0;1:0 1 0;3:1 1 1','<F>1 2 3</F>','Duplicate'),
 ('1:0 0 0;2:0 1 0;3:1 1 1','<F>1 2 9</F>','Unknown'),
 ('1:0 0 nan;2:0 1 0;3:1 1 1','<F>1 2 3</F>','finite'),
 ('1:0 0 0;2:0 1 0;3:1 1 1','<F>1 1 3</F>','distinct'),
 ('1:0 0 0;2:0 1 0;3:1 1 1','<F>1 2 3</F><F>3 2 1</F>','Duplicate'),
])
def test_malformed_references_refused(tmp_path,pnts,faces,expected):
    with pytest.raises(ValueError,match=expected):read_landxml(xml_surface(tmp_path,pnts,faces))


def test_explicit_boundary_is_not_silently_ignored(tmp_path):
    p=xml_surface(tmp_path,extra='<Boundaries><Boundary bndType="hide"><PntList2D>0 0 1 0 1 1</PntList2D></Boundary></Boundaries>')
    with pytest.raises(ValueError,match='Boundary'):read_landxml(p)


@pytest.mark.parametrize('encoding',['utf-8','utf-16'])
def test_dtd_entities_refused(tmp_path,encoding):
    p=tmp_path/'bad.xml';p.write_text('<?xml version="1.0" encoding="'+encoding+'"?><!DOCTYPE LandXML [<!ENTITY x "bad">]><LandXML>&x;</LandXML>',encoding=encoding)
    with pytest.raises(ValueError,match='DTD/entity'):read_landxml(p)


def test_multiple_surfaces_require_choice(tmp_path):
    p=xml_surface(tmp_path);text=p.read_text();part=text[text.index('<Surface name='):text.index('</Surface>')+10];p.write_text(text.replace('</Surfaces>',part.replace('name="test"','name="second"')+'</Surfaces>'))
    with pytest.raises(ValueError,match='explicitly'):read_landxml(p)
    assert read_landxml(p,'second').name=='second'


def test_degenerate_xy_refused():
    with pytest.raises(ValueError,match='degenerate'):ReferenceTin([[0,0,0],[1,1,1],[2,2,3]],[[0,1,2]])
