import json
import pytest
from pyargus.imagery.job import resolve_cameras

def frame(root,name,**extra):
    root.mkdir(parents=True,exist_ok=True)
    image=root/name;image.touch()
    params=dict(CalibratedFocalLength=1000,ImageWidth=600,ImageHeight=400)
    params.update(extra)
    image.with_name(name+'.cal').write_text(json.dumps([params]))
    return image

def resolve(images,**kw):
    return resolve_cameras({'filename':[p.name for p in images]},
                           {p.name.lower():p for p in images},**kw)

@pytest.mark.parametrize('changed',[
    {'CalibratedFocalLength':1001}, {'CalibratedCY':22},
    {'CalibratedK1':.04}, {'CalibratedP2':.001}, {'ImageWidth':602}])
def test_later_same_role_conflict_refuses(tmp_path,changed):
    a=frame(tmp_path,'flight_N_001.JPG')
    b=frame(tmp_path,'flight_N_002.JPG',**changed)
    with pytest.raises(ValueError,match='conflicting calibrations for camera role N'):
        resolve([a,b])
    with pytest.raises(ValueError,match='conflicting calibrations'):
        resolve([b,a])

def test_equivalent_sidecars_have_per_image_provenance(tmp_path):
    a=frame(tmp_path,'flight_N_001.JPG',Comment='first')
    b=frame(tmp_path,'flight_N_002.JPG',Comment='second',CalibratedK1=0)
    records=[];cams=resolve([a,b,a],provenance=records)
    assert list(cams)==['N']
    assert len(records)==2 and records[0]['sha256']!=records[1]['sha256']
    assert records[0]['parameters']==records[1]['parameters']

def test_distinct_roles_keep_different_lenses(tmp_path):
    a=frame(tmp_path,'flight_N_001.JPG')
    b=frame(tmp_path,'flight_P_001.JPG',CalibratedFocalLength=1100)
    cams=resolve([a,b]);assert cams['N'].focal_px!=cams['P'].focal_px

def test_later_frame_without_calibration_refuses(tmp_path):
    a=frame(tmp_path/'one','flight_N_001.JPG')
    b=tmp_path/'two'/'flight_N_002.JPG';b.parent.mkdir();b.touch()
    with pytest.raises(ValueError,match='no .cal calibration sidecar'):
        resolve([a,b])

def test_explicit_override_is_logged_in_provenance(tmp_path):
    a=frame(tmp_path,'flight_N_001.JPG')
    b=frame(tmp_path,'flight_N_002.JPG',CalibratedCY=22)
    records=[]
    resolve([a,b],cal=a.with_name(a.name+'.cal'),provenance=records)
    assert all(r['selection']=='explicit' for r in records)
    assert len({r['sha256'] for r in records})==1
