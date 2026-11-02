"""Read-only flightline diagnosis with disk-backed, common-cell evidence.

Qualified OLS planes are evaluated at cell centers, reducing the sampling
imbalance that can contaminate raw cell-median differences on sloped ground.
Neither these residuals nor a diagnostic trend is an instruction to adjust.
"""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import html
import json
import math
import sqlite3
import os
import shutil
import time
import tempfile
from contextlib import ExitStack
import numpy as np

FT_US = 1200 / 3937
DEFAULTS = dict(cell_ft=6., min_points=6, max_scatter_ft=.08, max_slope=.25,
                tolerance_ft=.10, min_cells=12)
LIMITATIONS = [
    'Class 2 is assumed ground; it does not prove pavement or a surveyed surface.',
    'Equal-cell OLS surface differences can still contain curvature, classification, sampling and georeferencing effects.',
    'Raw cell medians are retained in surface_cells.csv; they are not interchangeable with qualified plane-height differences.',
    'No corrections are fitted or applied. Spatial patterns do not identify a boresight, lever-arm or datum cause.',
    'No survey residuals are measured here. Independent absolute accuracy is not assessed.',
    'Coverage is observed occupied cells, not planned flight sidelap or a surveyed footprint.',
    'Map samples are bounded; CSVs and statistics retain all measured cells.',
]


def settings(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError('Flightline diagnostic settings must be a dictionary')
    unknown = set(value or {}) - set(DEFAULTS)
    if unknown:
        raise ValueError('Unknown diagnostic settings: ' + ', '.join(sorted(unknown)))
    result = dict(DEFAULTS, **(value or {}))
    for key in ('cell_ft', 'max_scatter_ft', 'max_slope', 'tolerance_ft'):
        v = result[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise ValueError(f'{key} must be finite and positive')
    for key, minimum in (('min_points', 3), ('min_cells', 3)):
        if type(result[key]) is not int or result[key] < minimum:
            raise ValueError(f'{key} must be an integer of at least {minimum}')
    return result


def _check(cancel):
    from pyargus.project import _check_cancel
    _check_cancel(cancel)


def _csv(path, fields, rows):
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)


class Store:
    def __init__(self, path, cell, config, cancel, log=lambda text:None):
        from pyargus.qa import coverage
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('PRAGMA cache_size=-32768')
        self.db.execute('PRAGMA journal_mode=OFF')
        self.db.set_progress_handler(lambda: int(cancel()), 10000)
        coverage.create(self.db)
        self.db.execute('CREATE TABLE ground(x INTEGER,y INTEGER,s INTEGER,z REAL)')
        names = ['n','u','v','uu','uv','vv','w','uw','vw','ww','q0','q1','q2','q3']
        self.db.execute('CREATE TABLE moments(x INTEGER,y INTEGER,s INTEGER,' + ','.join(k+' REAL' for k in names) + ',PRIMARY KEY(x,y,s)) WITHOUT ROWID')
        self.names = names
        self.config, self.cell, self.cancel = config, cell, cancel
        self.z0 = None
        self.path=Path(path);self.seen=set();self.log=log;self.point_count=0;self.last_log=0.

    def ingest(self, p, chosen):
        from pyargus.qa import coverage
        _check(self.cancel)
        keys = (chosen.astype(np.int64) + 2) * 65536 + p['point_source_id'].astype(np.int64)
        self.seen.update(np.unique(keys).tolist())
        if len(self.seen)>128:raise ValueError('Diagnostics supports at most 128 analysis flightlines; select a smaller project')
        if shutil.disk_usage(self.path.parent).free<256*1024**2:raise ValueError('Diagnostics stopped: less than 256 MiB of scratch-drive space remains')
        grid = np.floor(np.column_stack([p['x'], p['y']]) / self.cell)
        if np.any(np.abs(grid) > 2**50):
            raise ValueError('Coordinates/cell size exceed the supported cell-index range')
        coverage.ingest(self.db,p['x'],p['y'],p['classification'],keys,self.cell)
        keep = p['classification'] == 2
        if np.any(keep):
            x,y,z = (p[k][keep] for k in ('x','y','z'))
            if self.z0 is None:
                self.z0 = float(z[0])
            cells = grid[keep].astype(np.int64)
            s = keys[keep]
            self.db.executemany('INSERT INTO ground VALUES(?,?,?,?)',zip(cells[:,0].tolist(),cells[:,1].tolist(),s.tolist(),z.tolist()))
            u = x / self.cell - cells[:,0] - .5
            v = y / self.cell - cells[:,1] - .5
            w = z - self.z0
            group, inverse = np.unique(np.column_stack([cells,s]),axis=0,return_inverse=True)
            q = 2*(u>=0).astype(int)+(v>=0).astype(int)
            values = [np.bincount(inverse,weights=a,minlength=len(group)) for a in
                      (np.ones(len(z)),u,v,u*u,u*v,v*v,w,u*w,v*w,w*w,q==0,q==1,q==2,q==3)]
            records = zip(group[:,0].tolist(),group[:,1].tolist(),group[:,2].tolist(),*(a.tolist() for a in values))
            self.db.executemany('INSERT INTO moments VALUES('+','.join('?' for _ in range(17))+') '
                'ON CONFLICT(x,y,s) DO UPDATE SET '+','.join(k+'='+k+'+excluded.'+k for k in self.names),records)
        self.db.commit()
        self.point_count+=len(chosen)
        if time.monotonic()-self.last_log>5:
            self.log(f'Diagnostic scratch: {self.point_count:,} point records read')
            self.last_log=time.monotonic()

    def reduce(self):
        _check(self.cancel)
        self.db.executescript('''CREATE INDEX ground_order ON ground(x,y,s,z);
          CREATE TABLE medians AS SELECT x,y,s,avg(z) AS median FROM (
            SELECT x,y,s,z,row_number() OVER(PARTITION BY x,y,s ORDER BY z) AS r,
              count(*) OVER(PARTITION BY x,y,s) AS n FROM ground)
            WHERE r IN ((n+1)/2,(n+2)/2) GROUP BY x,y,s;
          CREATE UNIQUE INDEX median_keys ON medians(x,y,s);
          CREATE TABLE surfaces(x INTEGER,y INTEGER,s INTEGER,n INTEGER,median REAL,
             height REAL,scatter REAL,slope REAL,condition REAL,reason TEXT,PRIMARY KEY(x,y,s)) WITHOUT ROWID;''')
        cursor = self.db.execute('SELECT m.x,m.y,m.s,'+','.join('m.'+k for k in self.names)+',d.median FROM moments m JOIN medians d USING(x,y,s)')
        batch=[]
        for i,row in enumerate(cursor):
            if i%2000==0: _check(self.cancel)
            x,y,s,n,u,v,uu,uv,vv,w,uw,vw,ww,*tail = row
            quadrants, median = tail[:4],tail[4]
            height=scatter=slope=condition=None
            reason=''
            if n < self.config['min_points']:
                reason='Too few ground returns'
            elif not all(quadrants):
                reason='Cell center lacks ground returns in all four quadrants'
            else:
                design=np.array([[uu,uv,u],[uv,vv,v],[u,v,n]],dtype=float)
                eig=np.linalg.eigvalsh(design)
                if eig[0] <= max(eig[-1],1.)*1e-12:
                    reason='Rank-deficient local plane'
                else:
                    condition=math.sqrt(float(eig[-1]/eig[0]))
                    if condition>30:
                        reason='Poorly conditioned local plane'
                    else:
                        rhs=np.array([uw,vw,w])
                        beta=np.linalg.solve(design,rhs)
                        rss=float(ww-beta@rhs)
                        allowance=64*np.finfo(float).eps*(abs(ww)+abs(float(beta@rhs))+1)
                        if rss < -allowance:
                            reason='Numerically unstable local scatter'
                        else:
                            scatter=math.sqrt(max(0.,rss)/n)
                            slope=float(np.linalg.norm(beta[:2])/self.cell)
                            if scatter>self.config['max_scatter']:
                                reason='Local plane scatter exceeds limit'
                            elif slope>self.config['max_slope']:
                                reason='Local surface slope exceeds limit'
                            else:
                                height=float(self.z0+beta[2])
            batch.append((x,y,s,int(n),median,height,scatter,slope,condition,reason))
            if len(batch)>=2000:
                self.db.executemany('INSERT INTO surfaces VALUES(?,?,?,?,?,?,?,?,?,?)',batch);batch=[]
        self.db.executemany('INSERT INTO surfaces VALUES(?,?,?,?,?,?,?,?,?,?)',batch)
        self.db.commit()


def _percentile(db, table, column, q, where='1', parameters=()):
    from pyargus.large_qa import percentile
    return percentile(db,table,column,q,where,parameters)


def _stats(db, table, column, tolerance, where='1', parameters=()):
    n,mean,square,exceed=db.execute(f'SELECT count(*),avg({column}),avg(({column})*({column})),sum(abs({column})>?) FROM {table} WHERE {where}',(tolerance,*parameters)).fetchone()
    if not n:
        return dict(cells=0,mean=None,median=None,rmse=None,nmad=None,p95_abs=None,exceeding=None)
    median=_percentile(db,table,column,.5,where,parameters)
    nmad=1.4826*_percentile(db,table,f'abs(({column})-({median!r}))',.5,where,parameters)
    return dict(cells=n,mean=mean,median=median,rmse=math.sqrt(square),nmad=nmad,
                p95_abs=_percentile(db,table,f'abs({column})',.95,where,parameters),exceeding=int(exceed))


def _trend(db, a, b, cell, ft_per_unit):
    where='a=? AND b=?';parameters=(a,b)
    n,x0,y0=db.execute('SELECT count(*),avg(x),avg(y) FROM residuals WHERE '+where,parameters).fetchone()
    if n<6:
        return dict(available=False,reason='Too few qualified cells for a spatial trend')
    xlo,xhi,ylo,yhi=db.execute('SELECT min(x),max(x),min(y),max(y) FROM residuals WHERE '+where,parameters).fetchone()
    scale=max(float(xhi-xlo),float(yhi-ylo),1.)
    u=f'((x-({x0!r}))/({scale!r}))';v=f'((y-({y0!r}))/({scale!r}))'
    sums=db.execute(f'SELECT sum({u}),sum({v}),sum({u}*{u}),sum({u}*{v}),sum({v}*{v}),sum({u}*dz),sum({v}*dz),sum(dz) FROM residuals WHERE '+where,parameters).fetchone()
    su,sv,suu,suv,svv,suz,svz,sz=sums
    design=np.array([[suu,suv,su],[suv,svv,sv],[su,sv,n]],dtype=float)
    eig=np.linalg.eigvalsh(design)
    if eig[0]<=max(eig[-1],1.)*1e-12 or math.sqrt(eig[-1]/eig[0])>30:
        return dict(available=False,reason='Overlap geometry does not support a conditioned 2D spatial trend')
    beta=np.linalg.solve(design,[suz,svz,sz])
    return dict(available=True,east_gradient_per_1000ft=float(beta[0]*1000/(scale*cell*ft_per_unit)),north_gradient_per_1000ft=float(beta[1]*1000/(scale*cell*ft_per_unit)),
                intercept=float(beta[2]),condition=math.sqrt(float(eig[-1]/eig[0])),
                note='Descriptive OLS trend in cloud units per 1000 US survey ft; not a correction or physical-cause diagnosis')


def _sample(db, query, count, limit=1000, parameters=()):
    stride=max(1,math.ceil(count/limit))
    result=[]
    for index,row in enumerate(db.execute(query,parameters)):
        if index%stride==0 and len(result)<limit:
            result.append(list(row))
    return result


def _dataset(store,data,folder,config,ft_per_unit,cancel):
    db=store.db
    inventory=data.inventory
    if len(inventory['strips'])>128:
        raise ValueError('Diagnostics supports at most 128 analysis flightlines per run; select a smaller project')
    mapping={(s['trajectory']+2)*65536+s['source_id']:s['id'] for s in inventory['strips']}
    db.execute('CREATE TABLE flight_keys(raw INTEGER PRIMARY KEY,id INTEGER)')
    db.execute('CREATE INDEX coverage_flight ON coverage_entries(s,x,y)')
    db.executemany('INSERT INTO flight_keys VALUES(?,?)',mapping.items())
    db.executescript('''CREATE TABLE measured AS SELECT x,y,id AS s,n,median,height,scatter,slope,condition,reason FROM surfaces JOIN flight_keys ON surfaces.s=flight_keys.raw;
      CREATE UNIQUE INDEX measured_keys ON measured(x,y,s);
      CREATE TABLE residuals AS SELECT a.x,a.y,a.s AS a,b.s AS b,b.height-a.height AS dz FROM measured a JOIN measured b USING(x,y)
        WHERE a.s<b.s AND a.height IS NOT NULL AND b.height IS NOT NULL;
      CREATE INDEX residual_pairs ON residuals(a,b);''')
    db.commit()
    folder.mkdir()
    _csv(folder/'surface_cells.csv',['cell_east','cell_north','flight','ground_returns','raw_median','qualified_center_height','plane_rms','slope','condition','unavailable_reason'],
         ((int(x)*store.cell+store.cell/2,int(y)*store.cell+store.cell/2,*rest) for x,y,*rest in db.execute('SELECT * FROM measured ORDER BY s,x,y')))
    _csv(folder/'overlap_cells.csv',['a','b','cell_east','cell_north','dz_b_minus_a'],
         ((a,b,(x+.5)*store.cell,(y+.5)*store.cell,dz) for x,y,a,b,dz in db.execute('SELECT * FROM residuals ORDER BY a,b,x,y')))
    flights=[]
    for entry in inventory['strips']:
        _check(cancel)
        s=entry['id'];raw=next(key for key,value in mapping.items() if value==s)
        occupied=db.execute('SELECT count(*) FROM coverage_entries WHERE s=?',(raw,)).fetchone()[0]
        ground,ground_cells,qualified=db.execute('SELECT coalesce(sum(n),0),count(*),coalesce(sum(height IS NOT NULL),0) FROM measured WHERE s=?',(s,)).fetchone()
        reasons=dict(db.execute("SELECT reason,count(*) FROM measured WHERE s=? AND reason!='' GROUP BY reason",(s,)))
        flights.append(dict(entry,ground_returns=int(ground),occupied_cells=occupied,ground_cells=ground_cells,qualified_cells=qualified,
            rejected_cells=reasons,logical_key=[entry['source_id'],os.path.normcase(entry['trajectory_path']) if entry['trajectory_path'] else None],
            map_cells=_sample(db,'SELECT x,y FROM coverage_entries WHERE s=? ORDER BY x,y',occupied,
                              limit=max(30,30000//max(1,len(inventory['strips']))),parameters=(raw,))))
    pairs=[];neighbors={r['id']:set() for r in flights}
    for index,a in enumerate(flights):
        for b in flights[index+1:]:
            _check(cancel)
            ids=(a['id'],b['id'])
            shared=db.execute('SELECT count(*) FROM coverage_entries a JOIN coverage_entries b USING(x,y) WHERE a.s=? AND b.s=?',
                              tuple(next(k for k,v in mapping.items() if v==s) for s in ids)).fetchone()[0]
            ground_shared=db.execute('SELECT count(*) FROM measured a JOIN measured b USING(x,y) WHERE a.s=? AND b.s=?',ids).fetchone()[0]
            stats=_stats(db,'residuals','dz',config['tolerance'],'a=? AND b=?',ids)
            supported=stats['cells']>=config['min_cells']
            if supported:
                neighbors[ids[0]].add(ids[1]);neighbors[ids[1]].add(ids[0])
            finding=('Insufficient qualified overlap' if not supported else
                     'Systematic separation to review' if abs(stats['median'])>config['tolerance'] else
                     'Variable disagreement to review' if stats['rmse']>config['tolerance'] else
                     'No threshold exceedance in supported summary; review coverage')
            pairs.append(dict(a=ids[0],b=ids[1],occupied_shared_cells=shared,ground_shared_cells=ground_shared,
                a_covered_percent=100*shared/a['occupied_cells'] if a['occupied_cells'] else None,
                b_covered_percent=100*shared/b['occupied_cells'] if b['occupied_cells'] else None,
                supported=supported,statistics=stats,finding=finding,
                trend=_trend(db,*ids,store.cell,ft_per_unit) if supported else dict(available=False,reason='Insufficient qualified overlap'),
                map_cells=_sample(db,'SELECT x,y,dz FROM residuals WHERE a=? AND b=? ORDER BY x,y',stats['cells'],limit=max(30,30000//max(1,len(flights)*(len(flights)-1)//2)),parameters=ids)))
    components=[];remaining=set(neighbors)
    while remaining:
        seen=set();pending=[min(remaining)]
        while pending:
            s=pending.pop()
            if s not in seen:seen.add(s);pending.extend(neighbors[s]-seen)
        remaining-=seen;components.append(sorted(seen))
    for row in flights:
        row['supported_neighbors']=sorted(neighbors[row['id']])
    result=dict(inventory=inventory,flights=flights,pairs=pairs,connected_components=components,
                corrections_written=False,absolute_accuracy='Not assessed',
                cell=store.cell,units=data.crs.axis_info[0].unit_name)
    _csv(folder/'flightlines.csv',['flight','las_line_id','trajectory','ground_returns','occupied_cells','ground_cells','qualified_cells','supported_neighbors'],
         ((r['id'],r['source_id'],r['trajectory_path'],r['ground_returns'],r['occupied_cells'],r['ground_cells'],r['qualified_cells'],';'.join(map(str,r['supported_neighbors']))) for r in flights))
    _csv(folder/'pairs.csv',['a','b','occupied_shared_cells','ground_shared_cells','qualified_cells','median','rmse','nmad','p95_abs','exceeding','finding'],
         ((r['a'],r['b'],r['occupied_shared_cells'],r['ground_shared_cells'],r['statistics']['cells'],*[r['statistics'][k] for k in ('median','rmse','nmad','p95_abs','exceeding')],r['finding']) for r in pairs))
    occupied,multiple=db.execute('SELECT count(*),coalesce(sum(n>=2),0) FROM (SELECT count(*) AS n FROM coverage_entries GROUP BY x,y)').fetchone()
    result['occupied_union_cells']=occupied
    result['multiply_occupied_cells']=int(multiple)
    result['coverage_map_cells']=_sample(db,'SELECT x,y,count(*) FROM coverage_entries GROUP BY x,y ORDER BY x,y',occupied,limit=30000)
    _csv(folder/'coverage_cells.csv',['cell_east','cell_north','observed_flight_count'],
         (((x+.5)*store.cell,(y+.5)*store.cell,n) for x,y,n in db.execute('SELECT x,y,count(*) FROM coverage_entries GROUP BY x,y ORDER BY x,y')))
    return result


def _compare(first,second,baseline,candidate,folder,config,cancel):
    db=first.db
    bykey={tuple(r['logical_key']):r['id'] for r in baseline['flights']}
    links=[(r['id'],bykey[tuple(r['logical_key'])]) for r in candidate['flights'] if tuple(r['logical_key']) in bykey]
    if len(links)<2:
        raise ValueError('Candidate comparison needs at least two matching LAS line / trajectory identities')
    db.execute('ATTACH DATABASE ? AS candidate',(str(second.path),))
    db.execute('CREATE TABLE links(candidate INTEGER PRIMARY KEY,baseline INTEGER)')
    db.executemany('INSERT INTO links VALUES(?,?)',links)
    db.executescript('''CREATE TABLE common_cells AS SELECT r.x,r.y,r.a,r.b,r.dz AS before_dz,cb.height-ca.height AS after_dz
       FROM residuals r JOIN links la ON r.a=la.baseline JOIN links lb ON r.b=lb.baseline
       JOIN candidate.measured ca ON ca.x=r.x AND ca.y=r.y AND ca.s=la.candidate
       JOIN candidate.measured cb ON cb.x=r.x AND cb.y=r.y AND cb.s=lb.candidate
       WHERE ca.height IS NOT NULL AND cb.height IS NOT NULL;
       CREATE INDEX common_pairs ON common_cells(a,b);''')
    db.commit()
    rows=[]
    for pair in baseline['pairs']:
        _check(cancel)
        ids=pair['a'],pair['b']
        before=_stats(db,'common_cells','before_dz',config['tolerance'],'a=? AND b=?',ids)
        after=_stats(db,'common_cells','after_dz',config['tolerance'],'a=? AND b=?',ids)
        rows.append(dict(a=ids[0],b=ids[1],before=before,after=after,supported=before['cells']>=config['min_cells']))
    _csv(folder/'common_cells.csv',['cell_east','cell_north','a','b','before_dz_b_minus_a','after_dz_b_minus_a'],
         (((x+.5)*first.cell,(y+.5)*first.cell,a,b,d,e) for x,y,a,b,d,e in db.execute('SELECT * FROM common_cells ORDER BY a,b,x,y')))
    return dict(pairs=rows,flight_links=links,matching='LAS point_source_id plus canonical trajectory path; file-level lineage is operator supplied',
                note='Identical world cells and flight pairs qualified in both datasets; not identical point observations or independent accuracy.')


def run(project,out,*,candidate=None,config=None,log=print,cancel=lambda:False):
    from pyargus import project as projects
    from pyargus.analysis_records import analysis_job,finish,plain
    from pyargus.publication import staging_directory,publish_new
    from pyargus.qa import alignment_report
    from pyargus.job_manifest import identity
    config=settings(config)
    out=projects._target(out)
    crs,headers=projects._cloud_headers(project)
    candidate_headers=[]
    if candidate is not None:
        other_crs,candidate_headers=projects._cloud_headers(candidate)
        if not crs.equals(other_crs):raise ValueError('Baseline and candidate CRS/units differ; diagnostics never reprojects')
    metres=float(crs.axis_info[0].unit_conversion_factor)
    native=dict(config,cell=config['cell_ft']*FT_US/metres,max_scatter=config['max_scatter_ft']*FT_US/metres,tolerance=config['tolerance_ft']*FT_US/metres)
    reporting=alignment_report.settings(project.alignment_reporting)
    locations=[];survey_ids=[]
    for source,checks in [('reference',alignment_report.read_references(reporting)),
                          (reporting['role'],alignment_report.read_checks(reporting))]:
        if checks is None:continue
        survey_ids.append(checks['identity'])
        for name,xyz in zip(checks['ids'],checks['xyz']):
            locations.append(dict(id=name,role=source,easting=float(xyz[0]),northing=float(xyz[1]),survey_z=float(xyz[2])))
    radius=reporting['radius_ft']*FT_US/metres
    references=[r for r in locations if r['role']=='reference']
    for mark in locations:
        if mark['role']=='independent' and any(mark['id']==r['id'] or math.hypot(mark['easting']-r['easting'],mark['northing']-r['northing'])<=radius for r in references):
            mark['role']='role_conflict'
    inputs=[c['path'] for c in headers+candidate_headers]+[t.path for p in (project,candidate) if p is not None for t in p.trajectories]
    stores=[]
    with analysis_job('flightline-diagnostics',out,dict(config=config,baseline=asdict(project),candidate=asdict(candidate) if candidate else None),inputs=inputs,log=log) as record:
        record.data['inputs'].extend(dict(item,role='reference_location_only') for item in survey_ids)
        record.save()
        try:
            with staging_directory(out.parent,prefix='.pyargus-flightlines-') as stage, ExitStack() as stack:
                states=[]
                for name,spec in [('baseline',project)]+([('candidate',candidate)] if candidate is not None else []):
                    _check(cancel)
                    path=stage/('.'+name+'.sqlite')
                    store=Store(path,native['cell'],native,cancel,log=log);store.path=path;stores.append(store)
                    stack.callback(store.db.close)
                    log(name+': streaming original point records into diagnostic scratch')
                    data=projects.load(spec,chunk_sink=store.ingest,cancel=cancel,log=log)
                    if data.tracks and (data.inventory['unmatched'] or data.inventory['ambiguous']):
                        raise ValueError('Diagnostics refused unresolved trajectory matching; resolve it with Inspect / match')
                    log(name+': reducing ground cells and screening local planes')
                    store.reduce()
                    states.append(_dataset(store,data,stage/name,native,metres/FT_US,cancel))
                    state_locations=[]
                    for mark in locations:
                        x,y=math.floor(mark['easting']/store.cell),math.floor(mark['northing']/store.cell)
                        support=[row[0] for row in store.db.execute('SELECT s FROM measured WHERE x=? AND y=? AND height IS NOT NULL ORDER BY s',(x,y))]
                        state_locations.append(dict(mark,qualified_cell_flights=support,
                            assessment='Ground-cell coverage only; target support and survey residual not measured'))
                    states[-1]['reference_locations']=state_locations
                    spec.save(stage/(name+'.project.json'))
                common=_compare(*stores,*states,stage,native,cancel) if len(stores)==2 else None
                result=dict(schema_version=1,created_utc=datetime.now(timezone.utc).isoformat(),config=config,
                    native_settings=native,crs=crs.to_wkt(),states=states,comparison=common,
                    corrections_written=False,limitations=LIMITATIONS,inputs=record.data['inputs'],
                    resources=dict(input_chunk_limit=500000,sqlite_cache_mib_per_dataset=32,
                        maximum_analysis_flights=128,scratch_database_bytes=[st.path.stat().st_size for st in stores],
                        note='Chunked input and disk-backed reductions; this is not a measured whole-process RSS bound.'),
                    method='Class-2 OLS planes at world-aligned half-open cell centers; four-quadrant support, rank/condition, scatter and slope gates. Positive dZ means B above A.')
                from pyargus.qa.flightline_report import write
                write(stage,result)
                (stage/'diagnostics.json').write_text(json.dumps(plain(result),indent=2,allow_nan=False),encoding='utf-8')
                for c in headers+candidate_headers:projects._unchanged(c)
                for item in record.data['inputs']:
                    expected={k:v for k,v in item.items() if k!='role'}
                    if identity(item['path'],hash_content='sha256' in expected)!=expected:
                        raise ValueError('Diagnostic input changed: '+item['path'])
                _check(cancel)
                for store in stores:store.db.close()
                for store in stores:store.path.unlink()
                publish_new(stage,out)
            products=[p for p in out.rglob('*') if p.is_file()]
            finish(record,dict(corrections_written=False,flights=len(states[0]['flights']),pairs=len(states[0]['pairs']),absolute_accuracy='Not assessed'),outputs=products)
            log('Flightline diagnostics: '+str(out/'report.html'))
            return dict(result,report=str(out/'report.html'))
        except sqlite3.OperationalError:
            _check(cancel)
            raise
        finally:
            for store in stores:
                try:store.db.close()
                except sqlite3.Error:pass
