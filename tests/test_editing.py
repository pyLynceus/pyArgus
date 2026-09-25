import json
from threading import Event
import numpy as np
import pytest
import laspy
from pyproj import CRS
from pyargus.sections import extract_section
from pyargus.editing import EditSession, polygon_mask
from tests.test_gui import root


def make_session(tmp_path, fmt=6, limit=10000):
    source=tmp_path/'input.las'
    h=laspy.LasHeader(point_format=fmt,version='1.4' if fmt>=6 else '1.2')
    h.add_crs(CRS(6447));h.scales=[.001]*3
    h.add_extra_dim(laspy.ExtraBytesParams(name='custom',type=np.float32))
    h.vlrs.append(laspy.VLR(user_id='test',record_id=42,description='preserve',record_data=b'abc'))
    data=laspy.LasData(h)
    x,y=np.meshgrid(np.arange(20.),np.arange(-2.,3.))
    data.x=x.ravel()+1000;data.y=y.ravel()+2000;data.z=100+x.ravel()*.1
    data.classification=np.full(x.size,2,dtype=np.uint8)
    data.synthetic=np.ones(x.size,dtype=np.uint8);data.withheld=np.arange(x.size)%2
    data.intensity=np.arange(x.size,dtype=np.uint16);data.custom=np.arange(x.size,dtype=np.float32)*.7
    data.gps_time=np.arange(x.size)+1e8
    data.write(source)
    section=extract_section([source],[1000,2000],[1019,2000],2,limit=limit,chunk_size=13)
    return source,section


def test_inclusive_polygon_and_large_coordinates():
    vertices=[[0,1e6],[2,1e6],[2,1e6+2],[0,1e6+2]]
    pts=[[0,1e6],[1,1e6+1],[2,1e6+2],[3,1e6+1]]
    assert polygon_mask(pts,vertices).tolist()==[True,True,True,False]
    assert polygon_mask(pts,vertices[::-1]).tolist()==[True,True,True,False]
    with pytest.raises(ValueError):polygon_mask(pts,[[0,0],[1,1],[2,2]])


@pytest.mark.parametrize('fmt,ext',[(3,'.las'),(6,'.las'),(6,'.laz')])
def test_export_changes_only_intended_classification_bytes(tmp_path,fmt,ext):
    source,section=make_session(tmp_path,fmt)
    session=EditSession(section)
    chosen=session.select([[2,100],[7,100],[7,102],[2,102]])
    assert len(chosen)==18  # 6 stations across all three depth rows
    session.assign(chosen,6);session.assign(chosen[:2],7)
    session.undo();assert np.all(session.classes[chosen]==6)
    session.redo();assert np.all(session.classes[chosen[:2]]==7)
    original=source.read_bytes();destination=tmp_path/('out'+ext)
    report=session.export(destination,chunk_size=7)
    expected=laspy.read(source);after=laspy.read(destination)
    cls=np.asarray(expected.classification).copy();cls[session.indices]=session.classes
    expected.classification=cls
    assert expected.points.array.tobytes()==after.points.array.tobytes()
    assert source.read_bytes()==original
    assert report['changed']==18 and report['points']==100
    assert json.loads(destination.with_suffix(ext+'.edits.json').read_text())['status']=='verified'
    with pytest.raises(ValueError,match='new output'):session.export(destination)


def test_sampled_and_multifile_sections_refused(tmp_path):
    _,section=make_session(tmp_path,limit=3)
    with pytest.raises(ValueError,match='sampled'):EditSession(section)
    section.inputs*=2
    with pytest.raises(ValueError,match='exactly one'):EditSession(section)


def test_undo_branch_class_limit_and_source_change(tmp_path):
    source,section=make_session(tmp_path,fmt=3);session=EditSession(section)
    with pytest.raises(ValueError,match='31'):session.assign([0],32)
    session.assign([0,1],6);session.undo();session.assign([1],7)
    session.redo();assert session.classes[0]==2 and session.classes[1]==7
    source.touch()
    with pytest.raises(ValueError,match='changed'):session.export(tmp_path/'out.las')


def test_cancel_leaves_no_published_or_temporary_files(tmp_path):
    _,section=make_session(tmp_path);session=EditSession(section);session.assign([0],6)
    cancel=Event()
    def progress(s):cancel.set()
    with pytest.raises(InterruptedError):session.export(tmp_path/'out.las',cancel=cancel,progress=progress,chunk_size=7)
    assert sorted(p.name for p in tmp_path.iterdir())==['input.las']


def test_metadata_evlrs_preserved(tmp_path):
    source,_=make_session(tmp_path)
    from laspy.vlrs.vlrlist import VLRList
    data=laspy.read(source);data.evlrs=VLRList([laspy.VLR(user_id='test',record_id=99,record_data=b'extended')]);data.write(source)
    section=extract_section([source],[1000,2000],[1019,2000],2)
    session=EditSession(section);session.assign([0],255)
    session.export(tmp_path/'out.las')
    assert laspy.read(tmp_path/'out.las').evlrs[0].record_data_bytes()==b'extended'


def test_corrupted_export_never_published(tmp_path,monkeypatch):
    _,section=make_session(tmp_path);session=EditSession(section);session.assign([0],6)
    real=laspy.LasWriter.write_points
    def corrupt(writer,points):
        points.X=np.asarray(points.X)+1
        real(writer,points)
    monkeypatch.setattr(laspy.LasWriter,'write_points',corrupt)
    with pytest.raises(ValueError,match='record verification'):session.export(tmp_path/'out.las')
    assert sorted(p.name for p in tmp_path.iterdir())==['input.las']


def test_editor_selection_and_undo(root,tmp_path):
    from pyargus.editing_gui import SectionEditor
    _,section=make_session(tmp_path)
    editor=SectionEditor(root,section);root.update()
    editor.pick(np.array([2.,100.]));editor.pick(np.array([7.,102.]))
    assert len(editor.selected)==18
    editor.target.set('6');editor.assign();assert editor.session.changed==18
    editor.undo();assert editor.session.changed==0
    editor.redo();assert editor.session.changed==18
    editor.undo();editor.close()


def test_main_close_respects_unsaved_editor_and_export(root,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from pyargus.editing_gui import SectionEditor
    from pyargus.gui import Application
    _,section=make_session(tmp_path)
    editor=SectionEditor(root,section);root.update()
    editor.session.assign([0],6)
    monkeypatch.setattr('tkinter.messagebox.askyesno',lambda *a,**k:False)
    calls=[]
    fake=SimpleNamespace(workspace=SimpleNamespace(review=SimpleNamespace(editor=editor),close=lambda:calls.append('close')),
        runner=SimpleNamespace(running=False),root=SimpleNamespace(destroy=lambda:calls.append('destroy')))
    Application._confirm_close(fake)
    assert calls==[] and editor.window.winfo_exists()
    editor.busy=True
    Application._confirm_close(fake)
    assert calls==[] and editor.cancel.is_set()
    editor.busy=False;editor.session.undo()
    Application._confirm_close(fake)
    assert calls==['close','destroy']
