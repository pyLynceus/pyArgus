"""Disk-backed exact cell statistics. Memory scales with input chunks, not clouds.

All sources share half-open world-aligned cells. Tiles are render partitions,
never independent estimates: a cell receives every contributing strip first.
SQLite external sorts retain exact medians even for a very dense single cell.
"""
import csv
import html
import json
import math
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

import numpy as np


def percentile(db, table, column, q, where='1', params=()):
    n = db.execute(f'SELECT count(*) FROM {table} WHERE {where}',params).fetchone()[0]
    if not n: return None
    rank=(n-1)*q; low=math.floor(rank)
    rows=db.execute(f'SELECT {column} FROM {table} WHERE {where} ORDER BY {column} LIMIT 2 OFFSET ?',(*params,low)).fetchall()
    a=float(rows[0][0]); b=float(rows[-1][0])
    return a+(b-a)*(rank-low)


class Store:
    def __init__(self,path,cancel,log,control=None):
        if control is not None:
            ids,x,y,z=control
            if not (len(ids)==len(x)==len(y)==len(z)) or not np.isfinite(np.column_stack((x,y,z))).all():
                raise ValueError('Control requires matching IDs and finite XYZ arrays.')
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=OFF')
        self.db.execute('PRAGMA synchronous=OFF')
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('PRAGMA cache_size=-32768')
        self.db.set_progress_handler(lambda:int(cancel()),10000)
        self.db.executescript('''
            CREATE TABLE density(x INTEGER,y INTEGER,n INTEGER,PRIMARY KEY(x,y)) WITHOUT ROWID;
            CREATE TABLE ground(x INTEGER,y INTEGER,s INTEGER,z REAL);
            CREATE TABLE marks(k INTEGER,z REAL);
        ''')
        self.cancel,self.log,self.control=cancel,log,control
        self.points=0; self.ground=0; self.ground_counts={}; self.last_log=0
        self.extent={k:[math.inf,-math.inf] for k in ('x','y','z')}

    def ingest(self,p,chosen):
        from pyargus.project import _check_cancel
        _check_cancel(self.cancel)
        self.points+=len(chosen)
        for name in self.extent:
            self.extent[name][0]=min(self.extent[name][0],float(p[name].min()))
            self.extent[name][1]=max(self.extent[name][1],float(p[name].max()))
        cells=np.floor(np.column_stack((p['x'],p['y']))/3).astype(np.int64)
        unique,counts=np.unique(cells,axis=0,return_counts=True)
        self.db.executemany('INSERT INTO density VALUES(?,?,?) ON CONFLICT(x,y) DO UPDATE SET n=n+excluded.n',
                            zip(unique[:,0].tolist(),unique[:,1].tolist(),counts.tolist()))
        keep=p['classification']==2
        self.ground+=int(keep.sum())
        keys=(chosen[keep].astype(np.int64)+2)*65536+p['point_source_id'][keep].astype(np.int64)
        for key,n in zip(*np.unique(keys,return_counts=True)):
            self.ground_counts[int(key)]=self.ground_counts.get(int(key),0)+int(n)
        cells=np.floor(np.column_stack((p['x'][keep],p['y'][keep]))/6).astype(np.int64)
        self.db.executemany('INSERT INTO ground VALUES(?,?,?,?)',
            zip(cells[:,0].tolist(),cells[:,1].tolist(),keys.tolist(),p['z'][keep].tolist()))
        if self.control is not None:
            ids,cx,cy,cz=self.control
            gx,gy,gz=(p[n][keep] for n in ('x','y','z'))
            for k in range(len(ids)):
                near=(gx-cx[k])**2+(gy-cy[k])**2<=9.
                self.db.executemany('INSERT INTO marks VALUES(?,?)',((k,float(z)) for z in gz[near]))
        self.db.commit()
        if time.monotonic()-self.last_log>5:
            self.log(f'QA scratch: {self.points:,} returns counted; {self.ground:,} ground returns stored')
            self.last_log=time.monotonic()

    def reduce(self):
        self.log('Computing exact ground-cell medians on disk; Stop remains available')
        self.db.executescript('''
            CREATE INDEX ground_order ON ground(x,y,s,z);
            CREATE TABLE medians AS
            SELECT x,y,s,avg(z) AS z,max(n) AS n FROM (
              SELECT x,y,s,z,row_number() OVER (PARTITION BY x,y,s ORDER BY z) AS r,
                count(*) OVER (PARTITION BY x,y,s) AS n FROM ground
            ) WHERE n>=3 AND r IN ((n+1)/2,(n+2)/2) GROUP BY x,y,s;
            CREATE UNIQUE INDEX median_cell ON medians(x,y,s);
            CREATE TABLE dz AS SELECT a.x,a.y,a.s AS a,b.s AS b,b.z-a.z AS dz,
                abs(b.z-a.z) AS absdz FROM medians a JOIN medians b
                ON a.x=b.x AND a.y=b.y AND a.s<b.s;
            CREATE INDEX dz_pairs ON dz(a,b);
        ''')
        self.db.commit()


def render_tiles(db,table,value,cell,out,prefix,*,where='1',params=(),diverging=False,cancel=lambda:False):
    from pyargus.qa import raster
    from pyargus.project import _check_cancel
    # floor division is explicit: SQLite integer division truncates negative coordinates.
    tx='(CASE WHEN x<0 THEN (x-255)/256 ELSE x/256 END)'; ty='(CASE WHEN y<0 THEN (y-255)/256 ELSE y/256 END)'
    # SQL sort spills to disk; only one 256x256 image is materialized at a time.
    cursor=db.execute(f'SELECT x,y,{value},{tx},{ty} FROM {table} WHERE {where} ORDER BY {tx},{ty}',params)
    folder=out/'tiles'; folder.mkdir(exist_ok=True)
    current=None; grid=None; links=[]
    def flush():
        if current is None: return
        ix,iy=current; name=f'{prefix}_{ix}_{iy}'
        rgba=raster.diverging_rgba(grid,.25) if diverging else raster.sequential_rgba(grid)
        raster.write_png(folder/f'{name}.png',rgba)
        raster.write_world_file(folder/f'{name}.pgw',np.arange(ix*256,ix*256+257)*cell,np.arange(iy*256,iy*256+257)*cell)
        links.append(f'tiles/{name}.png')
    for i,(x,y,v,ix,iy) in enumerate(cursor):
        if i%10000==0: _check_cancel(cancel)
        key=ix,iy
        if key!=current:
            flush(); current=key; grid=np.full((256,256),np.nan) if diverging else np.zeros((256,256))
        grid[x-ix*256,y-iy*256]=v
    flush()
    return links


def write_report(store,data,out,cancel,log):
    from pyargus.qa import raster,checkpoints
    from pyargus.project import _check_cancel
    db=store.db; inv=data.inventory
    mapping={(s['trajectory']+2)*65536+s['source_id']:s['id'] for s in inv['strips']}
    summary=dict(title='pyArgus large-project QA',points=inv['points'],ground_points=store.ground,
        units=data.crs.axis_info[0].unit_name,extent=store.extent,mode='disk-backed',
        grid_convention='World-aligned half-open cells; x/y exactly on an edge belong to the next cell.',
        strips=[dict(strip=s['id'],points=s['points'],ground=store.ground_counts.get((s['trajectory']+2)*65536+s['source_id'],0)) for s in inv['strips']])
    log('Writing project density and per-strip overlap maps')
    density=dict(cell=3,covered_cells=db.execute('SELECT count(*) FROM density').fetchone()[0])
    for name,q in [('median',.5),('p5',.05),('p95',.95)]: density[name]=percentile(db,'density','n',q)/9
    summary['density']=density
    bounds=db.execute('SELECT min(x),max(x),min(y),max(y) FROM density').fetchone()
    x0,x1,y0,y1=bounds
    density['cells']=(x1-x0+1)*(y1-y0+1)
    step=max(1,math.ceil(max(x1-x0+1,y1-y0+1)/1024))
    overview=np.zeros((math.ceil((x1-x0+1)/step),math.ceil((y1-y0+1)/step)))
    for i,(x,y,n) in enumerate(db.execute('SELECT x,y,n FROM density')):
        if i%10000==0: _check_cancel(cancel)
        overview[(x-x0)//step,(y-y0)//step]+=n
    overview/=9*step*step
    raster.write_png(out/'density.png',raster.sequential_rgba(overview))
    raster.write_world_file(out/'density.pgw',(x0+np.arange(overview.shape[0]+1)*step)*3,(y0+np.arange(overview.shape[1]+1)*step)*3)
    density['overview_cell']=3*step
    tiles={'density':render_tiles(db,'density','n/9.0',3,out,'density',cancel=cancel)}
    pairs=[]
    for a,b,n,mean_square in db.execute('SELECT a,b,count(*),avg(dz*dz) FROM dz GROUP BY a,b'):
        _check_cancel(cancel); aid,bid=mapping[a],mapping[b]
        stats=dict(a=aid,b=bid,cells=n,median=percentile(db,'dz','dz',.5,'a=? AND b=?',(a,b)),
            rmse=math.sqrt(mean_square),p95_abs=percentile(db,'dz','absdz',.95,'a=? AND b=?',(a,b)))
        pairs.append(stats)
        log(f'Overlap strips {aid}/{bid}: {n:,} cells; median dZ {stats["median"]:.4f}')
        tiles[f'dz_{aid}-{bid}']=render_tiles(db,'dz','dz',6,out,f'dz_{aid}-{bid}',where='a=? AND b=?',params=(a,b),diverging=True,cancel=cancel)
    summary['strip_dz']=pairs
    for filename,query in [('density_cells.csv','SELECT x*3,y*3,n,n/9.0 FROM density ORDER BY x,y'),
                            ('strip_dz_cells.csv','SELECT x*6,y*6,a,b,dz FROM dz ORDER BY a,b,x,y')]:
        with (out/filename).open('w',newline='') as f:
            writer=csv.writer(f); writer.writerow(['x_min','y_min','count','points_per_square_unit'] if filename.startswith('density') else ['x_min','y_min','strip_a','strip_b','dz_b_minus_a'])
            for i,row in enumerate(db.execute(query)):
                if i%10000==0: _check_cancel(cancel)
                if filename.startswith('strip'): row=(*row[:2],mapping[row[2]],mapping[row[3]],row[4])
                writer.writerow(row)
    if store.control is not None:
        ids,cx,cy,cz=store.control; residuals={}; skipped={}
        for k,name in enumerate(ids):
            n=db.execute('SELECT count(*) FROM marks WHERE k=?',(k,)).fetchone()[0]
            if n<5: skipped[str(name)]=f'{n} neighbors (need 5)'
            else: residuals[str(name)]=percentile(db,'marks','z',.5,'k=?',(k,))-float(cz[k])
        control=dict(residuals=residuals,skipped=skipped,radius=3.,min_neighbours=5)
        values=np.array(list(residuals.values()))
        if len(values):
            control.update(checkpoints.robust_summary(values)); acc=checkpoints.asprs_vertical(values)
            control.update(mean=acc.mean,rmse_z=acc.rmse_z,nva=acc.nva)
        summary['control']=control
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (out/'inventory.json').write_text(json.dumps(inv,indent=2),encoding='utf-8')
    (out/'tiles.json').write_text(json.dumps(tiles,indent=2),encoding='utf-8')
    esc=html.escape
    rows=['<!doctype html><meta charset="utf-8"><title>pyArgus large-project QA</title>',
        '<style>body{font:16px Segoe UI,sans-serif;max-width:1050px;margin:32px auto;padding:20px;background:#f4f6f4;color:#20302a}table{border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ccc}img{max-width:100%}summary{cursor:pointer}</style>',
        '<h1>Large-project QA</h1>',f'<p>{inv["points"]:,} points · {store.ground:,} class-2 ground · {len(inv["strips"])} strips · {esc(summary["units"])}</p>',
        f'<p>Trajectory matches: {inv["matched"]:,}; unmatched: {inv["unmatched"]:,}; ambiguous: {inv["ambiguous"]:,}.</p>' if data.tracks else '<p>No trajectories supplied; strip identity follows the confirmed shared LAS IDs.</p>',
        '<p>All points contribute; no sampling. Density uses 3-unit cells. Ground dZ uses exact medians in 6-unit cells, with at least 3 returns from each strip. Positive dZ means strip B is higher. Raw medians also reflect slope and surface texture; they are not an absolute accuracy test.</p>',
        '<p>Cells are aligned to world-coordinate multiples and are half-open, including the last boundary. This differs from the legacy report at points exactly on its maximum grid edge. Tiles partition completed cells, so file/tile edges cannot split statistics. No neighbor buffer is needed for these cell-local measures.</p>',
        '<h2>Density</h2>',f'<p>Median {density["median"]:.3f}; p5 {density["p5"]:.3f}; p95 {density["p95"]:.3f} points per square unit across {density["covered_cells"]:,} occupied cells.</p>',
        f'<p>Overview pixel: {3*step:g} units. Full-resolution maps and exact cell values are linked below.</p><img src="density.png" alt="Project density overview">',
        '<h2>Ground strip differences</h2><table><tr><th>A</th><th>B</th><th>Cells</th><th>Median dZ</th><th>RMSE</th><th>p95 |dZ|</th></tr>']
    for p in pairs: rows.append(f'<tr><td>{p["a"]}</td><td>{p["b"]}</td><td>{p["cells"]:,}</td><td>{p["median"]:.4f}</td><td>{p["rmse"]:.4f}</td><td>{p["p95_abs"]:.4f}</td></tr>')
    rows.append('</table>')
    if not pairs: rows.append('<p>No cells meet the two-strip ground coverage threshold. This is not evidence of good alignment.</p>')
    if store.control is None: rows.append('<p>No checkpoints supplied; absolute vertical accuracy has not been evaluated.</p>')
    else:
        rows.append('<h2>Checkpoints: local median lidar minus control</h2><p>3-unit radius, minimum 5 ground returns. Per-strip plane decomposition is not included in this report.</p><table>')
        for name,dz in summary['control']['residuals'].items(): rows.append(f'<tr><td>{esc(name)}</td><td>{dz:.4f}</td></tr>')
        for name,why in summary['control']['skipped'].items(): rows.append(f'<tr><td>{esc(name)}</td><td>Skipped: {esc(why)}</td></tr>')
        rows.append('</table>')
    rows.append('<h2>Files and strip identities</h2><table><tr><th>Analysis ID</th><th>LAS ID</th><th>Trajectory</th><th>Ground points</th></tr>')
    for s in inv['strips']:
        key=(s['trajectory']+2)*65536+s['source_id']
        rows.append(f'<tr><td>{s["id"]}</td><td>{s["source_id"]}</td><td>{esc(s["trajectory_path"] or "none")}</td><td>{store.ground_counts.get(key,0):,}</td></tr>')
    rows.append('</table><h2>Full-resolution tiles and cell data</h2><p>dZ tiles: blue below, red above, scale ±0.25 map units. Each PNG has a matching .pgw world file. Use the recorded project CRS in GIS. Density tile colors scale independently; use cell CSV values for quantitative comparisons.</p>')
    for name,links in tiles.items():
        rows.append(f'<details><summary>{esc(name)} — {len(links)} tiles</summary>')
        rows.extend(f'<a href="{esc(link)}">{esc(Path(link).stem)}</a><br>' for link in links)
        rows.append('</details>')
    for name in ('density_cells.csv','strip_dz_cells.csv','summary.json','inventory.json','project.json','tiles.json'):
        rows.append(f'<p><a href="{name}">{name}</a></p>')
    (out/'report.html').write_text('\n'.join(rows),encoding='utf-8')
    return summary


def qa(project,out,*,control=None,log=lambda s:None,cancel=lambda:False):
    from pyargus import project as core
    out=core._target(out)
    _,headers=core._cloud_headers(project)
    total=sum(h['points'] for h in headers)
    estimate=total*160+64*1024**2
    available=shutil.disk_usage(out.parent).free
    if available<estimate:
        raise ValueError(f'Large QA needs scratch disk space: conservatively allow {estimate/1024**3:.1f} GiB; output drive has {available/1024**3:.1f} GiB free. Choose an output folder on a larger drive.')
    log(f'Large-project QA: streaming {total:,} points; scratch allowance {estimate/1024**3:.1f} GiB. No full-cloud arrays.')
    # Scratch is separate from publishable output. Windows closes SQLite before cleanup.
    with tempfile.TemporaryDirectory(prefix='.pyargus-large-qa-',dir=out.parent) as temp:
        temp=Path(temp); result_dir=temp/'result'; result_dir.mkdir()
        store=None
        try:
            store=Store(temp/'scratch.sqlite',cancel,log,control)
            data=core.load(project,keep_points=False,log=log,cancel=cancel,chunk_sink=store.ingest)
            if data.tracks and (data.inventory['unmatched'] or data.inventory['ambiguous']):
                raise ValueError('Project QA refused: unresolved trajectory matches. Run Inspect / match and resolve them first.')
            for t in data.tracks:
                p=Path(t.input.path)
                if t.signature!=(p.stat().st_size,p.stat().st_mtime_ns): raise ValueError('Trajectory changed during QA')
            store.reduce()
            result=write_report(store,data,result_dir,cancel,log)
            for c in data.inventory['clouds']: core._unchanged(c)
            for t in data.tracks:
                p=Path(t.input.path)
                if t.signature!=(p.stat().st_size,p.stat().st_mtime_ns): raise ValueError('Trajectory changed during QA')
            project.save(result_dir/'project.json')
            core._check_cancel(cancel)
            store.db.close(); store=None
            result_dir.rename(out)
        except sqlite3.OperationalError as exc:
            core._check_cancel(cancel)
            raise ValueError(f'Disk-backed QA failed: {exc}. Check free space on the output and system temporary drives.') from exc
        finally:
            if store is not None: store.db.close()
    result['report']=str(out/'report.html')
    log(f'Project QA finished: {out/"report.html"}')
    return result
