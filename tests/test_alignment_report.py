"""Independent geometry, evidence roles, report persistence and GUI coverage."""
from dataclasses import replace
import csv
import json
from pathlib import Path
import numpy as np
import pytest
from pyproj import CRS
from pyargus import project
from pyargus.qa import alignment_report as report
from tests.test_project import scene
from tests.test_gui import application, root


def points(scale=1):
    x,y=np.meshgrid(np.arange(-2.,2.01,.4),np.arange(-2.,2.01,.4))
    x,y=np.tile(x.ravel(),2)*scale,np.tile(y.ravel(),2)*scale
    ids=np.repeat([1,2],len(x)//2)
    return dict(x=x,y=y,z=10*scale+.02*x+.03*y+(ids==2)*.2*scale,
                classification=np.full(len(x),2),point_source_id=ids)


def checks(tmp_path, text='a,0,0,10\nb,20,20,10\n'):
    path=tmp_path/'checks.csv';path.write_text(text)
    config=report.settings(dict(checkpoints=str(path),role='independent',surface='pavement',material='Bare asphalt'))
    return config,report.read_checks(config)


def test_local_plane_recovers_merged_and_individual_offsets_without_extrapolation(tmp_path):
    config,c=checks(tmp_path);p=points();rows=report.assess(p,c,config,report.FT_US)
    assert len(rows)==2 and rows[0]['merged']['n']>8
    assert rows[0]['merged']['error']==pytest.approx(.1,abs=1e-10)
    assert rows[0]['flights']['1']['error']==pytest.approx(0,abs=1e-10)
    assert rows[0]['flights']['2']['error']==pytest.approx(.2,abs=1e-10)
    assert rows[1]['merged']['error'] is None and not rows[1]['merged']['supported']
    assert rows[0]['merged']['scatter']==pytest.approx(.1)
    assert rows[0]['merged']['slope']==pytest.approx(np.hypot(.02,.03))


def test_support_gates_reject_one_sided_collinear_and_sparse_points():
    xy=np.column_stack([np.arange(12)*.05+1,np.linspace(-.5,.5,12)**2])
    one_sided=report._plane(xy,np.ones(12),8,2)
    assert not one_sided['supported']
    assert not report._plane(np.zeros((12,2)),np.zeros(12),8,2)['supported']
    assert not report._plane(np.zeros((2,2)),np.zeros(2),8,2)['supported']
    # Enough well-conditioned points, but surveyed XY is outside their hull.
    xy=np.array([[x,y] for x in (0.1,0.5,1.) for y in (-1,0,1)])
    r=report._plane(xy,np.ones(9),8,2)
    assert not r['supported'] and 'outside' in r['reason']


def test_us_foot_thresholds_and_neighborhoods_are_converted_for_metre_cloud(tmp_path):
    config,c=checks(tmp_path,'a,0,0,3.048006096012192\n');rows=report.assess(points(report.FT_US),c,config,1.)
    assert rows[0]['tolerance']==pytest.approx(.1*report.FT_US)
    assert rows[0]['merged']['error']==pytest.approx(.1*report.FT_US,abs=1e-10)
    assert rows[0]['merged']['n']==report.assess(points(),dict(c,xyz=np.array([[0,0,10]])),config,report.FT_US)[0]['merged']['n']


def test_fitting_control_neighborhood_is_not_counted_as_independent(tmp_path):
    config,c=checks(tmp_path);p=points();a=report.assess(p,c,config,report.FT_US,fitting_control=np.array([[0,0,10]]))
    assert a[0]['role']=='fitting_control_neighborhood'
    assert a[0]['merged']['supported']
    assert report.compare_checks(a,a)[0]['paired_support']


@pytest.mark.parametrize('changes',[dict(radius_ft=0),dict(radius_ft=float('nan')),dict(min_points=True),dict(surface='guessed'),dict(role='control'),dict(extra=1)])
def test_invalid_preferences_fail(changes):
    with pytest.raises(ValueError):report.settings(changes)


@pytest.mark.parametrize('text',['a,0,0,10\na,1,1,10\n','a,nan,0,10\n'])
def test_bad_checkpoint_data_refused(tmp_path,text):
    with pytest.raises(ValueError):checks(tmp_path,text)


def test_complete_alignment_report_uses_exported_coordinates_and_retains_all_checks(scene,tmp_path):
    config,_=checks(tmp_path,'inside,2000,1025,100.5\nedge,2000,1045,100.9\noutside,3000,3000,0\n')
    spec=replace(scene,alignment_reporting=config);out=tmp_path/'aligned'
    result=project.align(spec,out,solve_boresight=False)
    d=json.loads((out/'alignment_comparison.json').read_text())
    assert d['review_status']=='Needs review'
    assert d['checkpoint_summary']['supplied']==3 and d['checkpoint_summary']['independent_paired_support']==2
    assert d['checkpoint_summary']['before']['rmse']==pytest.approx(.125,abs=.001)
    assert d['checkpoint_summary']['after']['rmse']<.001
    rows=d['checkpoints'];assert rows[-1]['id']=='outside' and rows[-1]['after']['error'] is None
    # Independently recover Z at surveyed XY from the actual exported LAS records.
    loaded=project.load(replace(spec,clouds=[str(out/r['output']) for r in result['outputs']]),keep_points=True)
    _,c=checks(tmp_path,'inside,2000,1025,100.5\nedge,2000,1045,100.9\noutside,3000,3000,0\n')
    independently_read=report.assess(loaded.points,c,config,loaded.crs.axis_info[0].unit_conversion_factor)
    assert [r['after']['error'] for r in rows]==[r['merged']['error'] for r in independently_read]
    assert (out/'report_checkpoints.csv').read_bytes()==Path(config['checkpoints']).read_bytes()
    assert project.Project.load(out/'project.json').alignment_reporting==config
    for name in report.PRODUCTS:assert (out/name).is_file()
    with (out/'checkpoint_comparison.csv').open(newline='') as f:csvrows=list(csv.DictReader(f))
    assert len(csvrows)==3 and csvrows[-1]['after_error']==''
    record=json.loads(next(tmp_path.glob('aligned.job-*.json')).read_text())
    assert any(i.get('sha256') and i['path']==config['checkpoints'] for i in record['inputs'])
    assert all(Path(i['path']).is_file() for i in record['outputs'])


def test_reference_checks_are_not_claimed_independent_and_fit_neighborhood_excluded(tmp_path):
    config,c=checks(tmp_path,'fit,0,0,10\n');config['role']='reference'
    a=report.assess(points(),c,config,report.FT_US,fitting_control=np.array([[0,0,10]]))
    summary=dict(offsets={'1':[0,0,0]},boresight=[0,0,0],patch_rms_before=.2,patch_rms_after=0,observations=20,control_anchored=True)
    result=report.generate(tmp_path,summary,{}, {},a,a,config,CRS.from_epsg(6445),inputs=[])
    assert result['checkpoint_summary']['independent_after']['n']==0
    assert result['checkpoint_summary']['after']['n']==0
    assert result['checkpoints'][0]['after']['supported']
    assert 'No independent checkpoints' in (tmp_path/'report.html').read_text()


def test_changed_checks_abort_before_publishing_alignment(scene,tmp_path):
    config,_=checks(tmp_path);spec=replace(scene,alignment_reporting=config)
    def mutate(line):
        if line=='Writing alignment comparison report':Path(config['checkpoints']).write_text('changed')
    with pytest.raises(ValueError,match='checkpoint CSV changed'):project.align(spec,tmp_path/'refused',solve_boresight=False,log=mutate)
    assert not (tmp_path/'refused').exists()
    assert json.loads(next(tmp_path.glob('refused.job-*.json')).read_text())['status']=='failed'


def test_cancel_discards_unpublished_alignment_report(scene,tmp_path):
    stopping=[False]
    def log(line):
        if line=='Writing alignment comparison report':stopping[0]=True
    with pytest.raises(project.Cancelled):project.align(scene,tmp_path/'cancelled',solve_boresight=False,log=log,cancel=lambda:stopping[0])
    assert not (tmp_path/'cancelled').exists()
    assert json.loads(next(tmp_path.glob('cancelled.job-*.json')).read_text())['status']=='cancelled'


def test_gui_settings_persist_and_selected_report_opens(application,tmp_path,monkeypatch):
    w=application.workspace;p=w.project_panel;config,_=checks(tmp_path)
    p.reporting.restore(config);assert p.snapshot().alignment_reporting==config
    saved=tmp_path/'prefs.argus.json';w.path=saved;w.persist();p.reporting.restore();w.restore(saved,load_view=False)
    assert p.snapshot().alignment_reporting==config
    page=tmp_path/'report.html';page.write_text('<html>test</html>');w.add_layer(page,'output','test');w.layout.update()
    key=next(k for k,v in w.layout.output_paths.items() if Path(v)==page);w.layout.outputs.selection_set(key)
    opened=[];monkeypatch.setattr('webbrowser.open',opened.append);w.layout.open_output_report()
    assert opened==[page.as_uri()]
