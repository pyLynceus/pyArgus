"""Recorded LP360 orchestration over the existing processing engines."""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import hashlib, html, json, os, shutil, time
import numpy as np
from pyargus import project
from pyargus.analysis_records import plain
from pyargus.job_manifest import identity, utc_now, JobRecord
from pyargus.lp360_jobs import inspect_recipe
from pyargus.workspace_state import Tracker


class Cancelled(Exception):pass


def _save(path,value):
    path=Path(path);tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(plain(value),indent=2,allow_nan=False)+'\n',encoding='utf-8');os.replace(tmp,path)


def _digest(path,cancel):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):
            if cancel():raise Cancelled('Stop requested')
            h.update(block)
    return h.hexdigest()


def _transfer(spec,mapping):
    return replace(spec,clouds=[mapping.get(p,p) for p in spec.clouds],bindings={mapping.get(c,c):t for c,t in spec.bindings.items()})


def _surface(paths,folder,recipe,cancel):
    from pyargus.formats.las import iter_points
    from pyargus.core import gridding
    from pyargus.surfaces.dtm import write_esri_ascii
    import laspy,ezdxf
    low=np.full(2,np.inf);high=np.full(2,-np.inf);ground=0
    def chunks():
        for source in paths:
            for pts in iter_points(source,fields=('x','y','z','classification'),chunk_size=500_000):
                if cancel():raise Cancelled('Stop requested')
                keep=pts['classification']==2
                if keep.any():yield [pts[name][keep] for name in ('x','y','z')]
    for x,y,z in chunks():
        if not np.isfinite(np.column_stack((x,y,z))).all():raise ValueError('Ground coordinates contain nonfinite values')
        low=np.minimum(low,[x.min(),y.min()]);high=np.maximum(high,[x.max(),y.max()]);ground+=len(z)
    if not ground:raise ValueError('No class-2 ground remains; review classification before surfacing.')
    xe,ye=gridding.grid_edges(np.array([low[0],high[0]]),np.array([low[1],high[1]]),recipe.cell)
    shape=(len(xe)-1,len(ye)-1)
    if shape[0]*shape[1]>recipe.max_grid_cells:raise ValueError('Surface exceeds the configured grid-cell limit; increase cell size or select a smaller block.')
    sums=np.zeros(shape);counts=np.zeros(shape,dtype=np.uint64)
    for x,y,z in chunks():
        ix,iy=gridding.cell_indices(x,y,xe,ye);np.add.at(sums,(ix,iy),z);np.add.at(counts,(ix,iy),1)
    grid=np.full(shape,np.nan);np.divide(sums,counts,out=grid,where=counts>0)
    if int(counts.sum())!=ground:raise ValueError('Ground-cell counts do not reproduce source returns')
    folder.mkdir();asc=folder/'dtm.asc';write_esri_ascii(asc,grid,xe,ye)
    # CAD and contours use exactly the published ASCII elevations.
    grid=np.loadtxt(asc,skiprows=6,ndmin=2)[::-1].T
    # ASCII uses a finite nodata marker. Restore the original support mask
    # after quantization so CAD and contours cannot turn empty cells into terrain.
    grid[counts==0]=np.nan
    with laspy.open(paths[0]) as r:crs=r.header.parse_crs()
    if crs is None:
        import pyproj
        crs=pyproj.CRS.from_user_input(recipe.map_crs)
    factor=crs.axis_info[0].unit_conversion_factor
    units=6 if np.isclose(factor,1.,rtol=1e-12) else 21 if np.isclose(factor,1200/3937,rtol=1e-12) else 2 if np.isclose(factor,.3048,rtol=1e-12) else 0
    asc.with_suffix('.prj').write_text(crs.to_wkt()+'\n',encoding='utf-8')
    np.savez_compressed(folder/'grid.npz',grid=grid,x_edges=xe,y_edges=ye,counts=counts)
    doc=ezdxf.new('R2010');doc.header['$INSUNITS']=units;doc.layers.new('DTM',dxfattribs={'color':3});model=doc.modelspace()
    cx=(xe[:-1]+xe[1:])/2;cy=(ye[:-1]+ye[1:])/2;faces=0
    for i in range(shape[0]-1):
        if cancel():raise Cancelled('Stop requested')
        for j in range(shape[1]-1):
            heights=[grid[i,j],grid[i+1,j],grid[i+1,j+1],grid[i,j+1]]
            if not np.isfinite(heights).all():continue
            corners=[(cx[i],cy[j],heights[0]),(cx[i+1],cy[j],heights[1]),(cx[i+1],cy[j+1],heights[2]),(cx[i],cy[j+1],heights[3])]
            for a,b,c in ((0,1,2),(0,2,3)):
                model.add_3dface([corners[a],corners[b],corners[c],corners[c]],dxfattribs={'layer':'DTM'});faces+=1
    doc.saveas(folder/'dtm.dxf');(folder/'dtm.prj').write_text(crs.to_wkt()+'\n',encoding='utf-8')
    audit=ezdxf.readfile(folder/'dtm.dxf').audit()
    if audit.has_errors or audit.has_fixes:raise ValueError('Surface DXF failed its readback audit')
    _save(folder/'summary.json',dict(ground_points=ground,finite_cells=int(np.isfinite(grid).sum()),grid_cells=int(grid.size),faces=faces,cell=recipe.cell,gap_fill=False,statistic='class-2 cell mean',units=crs.axis_info[0].unit_name))
    return grid,xe,ye,crs


def run(recipe,out,*,log=lambda s:None,cancel=lambda:False,on_stage=lambda state:None):
    """Run one new job. Completed stages remain Needs review, never auto-accepted."""
    issues,info=inspect_recipe(recipe)
    if issues:raise ValueError('\n'.join(i['message'] for i in issues))
    recipe=replace(recipe,control_order=info['control_order'])
    out=Path(out).resolve();root=Path(recipe.root).resolve()
    if out==root or out.exists():raise ValueError('Choose a new output folder; existing files are preserved.')
    sources=recipe.clouds+[t['path'] for t in recipe.trajectories]+[p for p in (recipe.control,recipe.alignment_reporting.get('checkpoints',''),recipe.eo if recipe.colorize else '',recipe.calibration if recipe.colorize else '') if p]
    for p in sources:
        if Path(p).resolve().is_relative_to(out):raise ValueError('An input is inside the proposed output folder.')
    volume=out.parent
    while not volume.exists():
        if volume==volume.parent:raise ValueError('Output drive is unavailable; choose an existing output parent.')
        volume=volume.parent
    if shutil.disk_usage(volume).free<info['points']*256+info['uncompressed_bytes']*(5 if recipe.colorize else 4):raise ValueError('Insufficient disk space for exact QA scratch and new cloud versions.')
    identities=[identity(p) for p in sources];out.parent.mkdir(parents=True,exist_ok=True);out.mkdir()
    workspace=out/'project.argus.json';tracker=Tracker();state=dict(status='Running',root=recipe.root,started=utc_now(),recipe=asdict(recipe),inputs=identities,steps=[],workspace=str(workspace),review='Completed stages need review; automatic processing is not an accuracy approval.')
    spec=recipe.spec();tracker.data['project']=asdict(spec)
    tracker.data['layers']=[dict(path=p,kind='cloud',origin='LP360 source',visible=False) for p in recipe.clouds]
    if recipe.control:tracker.data['layers'].append(dict(path=recipe.control,kind='control',order=recipe.control_order,origin='LP360 control',visible=False))
    tracker.data['lp360_job']=str(out/'run.json');started=time.monotonic();record_path=None
    def check():
        if cancel():raise Cancelled('Stop requested')
        for item in identities:
            if identity(item['path'])!=item:raise ValueError('Input changed during the job: '+item['path'])
    def persist():
        tracker.data['project']=asdict(spec);tracker.save(workspace);_save(out/'run.json',state)
    def stage(name,inputs,action,settings=None,stage_class=None):
        check();entry=dict(stage=name,status='Running',started=utc_now());state['steps'].append(entry)
        job=tracker.begin(name,settings or {},inputs);job.update(source='lp360',records=[])
        if stage_class:job['stage_class']=stage_class
        begin=time.monotonic();persist();on_stage(dict(entry));log('LP360: '+name)
        try:
            result,products=action();check()
            tracker.finish(job,'Needs review',products,elapsed=time.monotonic()-begin)
            job['records']=[str(p) for folder in {Path(p).parent for p in products} for p in folder.glob('*.job-*.json') if p.stat().st_mtime>=time.time()-(time.monotonic()-begin)-1]
            entry.update(status='Completed — needs review',elapsed=round(time.monotonic()-begin,2),outputs=[str(p) for p in products])
            known={l['path'] for l in tracker.data['layers']}
            tracker.data['layers'] += [dict(path=str(p),kind='output',origin='LP360 '+name,visible=False) for p in products if str(p) not in known]
            persist();on_stage(dict(entry));return result,job
        except Exception as exc:
            status='Cancelled' if cancel() or isinstance(exc,Cancelled) else 'Failed'
            tracker.finish(job,status,error=str(exc),elapsed=time.monotonic()-begin);entry.update(status=status,error=str(exc));persist();on_stage(dict(entry));raise
    def skip(name,reason):
        tracker.decide(name,'Skipped',reason);state['steps'].append(dict(stage=name,status='Skipped',reason=reason));persist()
    def qa_action(folder):
        control=None
        if recipe.control:
            from pyargus.formats.control import read_control_csv
            control=read_control_csv(recipe.control,recipe.control_order)
        value=project.qa(replace(spec,max_points=1),folder,control=control,log=log,cancel=cancel)
        return value,[folder/'report.html',folder/'summary.json',folder/'inventory.json']
    def inspect_action():
        inventory=project.load(spec,keep_points=False,log=log,cancel=cancel).inventory
        _save(out/'inventory.json',inventory)
        if inventory['unmatched'] or inventory['ambiguous']:
            if recipe.align:raise ValueError(f"Trajectory matching needs attention: {inventory['unmatched']:,} unmatched, {inventory['ambiguous']:,} ambiguous. Inventory saved; correct the trajectory/time settings before alignment.")
        return inventory,[out/'inventory.json']
    def report():
        rows=[]
        for item in state['steps']:
            links=[]
            for p in item.get('outputs',[]):
                path=Path(p);href=path.relative_to(out).as_posix() if path.is_relative_to(out) else path.as_uri()
                links.append(f'<a href="{html.escape(href,quote=True)}">{html.escape(path.name)}</a>')
            rows.append(f"<tr><td>{html.escape(item['stage'])}</td><td>{html.escape(item['status'])}</td><td>{'<br>'.join(links)}</td><td>{html.escape(item.get('error',item.get('reason','')))}</td></tr>")
        body=f'<!doctype html><html><meta charset="utf-8"><title>LP360 job results</title><style>body{{font:16px system-ui;max-width:1150px;margin:32px auto;color:#17382e}}td,th{{padding:10px;border-bottom:1px solid #ccc;text-align:left}}table{{width:100%}}</style><h1>LP360 job: {html.escape(root.name)}</h1><p>Status: {html.escape(state["status"])}. {html.escape(state["review"])}</p><p>Source: {html.escape(str(root))}. Original files are preserved. Alignment, when enabled, solves relative vertical offsets with the first strip fixed; survey marks are used for QA, not fitted as control. Existing colors and noise classes are preserved unless recoloring or explicit height bounds were selected.</p><table><tr><th>Stage</th><th>Status</th><th>Outputs</th><th>Details</th></tr>{"".join(rows)}</table><p><a href="project.argus.json">pyArgus workspace</a> · <a href="run.json">Settings and processing history</a></p></html>'
        (out/'report.html').write_text(body,encoding='utf-8')
    try:
        with JobRecord('lp360-job',out,asdict(recipe)) as record:
            record_path=str(record.path);record.data['inputs']=identities;record.save()
            state['job_record']=record_path
            stage('Inspect',sources,inspect_action,dict(mode='inspect',project=asdict(spec)))
            stage('Initial QA',sources,lambda:qa_action(out/'baseline_qa'),dict(phase='Baseline',control=recipe.control))
            from pyargus.classify.job import classify_ground_tiled
            (out/'classification').mkdir();mapping={}
            for index,source in enumerate(spec.clouds,1):
                dest=out/'classification'/f'{index:03d}_{Path(source).stem}_ground.las'
                def classify(source=source,dest=dest):
                    value=classify_ground_tiled(source,dest,cell=recipe.cell,slope=recipe.slope,window=recipe.window,threshold=recipe.threshold,noise_min=recipe.noise_min,noise_max=recipe.noise_max,workers=recipe.workers,memory_mb=recipe.memory_mb,log=log,should_stop=cancel)
                    if value.get('cancelled'):raise Cancelled('Classification stopped')
                    return value,[dest]
                _,job=stage('Classification',[source],classify,dict(cloud=source,stage=dict(cell=recipe.cell,slope=recipe.slope,window=recipe.window,threshold=recipe.threshold)),stage_class='ClassifyStage')
                mapping[source]=str(dest);tracker.register_cloud_result(source,str(dest),job['id'])
            spec=_transfer(spec,mapping);persist()
            stage('Initial QA',spec.clouds,lambda:qa_action(out/'ground_qa'),dict(phase='Ground QA',control=recipe.control))
            if recipe.align:
                def align():
                    from pyargus.qa.alignment_report import settings, PRODUCTS
                    reporting=settings(recipe.alignment_reporting)
                    if not reporting['checkpoints'] and recipe.control:
                        reporting.update(checkpoints=recipe.control,order=recipe.control_order,role='reference',surface='unspecified')
                    alignment_spec=replace(spec,alignment_reporting=reporting)
                    result=project.align(alignment_spec,out/'alignment',cell=recipe.alignment_cell,min_points=recipe.min_points,solve_boresight=False,log=log,cancel=cancel)
                    return result,[out/'alignment'/'alignment.json']+[out/'alignment'/name for name in PRODUCTS]+[out/'alignment'/item['output'] for item in result['outputs']]
                result,job=stage('Alignment',spec.clouds+[t.path for t in spec.trajectories]+[p for p in (recipe.alignment_reporting.get('checkpoints'),recipe.control) if p],align,dict(solve_boresight=False,cell=recipe.alignment_cell))
                mapping={item['source']:str(out/'alignment'/item['output']) for item in result['outputs']}
                for source,dest in mapping.items():tracker.register_cloud_result(source,dest,job['id'])
                spec=_transfer(spec,mapping);persist()
            else:skip('Alignment','Disabled in the LP360 recipe; no strip correction applied.')
            if recipe.colorize:
                from pyargus.imagery.job import colorize_cloud
                (out/'colorization').mkdir();mapping={}
                for index,source in enumerate(spec.clouds,1):
                    dest=out/'colorization'/f'{index:03d}_{Path(source).stem}_rgb.las'
                    def color(source=source,dest=dest):
                        value=colorize_cloud(source,recipe.eo,recipe.images,dest,cal=recipe.calibration or None,quarter_turns=recipe.quarter_turns,memory_budget_mb=recipe.memory_mb,log=log,should_stop=cancel)
                        if value.get('cancelled'):raise Cancelled('Colorization stopped')
                        return value,[dest]
                    _,job=stage('Colorization',[source,recipe.eo],color,dict(eo=recipe.eo,images=recipe.images))
                    mapping[source]=str(dest);tracker.register_cloud_result(source,str(dest),job['id'])
                spec=_transfer(spec,mapping);persist()
            else:skip('Colorization','Preserve existing cloud colors; EO and camera files remain available for optional recoloring.')
            def surface():
                values=_surface(spec.clouds,out/'surface',recipe,cancel)
                return values,[out/'surface'/'dtm.asc',out/'surface'/'dtm.dxf',out/'surface'/'summary.json']
            values,_=stage('Surface',spec.clouds,surface,dict(cell=recipe.cell,gap_fill=False))
            grid,xe,ye,crs=values
            def contours():
                from pyargus.surfaces.contours import contour_grid
                from pyargus.formats.dxf import write_contours_dxf
                finite=grid[np.isfinite(grid)]
                if (finite.max()-finite.min())/recipe.contour_interval>1000:raise ValueError('More than 1000 contour levels; review ground elevations or increase contour interval.')
                lines=contour_grid(grid,xe,ye,recipe.contour_interval);folder=out/'contours';folder.mkdir();cad=folder/'contours.dxf'
                if lines:write_contours_dxf(cad,lines)
                else:
                    import ezdxf
                    ezdxf.new('R2010').saveas(cad)
                cad.with_suffix('.prj').write_text(crs.to_wkt()+'\n',encoding='utf-8')
                _save(folder/'summary.json',dict(lines=len(lines),vertices=sum(len(l.xy) for l in lines),interval=recipe.contour_interval,smoothing=False,source=str(out/'surface'/'dtm.asc')))
                return dict(lines=len(lines)),[cad,folder/'summary.json']
            stage('Contours',[str(out/'surface'/'dtm.asc')],contours,dict(interval=recipe.contour_interval))
            final_qa,_=stage('Final QA',spec.clouds,lambda:qa_action(out/'final_qa'),dict(control=recipe.control))
            def delivery():
                folder=out/'final_clouds';folder.mkdir();products=[];receipts=[]
                for index,source in enumerate(spec.clouds,1):
                    check();dest=folder/f'{index:03d}_{Path(recipe.clouds[index-1]).stem}_final{Path(source).suffix.lower()}'
                    before=identity(source);expected_hash=_digest(source,cancel);shutil.copy2(source,dest)
                    if identity(source)!=before or _digest(dest,cancel)!=expected_hash:raise ValueError('Final cloud copy failed verification')
                    receipts.append(dict(source=source,output=str(dest),sha256=expected_hash,size_bytes=dest.stat().st_size));products.append(dest)
                _save(folder/'manifest.json',dict(clouds=receipts,points=final_qa['points'],ground_points=final_qa['ground_points'],qa=str(out/'final_qa'/'report.html'),review='Needs review; output creation is not accuracy acceptance.'))
                return receipts,products+[folder/'manifest.json']
            exported,_=stage('Delivery',spec.clouds,delivery,dict(export='verified separate final flight files'))
            # Reference the current processing versions; delivery copies are output layers.
            # Completed-stage output layers were added as each stage finished.
            tracker.data.update(view={},active_cloud=spec.clouds[0],qa_phase='Final QA',ui_layout=dict(mode='Review',pane='Job history',dock=True))
            state.update(status='Completed — needs review',finished=utc_now(),elapsed=round(time.monotonic()-started,2),final_clouds=[item['output'] for item in exported],final_qa=plain(final_qa));check();persist();report()
            record.finish('completed',dict(workspace=str(workspace),report=str(out/'report.html'),final_clouds=state['final_clouds'],review_status='Needs review'))
        return state
    except Exception as exc:
        stopped=cancel() or isinstance(exc,(Cancelled,InterruptedError))
        state.update(status='Cancelled' if stopped else 'Failed',error=str(exc),finished=utc_now(),elapsed=round(time.monotonic()-started,2));persist();report()
        if stopped:
            if record_path:
                record.data.update(status='cancelled',results=dict(workspace=str(workspace),reason=str(exc)))
                record.data.pop('error',None);record.save()
            return state
        raise
