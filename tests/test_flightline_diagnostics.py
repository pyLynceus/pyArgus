from pathlib import Path
import csv
import hashlib
import json
import os
import time
import numpy as np
import pytest
from pyargus.project import Project, Cancelled
from pyargus.qa import flightline_diagnostics as diag


def make_cloud(path, offset=.2, *, asymmetric=False, omit=None, rough=False, grade=.04,
               classes=True, isolated=False, epsg=6447, origin=-60.):
    import laspy
    from pyproj import CRS
    points=[]; labels=[]; sources=[]
    for sid in (1,2):
        for ix in range(5):
            for iy in range(4):
                cx=origin+6*ix+3;cy=-30+6*iy+3
                xx=np.array([-2,-1,1,2.]) if not (asymmetric and sid==2) else np.array([-2.5,-2,1,1.5])
                xx,yy=np.meshgrid(xx,[-2,-1,1,2.]);x=cx+xx.ravel();y=cy+yy.ravel()
                z=100+grade*(x-origin)+.02*(y+30)+(offset if sid==2 else 0)
                if rough and sid==2:z=z+np.tile([-.5,.5],8)
                if isolated and sid==2:x=x+600
                for a,b,c in zip(x,y,z):
                    points.append((a,b,c));sources.append(sid)
                    labels.append(2 if classes and not (sid==2 and omit==(ix,iy)) else 1)
    xyz=np.asarray(points)
    header=laspy.LasHeader(point_format=6,version='1.4');header.scales=(.000001,)*3
    header.offsets=(origin,-30.,0.)
    header.add_crs(CRS(epsg));data=laspy.LasData(header)
    data.x,data.y,data.z=xyz.T;data.point_source_id=np.asarray(sources,dtype=np.uint16)
    data.classification=np.asarray(labels,dtype=np.uint8);data.write(path)
    return Project([str(path)],same_vertical=True)


def run(tmp_path,**kw):
    project=make_cloud(tmp_path/'source.las',**kw)
    result=diag.run(project,tmp_path/'report',log=lambda _:None)
    return result,result['states'][0]['pairs'][0]


@pytest.mark.parametrize('key,value',[('cell_ft',0),('min_points',True),('min_cells',2),
    ('max_scatter_ft',float('nan')),('max_slope',-1),('tolerance_ft',float('inf'))])
def test_invalid_screening_refuses(key,value):
    with pytest.raises(ValueError):diag.settings({key:value})


def test_plane_height_recovers_injected_separation_and_retains_every_cell(tmp_path):
    result,pair=run(tmp_path,offset=.2)
    assert pair['supported'] and pair['statistics']['cells']==20
    assert pair['statistics']['median']==pytest.approx(.2,abs=2e-6)
    assert pair['statistics']['rmse']==pytest.approx(.2,abs=2e-6)
    assert pair['statistics']['exceeding']==20
    assert pair['finding']=='Systematic separation to review'
    assert pair['trend']['available']
    assert abs(pair['trend']['east_gradient_per_1000ft'])<1e-4
    assert result['states'][0]['connected_components']==[[1,2]]
    rows=list(csv.DictReader((tmp_path/'report/baseline/surface_cells.csv').open()))
    assert len(rows)==40 and all(int(r['ground_returns'])==16 for r in rows)
    assert any(float(r['cell_east'])<0 for r in rows)
    assert result['corrections_written'] is False


def test_plane_not_raw_median_handles_unequal_sampling_on_a_slope(tmp_path):
    _,pair=run(tmp_path,offset=0,asymmetric=True)
    assert pair['statistics']['median']==pytest.approx(0,abs=2e-6)
    rows=list(csv.DictReader((tmp_path/'report/baseline/surface_cells.csv').open()))
    medians={int(r['flight']):float(r['raw_median']) for r in rows[:1]+[r for r in rows if r['flight']=='2'][:1]}
    assert abs(medians[2]-medians[1])>.005


@pytest.mark.parametrize('kw,reason',[({'rough':True},'Local plane scatter exceeds limit'),
    ({'grade':.5},'Local surface slope exceeds limit')])
def test_surface_screening_rejects_bad_cells_without_zero_filling(tmp_path,kw,reason):
    result,pair=run(tmp_path,**kw)
    assert pair['statistics']['cells']==0 and pair['statistics']['rmse'] is None
    assert not pair['supported']
    rejected=result['states'][0]['flights'][1 if kw.get('rough') else 0]['rejected_cells']
    assert reason in rejected


def test_observed_overlap_does_not_substitute_for_ground_support(tmp_path):
    result,pair=run(tmp_path,classes=False)
    assert pair['occupied_shared_cells']==20
    assert pair['ground_shared_cells']==0 and pair['statistics']['cells']==0
    assert pair['statistics']['median'] is None
    assert result['states'][0]['connected_components']==[[1],[2]]


def test_disconnected_flights_remain_unassessed(tmp_path):
    result,pair=run(tmp_path,isolated=True)
    assert pair['occupied_shared_cells']==0 and pair['statistics']['cells']==0
    assert len(result['states'][0]['connected_components'])==2
    assert pair['trend']['available'] is False


def test_candidate_compares_exactly_common_qualified_cells_and_preserves_inputs(tmp_path):
    a=make_cloud(tmp_path/'before.las',offset=.2)
    b=make_cloud(tmp_path/'after.las',offset=.03,omit=(0,0))
    before={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in a.clouds+b.clouds}
    result=diag.run(a,tmp_path/'report',candidate=b,log=lambda _:None)
    pair=result['comparison']['pairs'][0]
    assert pair['before']['cells']==pair['after']['cells']==19
    assert pair['before']['rmse']==pytest.approx(.2,abs=2e-6)
    assert pair['after']['rmse']==pytest.approx(.03,abs=2e-6)
    assert result['states'][0]['pairs'][0]['statistics']['cells']==20
    assert len(list(csv.DictReader((tmp_path/'report/common_cells.csv').open())))==19
    assert {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in before}==before
    assert not list((tmp_path/'report').rglob('*.las'))


def test_large_origins_do_not_corrupt_local_plane_heights(tmp_path):
    _,pair=run(tmp_path,offset=-.125,origin=2357160.)
    assert pair['statistics']['median']==pytest.approx(-.125,abs=2e-6)
    assert pair['statistics']['rmse']==pytest.approx(.125,abs=2e-6)


def test_ground_statistics_merge_across_chunks_exactly(tmp_path):
    from pyargus.project import load
    p=make_cloud(tmp_path/'source.las',offset=.2)
    data=load(p,keep_points=True,log=lambda _:None)
    native=dict(diag.settings(),max_scatter=.08,tolerance=.1)
    store=diag.Store(tmp_path/'cells.sqlite',6.,native,lambda:False)
    try:
        # Convert back to raw LAS line identities for the ingest contract.
        points=dict(data.points,point_source_id=data.points['original_point_source_id'])
        for i in range(0,len(points['x']),13):
            part={k:v[i:i+13] for k,v in points.items()}
            store.ingest(part,np.full(len(part['x']),-1,dtype=np.int32))
        store.reduce()
        rows=store.db.execute('SELECT n,median,height FROM surfaces ORDER BY s,x,y').fetchall()
        assert len(rows)==40 and all(r[0]==16 and r[2] is not None for r in rows)
        first=rows[0]
        mask=(np.floor(points['x']/6)==-10)&(np.floor(points['y']/6)==-5)&(points['point_source_id']==1)
        assert first[1]==np.median(points['z'][mask])
    finally:store.db.close()


def test_cancellation_closes_database_before_removing_staging(tmp_path,monkeypatch):
    project=make_cloud(tmp_path/'source.las')
    cancelled=[False];original=diag.Store.ingest
    def ingest(self,*args):
        original(self,*args);cancelled[0]=True
    monkeypatch.setattr(diag.Store,'ingest',ingest)
    with pytest.raises(Cancelled):diag.run(project,tmp_path/'report',cancel=lambda:cancelled[0],log=lambda _:None)
    assert not (tmp_path/'report').exists()
    assert not list(tmp_path.glob('.pyargus-flightlines-*'))
    records=list(tmp_path.glob('report.job-*.json'))
    assert json.loads(records[0].read_text())['status']=='cancelled'


def test_input_mutation_refuses_publication(tmp_path,monkeypatch):
    from pyargus.qa import flightline_report
    project=make_cloud(tmp_path/'source.las');original=flightline_report.write
    def write(*args):
        original(*args);p=Path(project.clouds[0]);st=p.stat();os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns+1000000000))
    monkeypatch.setattr(flightline_report,'write',write)
    with pytest.raises(ValueError,match='changed'):diag.run(project,tmp_path/'report',log=lambda _:None)
    assert not (tmp_path/'report').exists() and not list(tmp_path.glob('.pyargus-flightlines-*'))


def test_existing_destination_is_never_replaced(tmp_path):
    project=make_cloud(tmp_path/'source.las');out=tmp_path/'report';out.mkdir();(out/'keep').write_text('existing')
    with pytest.raises(ValueError,match='already exists'):diag.run(project,out,log=lambda _:None)
    assert (out/'keep').read_text()=='existing'


def test_reference_locations_have_honest_cell_support_and_role_conflicts(tmp_path):
    project=make_cloud(tmp_path/'source.las')
    refs=tmp_path/'refs.csv';checks=tmp_path/'checks.csv'
    refs.write_text('P1,-27,-57,100\nOutside,1000,1000,100\n')
    checks.write_text('P1,-27,-57,100\n')
    project.alignment_reporting=dict(control_points=str(refs),checkpoints=str(checks),role='independent')
    result=diag.run(project,tmp_path/'report',log=lambda _:None)
    marks=result['states'][0]['reference_locations']
    assert marks[0]['qualified_cell_flights']==[1,2]
    assert marks[1]['qualified_cell_flights']==[]
    assert marks[2]['role']=='role_conflict'
    assert all('survey residual not measured' in r['assessment'] for r in marks)


def test_reused_line_ids_do_not_silently_become_separate_flights(tmp_path):
    a=make_cloud(tmp_path/'a.las');b=make_cloud(tmp_path/'b.las')
    with pytest.raises(ValueError,match='repeat across clouds'):
        diag.run(Project(a.clouds+b.clouds,same_vertical=True),tmp_path/'report',log=lambda _:None)
    assert not (tmp_path/'report').exists()


def test_cli_and_gui_route_to_diagnosis_not_alignment(tmp_path,monkeypatch):
    from pyargus.cli import build_parser
    args=build_parser().parse_args(['flightline-diagnostics','baseline.json','--out','new-report','--min-cells','8'])
    assert args.min_cells==8 and args.func.__module__=='pyargus.flightline_cli'


def test_native_dialog_runs_read_only_and_does_not_complete_alignment(tmp_path,monkeypatch):
    from tests.test_gui import make_root
    from pyargus.gui import Application,apply_theme
    project=make_cloud(tmp_path/'source.las')
    root=make_root();apply_theme(root);app=Application(root)
    try:
        panel=app.workspace.project_panel;panel.clouds=project.clouds;panel.same_vertical.set(True)
        view=app.workspace.layout.flightline_diagnostics
        view.open();view.out.set(str(tmp_path/'gui-report'));view.start()
        end=time.monotonic()+12
        while (app.runner.running or app._stage_open) and time.monotonic()<end:
            root.update();time.sleep(.01)
        assert not app.runner.running and app.runner.error is None
        assert (tmp_path/'gui-report/report.html').exists()
        jobs=app.workspace.tracker.data['jobs']
        assert jobs[-1]['mode']=='diagnostics' and jobs[-1]['stage']=='Initial QA'
        assert not any(job['stage']=='Alignment' for job in jobs)
        assert app.workspace.project_panel.clouds==project.clouds
    finally:root.destroy()


def test_unit_conversion_uses_us_survey_foot_thresholds_in_a_metric_cloud(tmp_path):
    project=make_cloud(tmp_path/'metres.las',epsg=32617,offset=.02)
    result=diag.run(project,tmp_path/'report',config={'cell_ft':6/diag.FT_US},log=lambda _:None)
    assert result['native_settings']['cell']==pytest.approx(6.)
    assert result['native_settings']['tolerance']==pytest.approx(.1*diag.FT_US)
    pair=result['states'][0]['pairs'][0]
    assert pair['statistics']['rmse']==pytest.approx(.02,abs=2e-6)
    assert pair['statistics']['exceeding']==0


def test_candidate_crs_conflict_refuses_before_outputs(tmp_path):
    a=make_cloud(tmp_path/'feet.las');b=make_cloud(tmp_path/'metres.las',epsg=32617)
    with pytest.raises(ValueError,match='CRS/units differ'):diag.run(a,tmp_path/'report',candidate=b,log=lambda _:None)
    assert not (tmp_path/'report').exists()


def test_common_population_without_ground_support_is_null_not_zero(tmp_path):
    a=make_cloud(tmp_path/'before.las');b=make_cloud(tmp_path/'after.las',classes=False)
    result=diag.run(a,tmp_path/'report',candidate=b,log=lambda _:None)
    pair=result['comparison']['pairs'][0]
    assert pair['before']['cells']==pair['after']['cells']==0
    assert pair['before']['rmse'] is None and pair['after']['rmse'] is None
    assert pair['supported'] is False


def test_publication_race_preserves_existing_and_recoverable_report(tmp_path,monkeypatch):
    from pyargus.qa import flightline_report
    from pyargus.publication import DestinationExistsError
    project=make_cloud(tmp_path/'source.las');out=tmp_path/'report';original=flightline_report.write
    def write(*args):
        original(*args);out.mkdir();(out/'keep').write_text('other writer')
    monkeypatch.setattr(flightline_report,'write',write)
    with pytest.raises(DestinationExistsError) as error:
        diag.run(project,out,log=lambda _:None)
    assert (out/'keep').read_text()=='other writer'
    assert (error.value.recovery_path/'report.html').exists()
    assert (error.value.recovery_path/'diagnostics.json').exists()


def test_one_sided_ground_does_not_extrapolate_a_center_plane(tmp_path):
    import laspy
    p=make_cloud(tmp_path/'source.las')
    data=laspy.read(p.clouds[0]);mask=(data.point_source_id==2)
    x=np.asarray(data.x);centers=np.floor(x/6)*6+3
    x[mask]=centers[mask]+np.abs(x[mask]-centers[mask]);data.x=x;data.write(p.clouds[0])
    result=diag.run(p,tmp_path/'report',log=lambda _:None)
    pair=result['states'][0]['pairs'][0]
    assert pair['statistics']['cells']==0
    assert 'Cell center lacks ground returns in all four quadrants' in result['states'][0]['flights'][1]['rejected_cells']


def test_cli_executes_a_read_only_diagnosis(tmp_path):
    from pyargus.cli import main
    project=make_cloud(tmp_path/'source.las');manifest=tmp_path/'project.json';project.save(manifest)
    assert main(['flightline-diagnostics',str(manifest),'--out',str(tmp_path/'cli-report')])==0
    result=json.loads((tmp_path/'cli-report/diagnostics.json').read_text())
    assert result['corrections_written'] is False


def test_spatial_trend_has_correct_sign_and_per_1000ft_units(tmp_path):
    import laspy
    project=make_cloud(tmp_path/'source.las',offset=.1)
    data=laspy.read(project.clouds[0]);z=np.asarray(data.z).copy();mask=np.asarray(data.point_source_id)==2
    z[mask]+=.001*(np.asarray(data.x)[mask]+60);data.z=z;data.write(project.clouds[0])
    result=diag.run(project,tmp_path/'report',log=lambda _:None)
    trend=result['states'][0]['pairs'][0]['trend']
    assert trend['available']
    assert trend['east_gradient_per_1000ft']==pytest.approx(1.,abs=1e-5)
    assert trend['north_gradient_per_1000ft']==pytest.approx(0.,abs=1e-5)
    assert result['states'][0]['occupied_union_cells']==20
    assert result['states'][0]['multiply_occupied_cells']==20
    assert all(p[2]==2 for p in result['states'][0]['coverage_map_cells'])


def test_closing_diagnostics_dialog_cancels_its_poll_callback(tmp_path):
    from tests.test_gui import make_root
    from pyargus.gui import Application
    root=make_root();app=Application(root)
    try:
        view=app.workspace.layout.flightline_diagnostics
        win=view.open();callback=view.poll_id
        assert callback in root.tk.call('after','info')
        win.destroy();root.update()
        assert callback not in root.tk.call('after','info')
        assert view.poll_id is None
    finally:root.destroy()
