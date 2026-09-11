"""SH151 AT correction evaluation; run explicitly as a module."""

def main():
    from pathlib import Path
    import json,time
    import laspy
    import numpy as np
    from scipy.spatial import cKDTree

    out=Path('reference/reports/sh151_at_fit')
    targets=json.loads((out/'bundle_targets.json').read_text())
    xy=np.array([p['xyz'][:2] for p in targets]); tree=cKDTree(xy)
    assert tree.query(xy,k=2)[0][:,1].min()>6, 'Overlapping target search circles need a multi-match gather'
    paths=sorted(Path('Z:/Users/BJordan/SH 151/LIDAR/TERRAFLIGHT/LAS').glob('*.las'))
    cache=out/'surface_cache'; cache.mkdir(exist_ok=True)
    gx0=int(np.floor(xy[:,0].min()/25))-2
    gy0=int(np.floor(xy[:,1].min()/25))-2
    nx=int(np.ceil(xy[:,0].max()/25))-gx0+3
    valid_cells=[]
    for q in xy:
        ix,iy=np.floor(q/25).astype(int)
        valid_cells.extend((ix+dx-gx0)+(iy+dy-gy0)*nx for dx in (-1,0,1) for dy in (-1,0,1))
    valid_cells=np.unique(valid_cells)
    metadata=[]; start=time.monotonic()
    for path in paths:
        stat=path.stat(); meta=dict(path=str(path),size=stat.st_size,mtime_ns=stat.st_mtime_ns)
        cachepath=cache/(path.stem+'.npz')
        with laspy.open(path) as reader:
            h=reader.header; crs=h.parse_crs()
            meta.update(points=h.point_count,crs=crs.to_string() if crs else None,scales=h.scales.tolist(),offsets=h.offsets.tolist())
            near=(xy[:,0]>=h.mins[0]-3)&(xy[:,0]<=h.maxs[0]+3)&(xy[:,1]>=h.mins[1]-3)&(xy[:,1]<=h.maxs[1]+3)
            parts=[]; processed=0
            if near.any():
                for chunk in reader.chunk_iterator(500000):
                    x0,y0=np.asarray(chunk.x),np.asarray(chunk.y)
                    bins=(np.floor(x0/25).astype(np.int64)-gx0)+(np.floor(y0/25).astype(np.int64)-gy0)*nx
                    keep=np.isin(bins,valid_cells)&~np.isin(np.asarray(chunk.classification),(7,18))
                    if keep.any():
                        x,y,z=(np.asarray(chunk[k])[keep] for k in ('x','y','z'))
                        distance,index=tree.query(np.column_stack((x,y)),distance_upper_bound=3.)
                        mask=np.isfinite(distance)
                        if mask.any(): parts.append(np.column_stack((index[mask],x[mask],y[mask],z[mask])))
                    processed+=len(chunk)
            data=np.concatenate(parts) if parts else np.empty((0,4))
        if (stat.st_size,stat.st_mtime_ns)!=(path.stat().st_size,path.stat().st_mtime_ns): raise RuntimeError('Source changed')
        np.savez(cachepath,data=data)
        metadata.append(meta)
        print(f'{len(metadata)}/{len(paths)} {path.name}: {len(data)} nearby surface returns; elapsed {time.monotonic()-start:.0f}s',flush=True)
    (out/'source_inventory.json').write_text(json.dumps(metadata,indent=2))
    print('Ground gathering complete',flush=True)


if __name__ == '__main__':
    main()
