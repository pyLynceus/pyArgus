from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import zipfile

import numpy as np
import pytest

from pyargus.job_manifest import identity
from pyargus.review_memory import ReviewMemory
from pyargus.review_package import export_package, prepare_report
from pyargus.workspace_state import Tracker


def state(path):
    return dict(schema_version=1, inputs=[identity(path)], crs='EPSG:6447',
        camera=dict(center=[10.,20.,3.],pan_units=[0.,0.],yaw=25.,pitch=45.,zoom=1.,span=10.),
        display=dict(mode='Classification',classes='All',line='All',stereo=False,depth=2.,swap=False),
        visible=[True],section=None,section_source=str(path.resolve()),confirmed=False,route=None,
        profile=dict(mode='Dataset',line='All',exaggeration=5.),
        layout=dict(mode='Review',dock=False,pane='Cross-section',preset='Custom',split_fraction=.48,extract_on_release=False),
        details=False,references=[])


def snapshot(tmp_path, notes=True):
    a,b,c=[tmp_path/name for name in ('original.las','other.las','ground.las')]
    for p in (a,b,c):p.write_bytes(b'External cloud bytes must never be read by the review exporter.')
    t=Tracker();t.data['project']={'clouds':[str(a),str(b)],'trajectories':[]}
    j=t.begin('Classification',{'cloud':str(a)},[a]);j['stage_class']='ClassifyStage'
    t.finish(j,'Needs review',[c]);t.register_cloud_result(a,c,j['id']);t.decide('Classification','Accepted','Synthetic operator decision')
    m=ReviewMemory()
    if notes:
        m.save_view('Wall <north>',state(a));i=m.issue('=Possible <script>alert(1)</script>',state(a))
        m.update_issue(i['id'],i['title'],'Ground classification','In review','@Review wall\nKeep the original coordinates.')
    t.data['review_notes']=deepcopy(m.data)
    return dict(workspace=t.data,workspace_path=str(tmp_path/'workspace.argus.json'),title='Synthetic review',operator_note='<script>not code</script>',
        captured_utc='2026-10-01T00:00:00+00:00',review_notes=m.data,current_settings={},current_view={'state':state(a),'warning':''},
        comparison={},section={}),a,b,c


def read_package(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {name:z.read(name) for name in z.namelist()}


def test_offline_package_integrity_escaping_csv_and_metadata_only(tmp_path,monkeypatch):
    snap,a,b,c=snapshot(tmp_path);before=deepcopy(snap)
    # Invalid LAS bytes intentionally prove no LAS reader is used.
    monkeypatch.setattr(Path,'read_bytes',lambda self:pytest.fail('External content was read'))
    package=tmp_path/'review.zip';result=export_package(package,snap)
    members=read_package(package);meta=json.loads(members['package.json']);manifest=json.loads(members['manifest.json'])
    assert result['issues']==1 and result['views']==1 and snap==before
    assert meta['workflow']['coverage'].startswith('1/2 active inputs')
    assert meta['attempts'][0]['recorded_status']=='Accepted' and meta['attempts'][0]['current_status']=='Accepted'
    assert 'original.las' not in members and b'External cloud bytes' not in b''.join(members.values())
    assert b'<script>alert' not in members['report.html'] and b'&lt;script&gt;alert' in members['report.html']
    rows=list(csv.DictReader(io.StringIO(members['issues.csv'].decode('utf-8-sig'))))
    assert rows[0]['title'].startswith("'=") and rows[0]['note'].startswith("'@")
    assert ReviewMemory(json.loads(members['review-notes.json'])).data==snap['review_notes']
    assert {f['path'] for f in manifest['files']}==set(members)-{'manifest.json'}
    for item in manifest['files']:
        assert hashlib.sha256(members[item['path']]).hexdigest()==item['sha256']
        assert len(members[item['path']])==item['size_bytes']


def test_missing_changed_and_historical_records_are_exported_without_claiming_current(tmp_path):
    snap,a,b,c=snapshot(tmp_path);a.write_bytes(b'Changed original');b.unlink()
    before=deepcopy(snap);report=prepare_report(snap)
    assert report['attempts'][0]['current_status']=='Outdated' and 'input changed' in report['attempts'][0]['reason']
    assert any(s['path']==str(b) and s['status']=='Missing' for s in report['sources'])
    assert report['contexts'][0]['warnings'] and report['current_view']['source_warnings']
    export_package(tmp_path/'stale.zip',snap)
    assert snap==before


def test_preview_refuses_changed_current_sources_and_validates_member_names(tmp_path):
    from PIL import Image
    snap,a,b,c=snapshot(tmp_path);stream=io.BytesIO();Image.new('RGB',(5,5)).save(stream,format='PNG')
    image={'data':stream.getvalue(),'caption':'Current display sample'}
    with pytest.raises(ValueError,match='Invalid review preview'):
        export_package(tmp_path/'bad-preview.zip',snap,previews={'../../outside.png':image})
    a.write_bytes(b'New identity')
    with pytest.raises(ValueError,match='Current display sources changed'):
        export_package(tmp_path/'stale-preview.zip',snap,previews={'current-cloud.png':image})
    assert not list(tmp_path.glob('*.zip'))


def test_export_never_overwrites_and_racing_destination_is_preserved(tmp_path):
    snap,*_=snapshot(tmp_path);out=tmp_path/'collision.zip';out.write_bytes(b'Keep existing file')
    with pytest.raises(ValueError,match='does not overwrite'):
        export_package(out,snap)
    assert out.read_bytes()==b'Keep existing file'
    out.unlink()
    def race(message):
        if message=='Writing README.txt':out.write_bytes(b'Competing writer')
    with pytest.raises(FileExistsError):export_package(out,snap,progress=race)
    assert out.read_bytes()==b'Competing writer' and not list(tmp_path.glob('.*.tmp'))


def test_cancel_changed_source_and_size_limit_publish_no_archive(tmp_path,monkeypatch):
    snap,a,b,c=snapshot(tmp_path);flag=False
    def cancel(message):
        nonlocal flag
        if message=='Writing package.json':flag=True
    with pytest.raises(InterruptedError):export_package(tmp_path/'stop.zip',snap,progress=cancel,cancel=lambda:flag)
    assert not list(tmp_path.glob('*.zip')) and not list(tmp_path.glob('.*.tmp'))
    def change(message):
        if message=='Writing README.txt':a.write_bytes(b'Source changed while exporting')
    with pytest.raises(ValueError,match='Reference changed during export'):
        export_package(tmp_path/'changed.zip',snap,progress=change)
    monkeypatch.setattr('pyargus.review_package.MAX_MEMBER_BYTES',32)
    with pytest.raises(ValueError,match='bounded export limit'):
        export_package(tmp_path/'large.zip',snap)
    assert not list(tmp_path.glob('*.zip')) and not list(tmp_path.glob('.*.tmp'))


def test_current_section_csv_retains_both_samples_indices_and_numeric_values(tmp_path):
    from pyargus.sections import Section
    snap,a,b,c=snapshot(tmp_path);inputs=[identity(a),identity(b)]
    section=Section(np.array([[-2.,0.,1.,0.,-.1],[2.,0.,1.2,4.,.1]]),np.array([0,2]),np.array([1,2]),np.array([0,1]),np.array([8,15]),
        50,[30,20],inputs,'EPSG:6447',[-2.,0.],[2.,0.],3.,100)
    snap['section']={'inputs':inputs,'sampled':2}
    export_package(tmp_path/'section.zip',snap,section=section)
    rows=list(csv.DictReader(io.StringIO(read_package(tmp_path/'section.zip')['section-sample.csv'].decode('utf-8-sig'))))
    assert len(rows)==2 and float(rows[0]['x'])==-2. and rows[1]['source_point_index']=='15'
    assert rows[1]['source_path']==str(b) and rows[0]['classification']=='0'
    b.write_bytes(b'Changed section input')
    with pytest.raises(ValueError,match='Extracted section source changed'):
        export_package(tmp_path/'bad-section.zip',snap,section=section)


def test_workspace_autosave_during_export_does_not_invalidate_captured_snapshot(tmp_path):
    snap,*_=snapshot(tmp_path);workspace=Path(snap['workspace_path']);workspace.write_text('{}')
    def autosave(message):
        if message=='Writing README.txt':workspace.write_text('{"new_autosave":true}')
    export_package(tmp_path/'autosave.zip',snap,progress=autosave)
    assert json.loads(read_package(tmp_path/'autosave.zip')['workspace-snapshot.argus.json'])==snap['workspace']


from tests.test_gui import root, application
from tests.test_review_memory import setup


def settle(app,exporter):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        app.root.update();app.workspace.poll();time.sleep(.02)
        if exporter.pending is None and not app.runner.running:return
    raise AssertionError('Review package export timed out')


def test_gui_export_preserves_view_processing_and_decisions_and_records_receipt(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path,True);p=w.package_export
    n.issue_here();n.title.set('Wall review');n.note.insert('1.0','Verify classification beside sound barrier');n.apply_issue()
    n.model.save_view('Before alignment',n.capture_view());n.changed()
    for var,value in zip(r.coords,[1010.,2000.,1050.,2000.]):var.set(str(value))
    r.width.set('3');r.set_corridor();r.use_cache.set(False);r.extract()
    from tests.test_review_workspace import wait
    wait(application.root,r);w.poll()
    time.sleep(.35);application.root.update()
    p.include_section.set(True);v.stereo.set(True);v.zoom=2;v.pan=np.array([5.,7.]);v.draw();application.root.update_idletasks()
    before=(v.camera_state(),list(w.project_panel.clouds),application.cloud_path.get(),deepcopy(w.tracker.data['jobs']),deepcopy(w.tracker.data['decisions']))
    monkeypatch.setattr(v,'load',lambda *a,**k:pytest.fail('Unexpected cloud scan'))
    monkeypatch.setattr(r,'extract',lambda *a,**k:pytest.fail('Unexpected section extraction'))
    monkeypatch.setattr('laspy.open',lambda *a,**k:pytest.fail('Unexpected LAS read'))
    p.note.insert('1.0','Ready for client review.');p.start(tmp_path/'gui-review.zip');settle(application,p)
    assert p.result,application.runner.error
    assert before==(v.camera_state(),w.project_panel.clouds,application.cloud_path.get(),w.tracker.data['jobs'],w.tracker.data['decisions'])
    members=read_package(tmp_path/'gui-review.zip');assert {'current-cloud.png','current-profile.png','section-sample.csv'}<=set(members)
    assert len(w.tracker.data['review_exports'])==1 and p.last_path==str(tmp_path/'gui-review.zip')
    from PIL import Image
    assert Image.open(io.BytesIO(members['current-profile.png'])).size==(1024,360)
    assert application.job_status.get().startswith('Finished')
    assert not w.active and all(j['stage']!='Delivery' for j in w.tracker.data['jobs'])
    assert 'QA review package' in next(child for child in w.layout.deliver.winfo_children() if child.winfo_class()=='TCombobox').cget('values')


def test_unapplied_note_busy_and_stale_section_refuse_before_starting_worker(application,tmp_path):
    w,n,v,r,paths=setup(application,tmp_path);p=w.package_export;n.issue_here();n.note.insert('1.0','Unapplied note')
    with pytest.raises(ValueError,match='Apply note'):p.start(tmp_path/'dirty.zip')
    n.apply_issue();v.busy=True
    with pytest.raises(ValueError,match='Wait'):p.start(tmp_path/'busy.zip')
    v.busy=False;p.include_section.set(True)
    with pytest.raises(ValueError,match='Extract a section'):p.start(tmp_path/'no-section.zip')
    assert application.runner.thread is None and not list(tmp_path.glob('*.zip'))


def test_records_can_export_when_no_view_or_when_current_sources_are_missing(application,tmp_path):
    p=application.workspace.package_export;p.start(tmp_path/'empty.zip');settle(application,p);assert p.result
    w,n,v,r,paths=setup(application,tmp_path);n.issue_here();paths[0].unlink()
    p.start(tmp_path/'missing.zip');settle(application,p);assert p.result
    members=read_package(tmp_path/'missing.zip');assert 'current-cloud.png' not in members
    assert 'Missing' in members['report.html'].decode() and 'Current display not exported' in members['report.html'].decode()


def test_gui_cancel_uses_stop_job_and_does_not_publish_or_change_history(application,tmp_path,monkeypatch):
    w,n,v,r,paths=setup(application,tmp_path);p=w.package_export;started=threading.Event()
    def blocked_export(*args,cancel,**kwargs):
        started.set()
        while not cancel():time.sleep(.01)
        raise InterruptedError('Stopped')
    monkeypatch.setattr('pyargus.review_package_gui.export_package',blocked_export)
    p.start(tmp_path/'cancel.zip');assert started.wait(2);application.runner.cancel();settle(application,p)
    assert not p.result and 'stopped' in p.status.get().lower() and not list(tmp_path.glob('*.zip'))
    assert not w.tracker.data['jobs'] and not w.tracker.data.get('review_exports')


def test_preview_captures_annotations_without_desktop_screenshot(root):
    import tkinter as tk
    from PIL import Image,ImageTk
    from pyargus.review_package_gui import canvas_png
    canvas=tk.Canvas(root,width=50,height=40);photo=ImageTk.PhotoImage(Image.new('RGB',(50,40),'black'),master=root)
    canvas.create_image(0,0,image=photo,anchor='nw');canvas.create_line(5,10,40,10,fill='#ffff00',width=2)
    image=Image.open(io.BytesIO(canvas_png(canvas,photo)))
    assert image.size==(50,40) and image.getpixel((15,10))==(255,255,0)


def test_report_links_and_assets_are_local_complete_and_parseable(tmp_path):
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.paths=[]
        def handle_starttag(self,tag,attrs):
            for key,value in attrs:
                if key in ('href','src'):self.paths.append(value)
    snap,*_=snapshot(tmp_path);export_package(tmp_path/'links.zip',snap)
    members=read_package(tmp_path/'links.zip');parser=Links();parser.feed(members['report.html'].decode('utf-8'));parser.close()
    assert parser.paths and all(p.startswith('#') or p in members for p in parser.paths)
    assert b'Content-Security-Policy' in members['report.html'] and b'<script' not in members['report.html']


def test_hidden_profile_preview_is_readable_and_keeps_plot_state(application,tmp_path):
    from PIL import Image
    from pyargus.review_package_gui import profile_png
    w,n,v,r,paths=setup(application,tmp_path)
    r.profile.set(np.array([[0.,100.],[30.,101.],[60.,100.5]]),np.tile([255,180,0],(3,1)),5.)
    r.profile.zoom=2.;r.profile.pan=np.array([4.,6.]);before=(r.profile.center.copy(),r.profile.span.copy(),r.profile.zoom,r.profile.pan.copy(),r.profile.photo)
    data=profile_png(r.profile);assert Image.open(io.BytesIO(data)).size==(1024,360)
    np.testing.assert_array_equal(r.profile.center,before[0]);np.testing.assert_array_equal(r.profile.span,before[1])
    assert r.profile.zoom==before[2] and r.profile.photo is before[4]
    np.testing.assert_array_equal(r.profile.pan,before[3])
