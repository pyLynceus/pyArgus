"""LP360 file selection and full native workflow, including failure boundaries."""
from dataclasses import asdict,replace
from pathlib import Path
import hashlib,json
import laspy
import numpy as np
import pyproj
import pytest
from pyargus import project
from pyargus.lp360_jobs import Recipe,discover,suggest,inspect_recipe
from pyargus.lp360_workflow import run
from pyargus.workspace_state import Tracker
from tests.test_project import track_file


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture
def job(tmp_path):
    root=tmp_path/'Job';flight=root/'Cycle_260101_120000'/'Flight_260101_120000';(flight/'LAS').mkdir(parents=True);(flight/'Trajectories').mkdir()
    x,y=np.meshgrid(np.linspace(1000,1100,71),np.linspace(2000,2080,61));x=x.ravel();y=y.ravel();ground=100+.02*(x-1000)+.03*(y-2000)
    clouds=[];tracks=[]
    for i,offset in enumerate((0.,.35),1):
        stem=f'20260101_120{i-1}00';path=flight/'LAS'/(stem+'.las')
        h=laspy.LasHeader(point_format=7,version='1.4');h.scales=[.001,.001,.001];h.add_crs(pyproj.CRS.from_epsg(2277));h.global_encoding.gps_time_type=1
        h.add_extra_dim(laspy.ExtraBytesParams('Amplitude','u2',scales=[.01],offsets=[0.]))
        las=laspy.LasData(h);las.x=x;las.y=y;las.z=ground+offset;las.gps_time=np.linspace(400000000+20*(i-1),400000010+20*(i-1),len(x));las.point_source_id=np.full(len(x),i);las.return_number=np.ones(len(x),dtype=np.uint8);las.number_of_returns=np.ones(len(x),dtype=np.uint8);las.classification=np.zeros(len(x),dtype=np.uint8);las.red=np.arange(len(x),dtype=np.uint16);las.Amplitude=np.ones(len(x));las.write(path)
        t=track_file(flight/'Trajectories'/(stem+'.trj'),i,begin=400000000+20*(i-1))
        clouds.append(str(path));tracks.append(dict(path=t,time_mode='same',gps_week=None,confirmed=False))
    control=root/'Control.csv';control.write_text('1,2040,1040,102,mark\n2,2060,1080,103.4,mark\n',encoding='utf-8')
    (flight/'System').mkdir();(flight/'System'/'eo_Photos_C260101.csv').write_text('Timestamp,Filename,OriginX,OriginY,OriginZ,DX,DY,DZ,UX,UY,UZ\n1,image.jpg,1000,2000,500,0,0,-1,0,1,0\n',encoding='utf-8')
    recipe=Recipe(str(root),clouds=clouds,trajectories=tracks,control=str(control),control_order='pnez',same_vertical=True,cell=3.,window=18.,threshold=1.5,alignment_cell=6.,min_points=6)
    return root,flight,recipe


def test_discovery_uses_sources_and_excludes_generated_clouds(job):
    root,flight,recipe=job
    for folder in (root/'pyArgus_test',root/'pyArgus_jobs',root/'records'):
        folder.mkdir();(folder/'derived.las').write_bytes(b'ignored')
    (root/'CCSM.las').write_bytes(b'not a flight source')
    (root/'Cycle_260101_120000'/'POS').mkdir();pos=root/'Cycle_260101_120000'/'POS'
    (pos/'sbet.out').write_bytes(b'sbet');(pos/'smrmsg.out').write_bytes(b'not a trajectory')
    result=discover(root)
    assert list(result.cloud_groups.values())==[recipe.clouds]
    assert result.controls==[recipe.control]
    assert len(result.eos)==1 and result.sbets==[str(pos/'sbet.out')]
    assert len(result.trjs)==2
    found=suggest(result);assert found.clouds==recipe.clouds
    assert [t['time_mode'] for t in found.trajectories]==['same','same']
    assert found.eo.endswith('eo_Photos_C260101.csv')
    assert not found.same_vertical  # Horizontal EPSG alone does not declare Z.


def test_multiple_groups_and_controls_require_selection(job):
    root,flight,recipe=job
    another=root/'Cycle_260102'/'Flight_260102'/'LAS';another.mkdir(parents=True);(another/'other.las').write_bytes(b'choice required')
    (root/'Survey_Control.csv').write_text('1,2,3,4',encoding='utf-8')
    d=discover(root);r=suggest(d)
    assert not r.clouds and not r.control
    selected=suggest(d,str(flight/'LAS'));assert selected.clouds==recipe.clouds and not selected.control
    issues,_=inspect_recipe(selected);assert any(i['field']=='control' for i in issues)


def test_missing_inputs_create_no_output(job,tmp_path):
    _,_,r=job;r=replace(r,control='',trajectories=[])
    problems,_=inspect_recipe(r)
    assert {'control','trajectories'}<={i['field'] for i in problems}
    out=tmp_path/'run'
    with pytest.raises(ValueError,match='Control CSV'):run(r,out)
    assert not out.exists()


def test_control_order_detects_coordinates_and_refuses_ambiguous(job):
    _,_,r=job
    problems,info=inspect_recipe(replace(r,control_order='auto'))
    assert not problems and info['control_order']=='pnez'
    Path(r.control).write_text('1,9000000,9000000,100,wrong coordinates\n',encoding='utf-8')
    problems,_=inspect_recipe(replace(r,control_order='auto'))
    assert any(i['field']=='control_order' for i in problems)


def test_optional_inputs_are_explicit(job):
    _,_,r=job
    assert not inspect_recipe(replace(r,control='',allow_no_control=True))[0]
    problems,_=inspect_recipe(replace(r,colorize=True))
    assert {'eo','images'}<={i['field'] for i in problems}
    problems,_=inspect_recipe(replace(r,max_points=2))
    assert any(i['field']=='max_points' for i in problems)
    assert not any(i['field']=='max_points' for i in inspect_recipe(replace(r,max_points=2,align=False))[0])


def test_full_native_pipeline_retains_records_and_review_states(job,tmp_path):
    root,_,recipe=job
    # Sparse flight coverage must survive every stage without inventing terrain.
    for path in recipe.clouds:
        cloud=laspy.read(path)
        hole=(cloud.x>1045)&(cloud.x<1065)&(cloud.y>2025)&(cloud.y<2045)
        cloud[~hole].write(path)
    expected=sum(len(laspy.read(path).points) for path in recipe.clouds)
    before={p:sha(p) for p in recipe.clouds+[recipe.control]+[t['path'] for t in recipe.trajectories]}
    out=tmp_path/'run';result=run(recipe,out)
    assert result['status']=='Completed — needs review'
    assert len(result['final_clouds'])==2
    assert result['final_qa']['points']==expected
    assert result['final_qa']['ground_points']==expected
    manifest=json.loads((out/'final_clouds'/'manifest.json').read_text())
    for source,item in zip(recipe.clouds,manifest['clouds']):
        a,b=laspy.read(source),laspy.read(item['output'])
        assert len(a.points)==len(b.points)
        for name in a.point_format.dtype().names:
            if name not in ('Z','classification'):assert a.points.array[name].tobytes()==b.points.array[name].tobytes(),name
        assert np.all(b.classification==2)
        assert sha(item['output'])==item['sha256']
    first,second=[laspy.read(p) for p in result['final_clouds']]
    np.testing.assert_allclose(first.z,second.z,atol=.002)
    assert before=={p:sha(p) for p in before}
    alignment_report=json.loads((out/'alignment'/'alignment_comparison.json').read_text())
    assert (out/'alignment'/'report.html').is_file()
    assert alignment_report['checkpoint_summary']['supplied']==2
    assert alignment_report['checkpoint_summary']['independent_paired_support']==0
    assert alignment_report['settings']['role']=='reference'
    assert alignment_report['review_status']=='Needs review'
    assert 'alignment/report.html' in (out/'report.html').read_text()
    tracker=Tracker.load(result['workspace'])
    for stage in ('Inspect','Initial QA','Classification','Alignment','Surface','Contours','Final QA','Delivery'):assert tracker.status(stage)=='Needs review',stage
    assert tracker.status('Colorization')=='Skipped'
    assert not tracker.data['decisions'] or all(d['decision']=='Skipped' for d in tracker.data['decisions'])
    records=list(tmp_path.glob('run.job-*.json'));assert len(records)==1 and json.loads(records[0].read_text())['status']=='completed'
    with np.load(out/'surface'/'grid.npz') as data:
        grid=data['grid'];missing=data['counts']==0
    assert missing.any()
    assert np.array_equal(np.isnan(grid),missing)
    published=np.loadtxt(out/'surface'/'dtm.asc',skiprows=6,ndmin=2)[::-1].T
    assert np.all(published[missing]==-9999.)
    published[missing]=np.nan
    np.testing.assert_array_equal(grid,published)
    assert (out/'surface'/'dtm.dxf').is_file() and (out/'contours'/'contours.dxf').is_file()
    assert json.loads((out/'surface'/'summary.json').read_text())['gap_fill'] is False


def test_cancel_retains_completed_stages_and_no_delivery(job,tmp_path):
    _,_,recipe=job;out=tmp_path/'run';stopping=[False]
    def event(s):
        if s['stage']=='Initial QA' and s['status'].startswith('Completed'):stopping[0]=True
    result=run(recipe,out,cancel=lambda:stopping[0],on_stage=event)
    assert result['status']=='Cancelled' and not (out/'final_clouds').exists()
    assert (out/'baseline_qa'/'report.html').is_file()
    assert json.loads(next(tmp_path.glob('run.job-*.json')).read_text())['status']=='cancelled'
    assert Tracker.load(out/'project.argus.json').status('Delivery')=='Not started'


def test_changed_input_stops_before_processing(job,tmp_path):
    _,_,recipe=job;out=tmp_path/'run'
    def event(s):
        if s['stage']=='Inspect' and s['status'].startswith('Completed'):
            with Path(recipe.control).open('a') as f:f.write('3,2060,1080,103.4,added\n')
    with pytest.raises(ValueError,match='Input changed'):run(recipe,out,on_stage=event)
    assert not (out/'classification').exists() and not (out/'final_clouds').exists()
    assert json.loads((out/'run.json').read_text())['status']=='Failed'


def test_existing_output_is_never_overwritten(job,tmp_path):
    _,_,recipe=job;out=tmp_path/'run';out.mkdir();sentinel=out/'keep.txt';sentinel.write_text('keep')
    with pytest.raises(ValueError,match='existing files'):run(recipe,out)
    assert sentinel.read_text()=='keep'


def test_duplicate_las_and_laz_are_flagged(job):
    _,_,recipe=job;source=Path(recipe.clouds[0]);other=source.with_suffix('.laz');laspy.read(source).write(other)
    issues,_=inspect_recipe(replace(recipe,clouds=recipe.clouds+[str(other)]))
    assert any('Both LAS and LAZ' in i['message'] for i in issues)


def test_clock_failure_preserves_inventory_and_originals(job,tmp_path):
    _,_,recipe=job;before={p:sha(p) for p in recipe.clouds}
    wrong=[dict(t,time_mode='week') for t in recipe.trajectories]
    with pytest.raises(ValueError):run(replace(recipe,trajectories=wrong),tmp_path/'run')
    assert before=={p:sha(p) for p in before}
    assert not (tmp_path/'run'/'final_clouds').exists()
    assert json.loads((tmp_path/'run'/'run.json').read_text())['status']=='Failed'


def test_unreadable_las_keeps_a_recipe_for_manual_replacement(job):
    root,_,recipe=job;Path(recipe.clouds[0]).write_bytes(b'broken LAS')
    found=suggest(discover(root))
    assert found.clouds==recipe.clouds and found.control==recipe.control
    issues,_=inspect_recipe(found)
    assert any(i['field']=='clouds' for i in issues)


def test_unreadable_trj_is_reported_without_discarding_other_inputs(job):
    root,_,recipe=job;Path(recipe.trajectories[0]['path']).write_bytes(b'broken TRJ')
    found=suggest(discover(root))
    assert found.clouds==recipe.clouds and len(found.trajectories)==2
    issues,_=inspect_recipe(replace(found,same_vertical=True))
    assert any(i['field']=='trajectories' and 'truncated TRJ' in i['message'] for i in issues)


def test_surface_gaps_preserve_ascii_support_in_cad_and_contours(job,tmp_path):
    import ezdxf
    from pyargus.lp360_workflow import _surface
    from pyargus.surfaces.contours import contour_grid
    _,_,recipe=job
    x,y=np.meshgrid(np.arange(7),np.arange(7))
    keep=~((x>=2)&(x<=4)&(y>=2)&(y<=4))
    header=laspy.LasHeader(point_format=6,version='1.4')
    header.scales=[.001,.001,.001];header.add_crs(pyproj.CRS.from_epsg(2277))
    cloud=laspy.LasData(header)
    cloud.x=1000.5+x[keep];cloud.y=2000.5+y[keep]
    cloud.z=100.+.27*x[keep]+.13*y[keep];cloud.classification=np.full(keep.sum(),2)
    source=tmp_path/'sparse.las';cloud.write(source)
    folder=tmp_path/'surface'
    grid,xe,ye,_=_surface([str(source)],folder,replace(recipe,cell=1.),lambda:False)
    with np.load(folder/'grid.npz') as data:
        occupied=data['counts']>0
        np.testing.assert_array_equal(data['grid'],grid)
    assert np.array_equal(np.isfinite(grid),occupied)
    assert np.isnan(grid[2:5,2:5]).all()
    published=np.loadtxt(folder/'dtm.asc',skiprows=6,ndmin=2)[::-1].T
    assert np.all(published[~occupied]==-9999.)
    np.testing.assert_array_equal(grid[occupied],published[occupied])
    squares=occupied[:-1,:-1]&occupied[1:,:-1]&occupied[1:,1:]&occupied[:-1,1:]
    faces=list(ezdxf.readfile(folder/'dtm.dxf').modelspace().query('3DFACE'))
    assert len(faces)==2*int(squares.sum()) and faces
    for face in faces:
        for vertex in (face.dxf.vtx0,face.dxf.vtx1,face.dxf.vtx2):
            i=int(np.floor(vertex.x-xe[0]));j=int(np.floor(vertex.y-ye[0]))
            assert occupied[i,j] and vertex.z==grid[i,j]
    summary=json.loads((folder/'summary.json').read_text())
    assert summary['finite_cells']==int(occupied.sum())<summary['grid_cells']
    finite=grid[occupied]
    assert (finite.max()-finite.min())/recipe.contour_interval<1000
    lines=contour_grid(grid,xe,ye,.25)
    assert lines and all(finite.min()<=line.level<=finite.max() for line in lines)
    assert all(not np.any((line.xy[:,0]>1002.5)&(line.xy[:,0]<1004.5)&
                         (line.xy[:,1]>2002.5)&(line.xy[:,1]<2004.5)) for line in lines)
