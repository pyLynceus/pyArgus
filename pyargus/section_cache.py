"""Local spatial cache for optional, read-only section acceleration.
Caches derived attributes only; no point is modified. Source-order sampling
matches sections.extract_section when both use the cache's chunk size.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import numpy as np
from pyargus.job_manifest import identity
from pyargus.sections import Section, section_coordinates

DTYPE=np.dtype([('x','<f8'),('y','<f8'),('z','<f8'),('classification','u1'),('line','<u2'),('index','<i8')])


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError('Cache operation cancelled')


def fingerprint(path):
    s=Path(path).stat()
    return [s.st_size,s.st_mtime_ns]


def build(source,target,*,cell=50.,chunk_size=250000,cancel=None,progress=lambda text:None):
    import laspy
    source=Path(source).resolve();target=Path(target).resolve()
    if target.exists():raise FileExistsError(target)
    if not np.isfinite(cell) or cell<=0 or chunk_size<1:raise ValueError('Positive cell/chunk size required')
    before=identity(source);check_cancel(cancel)
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.section-cache-',dir=target.parent) as temp:
        stage=Path(temp)/'cache';stage.mkdir()
        with laspy.open(source) as reader:
            crs=reader.header.parse_crs()
            if crs is None or not crs.is_projected:raise ValueError('Projected CRS required')
            factors=[a.unit_conversion_factor for a in crs.axis_info]
            if not np.allclose(factors,factors[0],rtol=1e-12,atol=0):raise ValueError('Matching XYZ units required')
            meta=dict(schema_version=2,source=before,cell=float(cell),chunk_size=int(chunk_size),crs=crs.to_wkt(),source_points=int(reader.header.point_count),chunks=[])
            offset=0
            for number,points in enumerate(reader.chunk_iterator(chunk_size)):
                check_cancel(cancel)
                xyz=np.column_stack([points.x,points.y,points.z]);valid=np.isfinite(xyz).all(axis=1)
                rows=np.empty(int(valid.sum()),dtype=DTYPE)
                for axis,col in enumerate(('x','y','z')):rows[col]=xyz[valid,axis]
                rows['classification']=np.asarray(points.classification)[valid]
                rows['line']=np.asarray(points.point_source_id)[valid]
                rows['index']=np.flatnonzero(valid)+offset
                xy=np.floor(xyz[valid,:2]/cell)
                if np.any(np.abs(xy)>=np.iinfo(np.int64).max):raise ValueError('Cell coordinates exceed int64')
                xy=xy.astype(np.int64);order=np.lexsort((xy[:,1],xy[:,0]));rows=rows[order];xy=xy[order]
                starts=np.r_[0,1+np.flatnonzero(np.any(xy[1:]!=xy[:-1],axis=1))] if len(rows) else np.empty(0,dtype=int)
                stops=np.r_[starts[1:],len(rows)] if len(rows) else np.empty(0,dtype=int)
                blocks=[[int(xy[a,0]),int(xy[a,1]),int(a),int(b)] for a,b in zip(starts,stops)]
                filename=f'chunk_{number:06d}.npy';np.save(stage/filename,rows,allow_pickle=False)
                meta['chunks'].append(dict(file=filename,identity=fingerprint(stage/filename),rows=len(rows),blocks=blocks))
                offset+=len(points)
                progress(f"Caching {source.name}: {offset:,}/{meta['source_points']:,} points")
            if offset!=meta['source_points']:raise ValueError('Source point count mismatch')
        check_cancel(cancel)
        if before!=identity(source):raise ValueError('Source changed during cache build')
        (stage/'manifest.json').write_text(json.dumps(meta,separators=(',',':')),encoding='utf-8')
        (stage/'manifest.sha256').write_text(hashlib.sha256((stage/'manifest.json').read_bytes()).hexdigest(),encoding='ascii')
        check_cancel(cancel)
        stage.rename(target)
    return meta


def load(cache):
    cache=Path(cache).resolve()
    raw=(cache/'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=(cache/'manifest.sha256').read_text(encoding='ascii').strip():raise ValueError('Cache manifest changed')
    m=json.loads(raw)
    if m.get('schema_version')!=2:raise ValueError('Unsupported cache schema')
    if identity(m['source']['path'])!=m['source']:raise ValueError('Stale cache: source changed')
    for i,chunk in enumerate(m['chunks']):
        if chunk['file']!=f'chunk_{i:06d}.npy':raise ValueError('Invalid cache chunk name')
        if fingerprint(cache/chunk['file'])!=chunk['identity']:raise ValueError('Cache chunk changed')
    return m


def query_blocks(m,chunk,start,end,width):
    a,b=np.asarray(start),np.asarray(end);delta=b-a;side=np.array([-delta[1],delta[0]])/np.linalg.norm(delta)*width/2
    corners=np.array([a+side,a-side,b+side,b-side]);low=corners.min(axis=0);high=corners.max(axis=0)
    lower=np.floor(low/m["cell"]).astype(np.int64)-1;upper=np.floor(high/m["cell"]).astype(np.int64)+1
    grid=np.asarray(chunk['blocks'],dtype=np.int64).reshape(-1,4)
    ux,uy=delta/np.linalg.norm(delta)
    dx=(grid[:,0]+.5)*m['cell']-a[0];dy=(grid[:,1]+.5)*m['cell']-a[1]
    station_mid=dx*ux+dy*uy;across_mid=-dx*uy+dy*ux
    reach=.5*m['cell']*(abs(ux)+abs(uy))
    tolerance=np.finfo(float).eps*32*max(1.,float(np.abs(corners).max()),m['cell'])
    keep_blocks=(grid[:,0]>=lower[0])&(grid[:,0]<=upper[0])&(grid[:,1]>=lower[1])&(grid[:,1]<=upper[1])
    keep_blocks &= (station_mid>=-reach-tolerance)&(station_mid<=np.linalg.norm(delta)+reach+tolerance)&(np.abs(across_mid)<=width/2+reach+tolerance)
    blocks=grid[keep_blocks,2:].tolist()
    return blocks


def candidate_fraction(manifests,start,end,width,*,cancel=None):
    section_coordinates([],[],start,end,width)
    total=sum(m["source_points"] for m in manifests)
    count=0
    for m in manifests:
        for c in m["chunks"]:
            check_cancel(cancel)
            count+=sum(q-p for p,q in query_blocks(m,c,start,end,width))
    return count/max(1,total)


def extract(caches,start,end,width,*,limit=100000,cancel=None,stats=None,progress=lambda text:None):
    from pyproj import CRS
    section_coordinates([],[],start,end,width)
    if limit<1:raise ValueError('Positive sample limit required')
    if not caches:raise ValueError('Choose caches')
    check_cancel(cancel)
    manifests=[load(c) for c in caches]
    sources=[m['source']['path'] for m in manifests]
    if len(set(sources))!=len(sources):raise ValueError('Duplicate source')
    crs=CRS(manifests[0]['crs'])
    if any(CRS(m['crs'])!=crs for m in manifests):raise ValueError('Cloud coordinate systems differ')
    if len(set(m['chunk_size'] for m in manifests))!=1:raise ValueError('Sampling requires common source chunk size')
    rng=np.random.default_rng(0);outputs=[];counts=[];candidates=0;blocks_read=0
    for file_id,(cache,m) in enumerate(zip(caches,manifests)):
        keys=np.empty(0);rows=np.empty((0,5));classes=np.empty(0,dtype='u1');lines=np.empty(0,dtype='u2');indices=np.empty(0,dtype='i8');matched=0
        for chunk_number,chunk in enumerate(m['chunks'],1):
            check_cancel(cancel)
            progress(f"Cached section: {Path(m['source']['path']).name}, block {chunk_number}/{len(m['chunks'])}")
            blocks=query_blocks(m,chunk,start,end,width)
            if blocks:
                data=np.load(Path(cache)/chunk['file'],mmap_mode='r',allow_pickle=False)
                if data.dtype!=DTYPE or data.shape!=(chunk['rows'],):raise ValueError('Invalid cache array')
                selected=np.concatenate([data[p:q] for p,q in blocks]);del data
            else:selected=np.empty(0,dtype=DTYPE)
            candidates+=len(selected);blocks_read+=len(blocks)
            station,across,keep=section_coordinates(selected['x'],selected['y'],start,end,width)
            # Only matching rows need restoration to original source order.
            selected=selected[keep];station=station[keep];across=across[keep]
            order=np.argsort(selected['index'],kind='stable')
            selected=selected[order];station=station[order];across=across[order]
            keep=np.ones(len(selected),dtype=bool)
            matched+=len(selected)
            # Replay even empty chunks: argpartition order is part of reference sampling.
            keys=np.r_[keys,rng.random(int(keep.sum()))]
            rows=np.concatenate([rows,np.column_stack([selected['x'][keep],selected['y'][keep],selected['z'][keep],station[keep],across[keep]])])
            classes=np.r_[classes,selected['classification'][keep]];lines=np.r_[lines,selected['line'][keep]];indices=np.r_[indices,selected['index'][keep]]
            if len(keys)>limit:
                chosen=np.argpartition(keys,limit-1)[:limit]
                keys,rows,classes,lines,indices=(v[chosen] for v in (keys,rows,classes,lines,indices))
        counts.append(matched);outputs.append((rows,classes,lines,np.full(len(rows),file_id,dtype=np.int32),indices))
    check_cancel(cancel)
    for cache,m in zip(caches,manifests):
        if load(cache)!=m:raise ValueError('Cache changed during section query')
    if stats is not None:stats.update(candidate_points=candidates,blocks_read=blocks_read,source_points=sum(m['source_points'] for m in manifests))
    arrays=[np.concatenate([o[i] for o in outputs]) for i in range(5)]
    return Section(*arrays,sum(counts),counts,[m['source'] for m in manifests],crs.to_wkt(),list(map(float,start)),list(map(float,end)),float(width),int(limit))
