"""Measured XY-cell coverage overlap, distinct from planned flight sidelap.

A cell belongs to a strip when at least one return other than known noise
(classes 7/18) lands there. Cells are world aligned and half open, using floor
for both signs. SQLite merges chunks/tiles before counting shared coverage.
"""
import csv
import html
import itertools
import math
from pathlib import Path
import sqlite3
import tempfile
import numpy as np
from pyargus.qa import raster

EXCLUDED_CLASSES=(7,18)
COLORS=np.array([[0,0,0,0],[58,139,196,255],[239,168,54,255],[140,89,166,255]],dtype=np.uint8)


def check(cancel):
    if cancel():
        from pyargus.project import Cancelled
        raise Cancelled('coverage reporting cancelled')


def create(db):
    db.execute('CREATE TABLE coverage_entries(x INTEGER,y INTEGER,s INTEGER,n INTEGER,PRIMARY KEY(x,y,s)) WITHOUT ROWID')


def ingest(db,x,y,classification,strip_ids,cell=3.):
    if not np.isfinite(cell) or cell<=0:raise ValueError('Coverage cell size must be finite and positive')
    x,y,classification,strip_ids=(np.asarray(v) for v in (x,y,classification,strip_ids))
    if any(v.ndim!=1 for v in (x,y,classification,strip_ids)) or len({len(v) for v in (x,y,classification,strip_ids)})!=1:
        raise ValueError('Coverage requires matching one-dimensional point fields')
    if not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('Coverage coordinates must be finite')
    keep=~np.isin(classification,EXCLUDED_CLASSES)
    if not keep.any():return 0,int(len(x))
    raw=np.floor(np.column_stack((x[keep],y[keep]))/cell)
    if ((raw < -2.**63)|(raw >= 2.**63)).any():raise ValueError('Coverage cell indices exceed the integer range')
    keys=strip_ids[keep]
    if not np.issubdtype(keys.dtype,np.integer):
        if not np.isfinite(keys).all() or (keys!=np.floor(keys)).any():raise ValueError('Coverage strip IDs must be integers')
    rows=np.column_stack((raw.astype(np.int64),keys.astype(np.int64)))
    unique,counts=np.unique(rows,axis=0,return_counts=True)
    db.executemany('INSERT INTO coverage_entries VALUES(?,?,?,?) ON CONFLICT(x,y,s) DO UPDATE SET n=n+excluded.n',
                   zip(unique[:,0].tolist(),unique[:,1].tolist(),unique[:,2].tolist(),counts.tolist()))
    return int(keep.sum()),int((~keep).sum())


def rgba(grid):
    return COLORS[np.minimum(raster.grid_to_image(grid).astype(np.uint64),3).astype(np.uint8)]


def _percent(part,total):return 100.*part/total if total else None


def write(db,out,mapping,*,cell=3.,units='map units',excluded_returns=0,cancel=lambda:False,crs=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);check(cancel)
    if not np.isfinite(cell) or cell<=0:raise ValueError('Coverage cell size must be finite and positive')
    mapping={int(k):int(v) for k,v in mapping.items()}
    if len(set(mapping.values()))!=len(mapping):raise ValueError('Coverage analysis IDs must be distinct')
    totals={s:(int(n),int(c)) for s,n,c in db.execute('SELECT s,sum(n),count(*) FROM coverage_entries GROUP BY s')}
    if not set(totals)<=set(mapping):raise ValueError('Coverage contains an unmapped strip')
    shared={(int(a),int(b)):int(n) for a,b,n in db.execute('SELECT a.s,b.s,count(*) FROM coverage_entries a JOIN coverage_entries b ON a.x=b.x AND a.y=b.y AND a.s<b.s GROUP BY a.s,b.s')}
    multi={s:int(n) for s,n in db.execute('SELECT s,count(*) FROM coverage_entries WHERE (x,y) IN (SELECT x,y FROM coverage_entries GROUP BY x,y HAVING count(*)>1) GROUP BY s')}
    bounds=db.execute('SELECT min(x),max(x),min(y),max(y) FROM coverage_entries').fetchone()
    rows_by_strip=[];pairs=[]
    for key in sorted(mapping,key=mapping.get):
        returns,count=totals.get(key,(0,0))
        neighbors=sorted(mapping[b if a==key else a] for (a,b),n in shared.items() if n and key in (a,b))
        rows_by_strip.append(dict(strip=mapping[key],eligible_returns=returns,covered_cells=count,area_square_units=count*cell*cell,
            shared_with_any_cells=multi.get(key,0),shared_with_any_percent=_percent(multi.get(key,0),count),neighbors=neighbors,
            status='No eligible coverage' if not count else 'Isolated coverage' if not neighbors else 'Shared coverage'))
    for a,b in itertools.combinations(sorted(mapping,key=mapping.get),2):
        count=shared.get((min(a,b),max(a,b)),0);ca=totals.get(a,(0,0))[1];cb=totals.get(b,(0,0))[1]
        pairs.append(dict(a=mapping[a],b=mapping[b],shared_cells=count,shared_area_square_units=count*cell*cell,
            a_covered_by_b_percent=_percent(count,ca),b_covered_by_a_percent=_percent(count,cb),
            shared_over_union_percent=_percent(count,ca+cb-count)))
    union=0;multi_union=0;histogram={};tiles=[];step=None
    if bounds[0] is None:
        overview=np.zeros((1,1),dtype=np.uint32)
    else:
        x0,x1,y0,y1=bounds;step=max(1,math.ceil(max(x1-x0+1,y1-y0+1)/1024))
        overview=np.zeros((math.ceil((x1-x0+1)/step),math.ceil((y1-y0+1)/step)),dtype=np.uint32)
        raster.write_world_file(out/'coverage.pgw',(x0+np.arange(overview.shape[0]+1)*step)*cell,(y0+np.arange(overview.shape[1]+1)*step)*cell)
        if crs is not None:(out/'coverage.prj').write_text(crs.to_wkt()+'\n',encoding='utf-8')
    with (out/'coverage_cells.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['x_min','y_min','strip_count','analysis_ids'])
        for i,(x,y,n,ids) in enumerate(db.execute('SELECT x,y,count(*),group_concat(s) FROM coverage_entries GROUP BY x,y ORDER BY x,y')):
            if i%10000==0:check(cancel)
            union+=1;multi_union+=int(n>=2);histogram[str(n)]=histogram.get(str(n),0)+1
            writer.writerow([x*cell,y*cell,n,';'.join(str(mapping[k]) for k in sorted((int(v) for v in ids.split(',')),key=mapping.get))])
            ix,iy=(x-x0)//step,(y-y0)//step
            old=int(overview[ix,iy]);overview[ix,iy]=n if not old else min(old,n)
    raster.write_png(out/'coverage.png',rgba(overview))
    if union:
        folder=out/'tiles';folder.mkdir(exist_ok=True);current=None;grid=None
        def flush():
            if current is None:return
            tx,ty=current;name=f'coverage_{tx}_{ty}'
            raster.write_png(folder/(name+'.png'),rgba(grid))
            raster.write_world_file(folder/(name+'.pgw'),np.arange(tx*256,tx*256+257)*cell,np.arange(ty*256,ty*256+257)*cell)
            tiles.append('tiles/'+name+'.png')
        # Integer division in SQL truncates negatives; explicitly implement floor.
        tx='CASE WHEN x<0 THEN (x-255)/256 ELSE x/256 END';ty='CASE WHEN y<0 THEN (y-255)/256 ELSE y/256 END'
        for i,(x,y,n,xt,yt) in enumerate(db.execute(f'SELECT x,y,count(*),{tx},{ty} FROM coverage_entries GROUP BY x,y ORDER BY {tx},{ty},x,y')):
            if i%10000==0:check(cancel)
            key=(xt,yt)
            if key!=current:flush();current=key;grid=np.zeros((256,256),dtype=np.uint32)
            grid[x-xt*256,y-yt*256]=n
        flush()
    with (out/'coverage_pairs.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['a','b','shared_cells','shared_area_square_units','a_covered_by_b_percent','b_covered_by_a_percent','shared_over_union_percent']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(pairs)
    with (out/'coverage_strips.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['strip','eligible_returns','covered_cells','area_square_units','shared_with_any_cells','shared_with_any_percent','status']
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows_by_strip)
    return dict(method='Measured occupied XY-cell coverage; not planned cross-track sidelap',cell=cell,units=units,
        grid_convention='World-aligned half-open cells; floor coordinates, including negative and maximum edges',
        excluded_classes=list(EXCLUDED_CLASSES),excluded_returns=int(excluded_returns),eligible_returns=sum(t[0] for t in totals.values()),
        union_cells=union,union_area_square_units=union*cell*cell,multiple_strip_cells=multi_union,
        multiple_strip_percent_of_union=_percent(multi_union,union),multiplicity_cells=histogram,strips=rows_by_strip,pairs=pairs,
        overview_cell=None if step is None else cell*step,overview_rule='Minimum strip count among occupied fine cells per overview pixel; empty fine cells are ignored',
        tiles=tiles,limitations='Resolution-dependent observed returns, not swath width, planned sidelap, surveyed boundary or accuracy approval; unclassified outliers and occlusions can affect coverage')


def generate(points,out,*,cell=3.,units='map units',cancel=lambda:False):
    keys=np.unique(points['point_source_id']);mapping={int(k):int(k) for k in keys};excluded=0
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.coverage-',dir=out) as temp:
        db=sqlite3.connect(Path(temp)/'cells.sqlite')
        try:
            db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-32768')
            db.set_progress_handler(lambda:int(cancel()),10000);create(db)
            for start in range(0,len(points['x']),500_000):
                check(cancel);stop=start+500_000
                _,n=ingest(db,points['x'][start:stop],points['y'][start:stop],points['classification'][start:stop],points['point_source_id'][start:stop],cell)
                excluded+=n;db.commit()
            return write(db,out,mapping,cell=cell,units=units,excluded_returns=excluded,cancel=cancel)
        finally:db.close()


def html_section(summary,*,image_src='coverage.png',links=True):
    esc=html.escape
    def pct(value):return '—' if value is None else f'{value:.1f}%'
    rows=['<h2>Measured coverage overlap</h2>',
        f'<p>At least one return per {summary["cell"]:g} {esc(summary["units"])} XY cell. Known noise classes 7 and 18 are excluded ({summary["excluded_returns"]:,} returns). These percentages measure occupied coverage; planned flight sidelap is not inferred.</p>',
        '<p>% A covered by B = shared cells / A cells; % B covered by A = shared cells / B cells. Pair union % = shared / (A + B − shared). Multi-strip % counts each cell once, even when three or more strips cover it. Ground dZ below uses its own class-2 and minimum-return requirements.</p>',
        f'<p><b>{summary["union_cells"]:,} occupied cells; {summary["multiple_strip_cells"]:,} covered by multiple strips ({pct(summary["multiple_strip_percent_of_union"])} of the observed union).</b></p>',
        '<table><tr><th>Strip A</th><th>Strip B</th><th>Shared cells</th><th>% A covered by B</th><th>% B covered by A</th><th>Pair union %</th></tr>']
    for p in summary['pairs']:
        rows.append(f'<tr><td>{p["a"]}</td><td>{p["b"]}</td><td>{p["shared_cells"]:,}</td><td>{pct(p["a_covered_by_b_percent"])}</td><td>{pct(p["b_covered_by_a_percent"])}</td><td>{pct(p["shared_over_union_percent"])}</td></tr>')
    rows.append('</table><table><tr><th>Strip</th><th>Occupied cells</th><th>% shared with any strip</th><th>Coverage status</th></tr>')
    for s in summary['strips']:rows.append(f'<tr><td>{s["strip"]}</td><td>{s["covered_cells"]:,}</td><td>{pct(s["shared_with_any_percent"])}</td><td>{esc(s["status"])}</td></tr>')
    rows.append('</table>')
    if not summary['union_cells']:rows.append('<p>No eligible coverage. Overlap percentages are not computed.</p>')
    elif len(summary['strips'])<2:rows.append('<p>Only one analysis strip; there is no strip pair to compare.</p>')
    rows.extend([f'<img src="{esc(image_src,quote=True)}" alt="Measured strip coverage map">',
        '<p>North up. Blue: one strip; amber: two; purple: three or more. Transparent: no eligible return observed, which may be outside the survey boundary or a data void.</p>',
        f'<p>Overview pixel: {summary["overview_cell"] or summary["cell"]:g} units. Coarse pixels show the minimum count among occupied fine cells; exact cell counts and full-resolution tiles are available. {esc(summary["limitations"])}</p>'])
    if links:rows.append('<p><a href="coverage_pairs.csv">Pair percentages CSV</a> · <a href="coverage_strips.csv">Strip coverage CSV</a> · <a href="coverage_cells.csv">Exact coverage cells CSV</a></p>')
    return '\n'.join(rows)
