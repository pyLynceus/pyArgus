"""Control coverage is geometric evidence, with fitting and check roles isolated."""
from dataclasses import replace
from pathlib import Path
import csv
import json
import xml.etree.ElementTree as ET
import numpy as np
import pytest
from pyargus import project
from pyargus.core.units import M_PER_US_SURVEY_FOOT as USFT
from pyargus.qa import alignment_report as report, control_coverage as coverage
from tests.test_project import scene
from tests.test_gui import application, root


def ground(scale=1., second_shift=0.):
    x,y=np.meshgrid(np.arange(101.),np.arange(21.))
    x,y=x.ravel(),y.ravel()
    return dict(x=np.tile(x,2)*scale,y=np.concatenate([y,y+second_shift])*scale,
                z=np.tile(10+.02*x+.03*y,2)*scale,
                classification=np.full(2*len(x),2),point_source_id=np.repeat([1,2],len(x)))


def inventory():
    return dict(units='test units',strips=[dict(id=i,source_id=7,clouds=[f'tile-{i}.las'],trajectory_path=f'flight-{i}.trj') for i in (1,2)])


def survey(xy,scale=1.):
    xyz=np.array([[x,y,10+.02*x+.03*y] for x,y in xy])*scale
    return dict(ids=[f'PID{i}' for i in range(len(xyz))],xyz=xyz)


def test_reference_coverage_uses_full_inventory_and_cannot_become_fitting_control():
    p=ground(second_shift=50)
    refs=survey([(10,5),(90,5),(10,15),(90,15)])
    result=coverage.collect(p,inventory(),report.settings(),USFT,references=refs)
    a,b=result['flights']
    assert result['basis']=='reference' and result['summary']['fitting_control_records']==0
    assert a['usable_sites']==4 and not a['flags']
    assert a['along_span_fraction']==pytest.approx(.8)
    assert a['cross_span_fraction']==pytest.approx(.5)
    assert b['strip']==2 and b['source_id']==a['source_id'] and b['usable_sites']==0
    assert b['counts']['reference']['rejected']==4 and b['maximum_gap']==pytest.approx(100)
    assert b['flags'] and a['trajectory_path']!=b['trajectory_path']


def test_independent_checks_cannot_satisfy_control_threshold_and_fit_proximity_is_excluded():
    p=ground();config=report.settings(dict(role='independent'))
    checks=report.assess(p,survey([(10,5),(90,5),(10,15),(90,15)]),config,USFT,
                         fitting_control=np.array([[10.,5.,10.35]]))
    result=coverage.collect(p,inventory(),config,USFT,checks=checks)
    assert result['basis'] is None
    assert result['flights'][0]['counts']['independent']['sites']==3
    assert result['flights'][0]['counts']['excluded']['sites']==1
    assert result['flights'][0]['usable_sites']==0


def test_actual_fit_array_remains_distinct_from_reference_and_check_support():
    p=ground();config=report.settings()
    result=coverage.collect(p,inventory(),config,USFT,
        fitting_control=survey([(10,5)])['xyz'],references=survey([(10,5),(90,5),(10,15),(90,15)]))
    f=result['flights'][0]
    assert result['basis']=='fitting_control' and f['usable_sites']==1
    assert f['counts']['reference']['sites']==4 and f['counts']['fitting_control']['sites']==1
    assert any('planning threshold' in v for v in f['flags'])


def test_duplicate_ids_at_same_xy_do_not_manufacture_control_geometry():
    refs=survey([(10,5),(10,5),(10,5)])
    a=coverage.collect(ground(),inventory(),report.settings(),USFT,references=refs)
    assert len(a['points'])==3 and a['flights'][0]['counts']['reference']['supported']==3
    assert a['flights'][0]['usable_sites']==1
    checks=report.assess(ground(),refs,report.settings(),USFT)
    b=coverage.collect(ground(),inventory(),report.settings(),USFT,references=refs,checks=checks)
    assert len(b['points'])==3 and all('report_checkpoints' in m['source'] for m in b['points'])


@pytest.mark.parametrize('factor',[1.,USFT,.3048])
def test_units_and_projected_endpoint_gaps(factor):
    scale=USFT/factor
    config=report.settings(dict(coverage_max_gap_ft=30.))
    a=coverage.collect(ground(scale),inventory(),config,factor,
        references=survey([(40,5),(50,15),(60,5)],scale))['flights'][0]
    assert a['maximum_gap']==pytest.approx(40*scale)
    assert len(a['long_gaps'])==2
    assert [g['length'] for g in a['long_gaps']]==pytest.approx([40*scale,40*scale])
    assert a['along_span_fraction']==pytest.approx(.2)


def test_collinear_control_and_one_sided_cloud_support_are_flagged():
    refs=survey([(10,10),(30,10),(60,10),(90,10),(-2,10)])
    a=coverage.collect(ground(),inventory(),report.settings(),USFT,references=refs)
    assert a['flights'][0]['usable_sites']==4
    assert any('collinear' in v for v in a['flights'][0]['flags'])
    assert any('quarter' in v for v in a['flights'][0]['flags'])
    assert not a['points'][-1]['flights'][0]['supported']
    assert 'outside' in a['points'][-1]['flights'][0]['reason'] or 'few' in a['points'][-1]['flights'][0]['reason']


def test_empty_and_degenerate_ground_are_unavailable_and_json_is_finite(tmp_path):
    p=ground();p['classification'][:]=1
    audit=coverage.collect(p,inventory(),report.settings(),USFT,references=survey([(10,5)]))
    assert all(f['extent']==[] and f['maximum_gap'] is None for f in audit['flights'])
    coverage.write(tmp_path,audit)
    assert ET.parse(tmp_path/'control_coverage.svg').getroot().tag.endswith('svg')
    assert 'NaN' not in (tmp_path/'control_coverage.json').read_text()
    with (tmp_path/'control_coverage_points.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==2 and all(r['supported']=='False' for r in rows)


def test_cancel_and_invalid_settings_are_not_silently_accepted():
    with pytest.raises(project.Cancelled):
        coverage.collect(ground(),inventory(),report.settings(),USFT,cancel=lambda:True)
    for value in (dict(coverage_min_sites=True),dict(coverage_min_sites=0),dict(coverage_max_gap_ft=float('nan')),dict(control_order='auto')):
        with pytest.raises(ValueError):report.settings(value)


def test_native_alignment_retains_audit_sources_and_checks_without_affecting_solve(scene,tmp_path):
    checks=tmp_path/'independent.csv';checks.write_text('check,2000,1025,100.5\n')
    controls=tmp_path/'pids.csv';controls.write_text('PID1,2000,1025,9999\nPID2,2000,1065,9999\n')
    config=report.settings(dict(checkpoints=str(checks),control_points=str(controls),role='independent'))
    reference=project.align(scene,tmp_path/'baseline',solve_boresight=False)
    out=tmp_path/'audit';result=project.align(replace(scene,alignment_reporting=config),out,solve_boresight=False)
    assert result['offsets']==reference['offsets'] and not result['control_anchored']
    data=json.loads((out/'alignment_comparison.json').read_text())
    audit=data['control_coverage'];assert audit['basis']=='reference'
    assert audit['summary']['reference_records']==2 and audit['summary']['independent_records']==1
    assert audit['summary']['fitting_control_records']==0
    assert all(f['counts']['fitting_control']['supported']==0 for f in audit['flights'])
    assert (out/'report_controls.csv').read_bytes()==controls.read_bytes()
    for name in coverage.PRODUCTS:assert (out/name).is_file()
    html=(out/'report.html').read_text(encoding='utf-8')
    assert 'Control / PID coverage audit' in html and 'coverageMap' in html
    assert 'control_coverage_flights.csv' in html
    record=json.loads(next(tmp_path.glob('audit.job-*.json')).read_text())
    assert any(r.get('role')=='audit_control_reference' and r['sha256'] for r in record['inputs'])
    assert any(r['path'].endswith('control_coverage.json') for r in record['outputs'])


def test_changed_audit_csv_refuses_publication(scene,tmp_path):
    source=tmp_path/'pids.csv';source.write_text('PID1,2000,1025,100.5\n')
    spec=replace(scene,alignment_reporting=report.settings(dict(control_points=str(source))))
    def mutate(text):
        if text=='Writing alignment comparison report':source.write_text('PID1,2000,1025,100.6\n')
    with pytest.raises(ValueError,match='control/PID CSV changed'):
        project.align(spec,tmp_path/'refused',solve_boresight=False,log=mutate)
    assert not (tmp_path/'refused').exists()


def test_gui_audit_preferences_survive_workspace_save(application,tmp_path):
    w=application.workspace;p=w.project_panel
    source=tmp_path/'pids.csv';source.write_text('PID1,2000,1025,100.5\n')
    config=report.settings(dict(control_points=str(source),control_order='penz',coverage_min_sites=4,coverage_max_gap_ft=750))
    p.reporting.restore(config)
    assert p.reporting.snapshot()==config and p.snapshot().alignment_reporting==config
    saved=tmp_path/'audit.argus.json';w.path=saved;w.persist();p.reporting.restore();w.restore(saved,load_view=False)
    assert p.reporting.snapshot()==config


def test_conflicting_reference_and_independent_roles_receive_no_dual_credit(tmp_path):
    config=report.settings(dict(role='independent'))
    refs=survey([(10,5),(90,5),(10,15),(90,15)])
    observations=report.assess(ground(),refs,config,USFT)
    audit=coverage.collect(ground(),inventory(),config,USFT,references=refs,checks=observations)
    assert audit['summary']['conflicting_role_records']==8
    assert all(f['usable_sites']==0 and f['flags'] for f in audit['flights'])
    assert all(f['counts']['reference']['eligible_sites']==0 for f in audit['flights'])
    fit=dict(offsets={'1':[0,0,0]},boresight=[0,0,0],patch_rms_before=.1,patch_rms_after=.1,observations=20,control_anchored=False)
    from pyproj import CRS
    result=report.generate(tmp_path,fit,{}, {},observations,observations,config,CRS(6447),inputs=[],coverage_audit=audit)
    assert result['checkpoint_summary']['independent_paired_support']==0
    assert all(r['role']=='survey_role_conflict' for r in result['checkpoints'])
    assert all(r['role']=='independent' for r in observations)  # caller records are unchanged


def test_audit_csv_edit_marks_workspace_alignment_outdated(application,tmp_path):
    w=application.workspace
    source=tmp_path/'pids.csv';source.write_text('PID1,2000,1025,100.5\n')
    config=report.settings(dict(control_points=str(source)))
    w.project_panel.reporting.restore(config)
    spec=project.Project(alignment_reporting=config)
    w.begin_project('align',spec,str(tmp_path/'result'))
    job=w.active
    job['status']='Accepted'
    assert any(row[0]==str(source.resolve()) for row in job['inputs'])
    source.write_text('PID1,2000,1025,100.6\nPID2,2000,1060,101.2\n')
    assert w.tracker.job_status(job)=='Outdated'
    w.active=None
