import json
from threading import Event
from pathlib import Path
import numpy as np
import pytest

from pyargus.review import load_review, review_rows, cloud_layers
from pyargus.sections import extract_section, section_coordinates, export_section
from pyargus.job_manifest import identity
from tests.test_gui import root


def cloud(path, dz=0., epsg=6447):
    import laspy
    from pyproj import CRS
    header=laspy.LasHeader(point_format=6,version="1.4")
    header.scales=(.001,.001,.001); header.add_crs(CRS(epsg))
    data=laspy.LasData(header)
    x,y=np.meshgrid(np.arange(101.),np.arange(-5.,6.))
    data.x=x.ravel()+1000; data.y=y.ravel()+2000
    data.z=100+.01*x.ravel()+dz
    data.classification=np.full(x.size,2,dtype=np.uint8)
    data.point_source_id=np.where(x.ravel()<50,1,2)
    data.write(path)


@pytest.fixture
def pair(tmp_path):
    a,b=tmp_path/'original.las',tmp_path/'corrected.las'
    cloud(a,.25); cloud(b)
    return a,b


def record(pair, tmp_path):
    data=dict(schema_version=1,operation="project-align",status="completed",elapsed_seconds=1,
        inputs=[identity(pair[0])],outputs=[identity(pair[1])],results=dict(
        corrections_written=True,inventory=dict(unmatched=3,ambiguous=0),
        before_qa=dict(strip_dz=[dict(a=1,b=2,median=.5,rmse=.5)]),
        after_qa=dict(strip_dz=[dict(a=1,b=2,median=.05,rmse=.08)],
                      control=dict(residuals={"mark":.4},skipped={"absent":"no ground"}))))
    path=tmp_path/'review.job-test.json'; path.write_text(json.dumps(data))
    return path


def test_review_compares_flags_and_preserves_source_identity(pair,tmp_path):
    review=load_review(record(pair,tmp_path)); rows=review_rows(review)
    median=next(r for r in rows if r['label']=='Strip 1 / 2: median')
    assert median['before']==.5 and median['after']==.05 and not median['flag']
    assert next(r for r in rows if r['label']=='Trajectory unmatched')['flag']
    assert next(r for r in rows if r['label']=='After control mark')['flag']
    assert [v['role'] for v in cloud_layers(review)]==['Original','Corrected']
    pair[1].write_bytes(b'changed')
    assert cloud_layers(review)[1]['state']=='changed since job'
    for limit in [0,-1,float('nan')]:
        with pytest.raises(ValueError): review_rows(review,limit)


def test_review_refuses_nonjob_json(tmp_path):
    path=tmp_path/'plain.json'; path.write_text('{}')
    with pytest.raises(ValueError,match='schema'): load_review(path)


def test_section_geometry_direction_and_boundaries():
    station,cross,keep=section_coordinates([10,10,11,10],[0,5,5,11],[10,0],[10,10],2)
    np.testing.assert_allclose(station,[0,5,5,11])
    np.testing.assert_allclose(cross,[0,0,-1,0])
    assert keep.tolist()==[True,True,True,False]
    with pytest.raises(ValueError): section_coordinates([],[],[0,0],[0,0],1)
    with pytest.raises(ValueError): section_coordinates([],[],[0,0],[1,0],-1)


def test_full_scan_extract_counts_offsets_export_and_no_source_changes(pair,tmp_path):
    before=[p.read_bytes() for p in pair]
    section=extract_section(pair,[1010,2000],[1020,2000],2,limit=1000,chunk_size=17)
    assert section.matched==66 and section.matched_by_file==[33,33]
    assert len(section.points)==66
    a=section.points[section.files==0]; b=section.points[section.files==1]
    np.testing.assert_allclose(a[:,2]-b[:,2],.25)
    assert section.points[:,3].min()==0 and section.points[:,3].max()==10
    out=tmp_path/'section.csv'; meta=export_section(section,out)
    saved=json.loads(meta.read_text())
    assert saved['matched']==66 and saved['displayed']==66
    assert len(out.read_text().splitlines())==67
    with pytest.raises(ValueError,match='new export'): export_section(section,out)
    assert [p.read_bytes() for p in pair]==before


def test_section_bounded_deterministic_and_chunk_invariant(pair):
    a=extract_section(pair,[1000,2000],[1100,2000],20,limit=11,chunk_size=23)
    b=extract_section(pair,[1000,2000],[1100,2000],20,limit=11,chunk_size=199)
    assert len(a.points)==22 and a.matched==2222
    assert set(a.files)=={0,1}
    assert set(zip(a.files,a.point_indices))==set(zip(b.files,b.point_indices))


def test_section_empty_cancel_and_crs_refusal(pair):
    s=extract_section(pair,[1000,9000],[1100,9000],1)
    assert s.matched==0 and s.points.shape==(0,5)
    cancel=Event(); cancel.set()
    with pytest.raises(InterruptedError): extract_section(pair,[1000,2000],[1100,2000],2,cancel=cancel)
    cloud(pair[1],epsg=26916)
    with pytest.raises(ValueError,match='differ'): extract_section(pair,[1000,2000],[1100,2000],2)


def wait(root, workspace):
    def check():
        if workspace.busy: root.after(20,check)
        else: root.quit()
    timeout=root.after(15000,root.quit); root.after(20,check); root.mainloop(); root.after_cancel(timeout)
    assert not workspace.busy, workspace.status.get()


def test_workspace_load_pick_extract_filter_and_transform(root,pair,tmp_path):
    from pyargus.review_gui import ReviewWorkspace
    w=ReviewWorkspace(root)
    try:
        w.open_record(record(pair,tmp_path)); root.update()
        assert len(w.tree.get_children())>=6
        w.confirm.set(True); w.load_clouds(); wait(root,w)
        assert w.scene is not None,w.status.get()
        with pytest.raises(ValueError,match='Choose a Section source'):
            w.section_paths()
        w.pick(np.array([1010.,2000.])); w.pick(np.array([1020.,2000.]))
        w.section_source.set('Compare all loaded clouds')
        w.width.set('2'); w.extract(); wait(root,w)
        assert w.section.matched==66,w.status.get()
        assert w.profile.photo.width()>0
        for mode in ('Dataset','Flight line','Classification'):
            w.mode.set(mode); w.redraw()
        point=np.array([1015.,2000.]); np.testing.assert_allclose(w.plan.world(*w.plan.screen(point)),point)
        w.line.set('999'); w.redraw(); assert len(w.profile.xy)==0
        w.line.set('All'); w.redraw(); assert len(w.profile.xy)==66
        w.filelist.selection_clear(0,'end'); w.filelist.selection_set(0); w.redraw()
        assert len(w.profile.xy)==33
        w.filelist.selection_set(0,'end')
        w.section_source.set(str(pair[1].resolve()))
        w.extract(); wait(root,w)
        assert w.section.matched==33
        assert len(w.section.inputs)==1
        assert w.section.inputs[0]['path']==str(pair[1].resolve())
        assert len(w.profile.xy)==33
        w.width.set('4'); w.set_corridor()
        assert w.section is None and len(w.profile.xy)==0
    finally: w.close()


def test_project_qa_review_loads_matching_inventory(tmp_path):
    folder=tmp_path/'qa';folder.mkdir()
    (folder/'inventory.json').write_text(json.dumps(dict(unmatched=4,ambiguous=1)))
    path=tmp_path/'qa.job.json'
    path.write_text(json.dumps(dict(schema_version=1,operation='project-qa',status='completed',
                                   results=dict(report=str(folder/'report.html')))))
    data=load_review(path)
    assert next(r for r in review_rows(data) if r['label']=='Trajectory ambiguous')['after']==1


def test_section_detects_input_mutation(pair):
    def progress(_):
        # Change metadata after the extractor has captured its input identity.
        import os
        stat=pair[0].stat();os.utime(pair[0],ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
    with pytest.raises(ValueError,match='changed during'):
        extract_section(pair,[1010,2000],[1020,2000],2,progress=progress)
