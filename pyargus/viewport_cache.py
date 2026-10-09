"""Local-cache viewport sampling, preserving full-scan chunk sampling order."""
import numpy as np
from pyargus import section_cache


def mask(q,bounds,stereo_depth=0.):
    shear=np.tan(np.deg2rad(stereo_depth/2))
    keep_y=(q[:,1]>=bounds[2])&(q[:,1]<=bounds[3])
    return keep_y & (((q[:,0]+shear*q[:,2]>=bounds[0])&(q[:,0]+shear*q[:,2]<=bounds[1])) |
                     ((q[:,0]-shear*q[:,2]>=bounds[0])&(q[:,0]-shear*q[:,2]<=bounds[1])))


def extract(store,paths,center,yaw,pitch,bounds,*,limit=150000,cancel=None,progress=lambda s:None,stereo_depth=0.):
    from pyproj import CRS
    from pyargus.viewer3d import project_points
    from pyargus.job_manifest import identity
    if limit<1 or not np.isfinite([*center,yaw,pitch,*bounds,stereo_depth]).all() or not 0<=stereo_depth<=6:
        raise ValueError('Invalid viewport definition.')
    if bounds[0]>bounds[1] or bounds[2]>bounds[3]:raise ValueError('Invalid viewport bounds.')
    with store.locked():
        caches=[store.path(p) for p in paths];manifests=[section_cache.load(p) for p in caches]
        if not manifests:raise ValueError('No clouds loaded.')
        crs=CRS(manifests[0]['crs'])
        for source,m in zip(paths,manifests):
            if m['source']!=identity(source) or CRS(m['crs'])!=crs or m['chunk_size']!=250000:
                raise ValueError('Cache source, CRS or chunk size differs.')
        rng=np.random.default_rng(0);keys=np.empty(0);points=np.empty((0,3))
        classes=np.empty(0,dtype=np.uint8);lines=np.empty(0,dtype=np.uint16);files=np.empty(0,dtype=np.int32);matched=0
        basis=project_points(np.eye(3),np.zeros(3),yaw,pitch)
        shear=np.tan(np.deg2rad(stereo_depth/2))
        for file_id,(cache,m) in enumerate(zip(caches,manifests)):
            for ci,c in enumerate(m['chunks']):
                section_cache.check_cancel(cancel)
                progress(f'Local detail: file {file_id+1}/{len(paths)}, chunk {ci+1}/{len(m["chunks"])}')
                rows=np.load(cache/c['file'],mmap_mode='r',allow_pickle=False)
                try:
                    if rows.dtype!=section_cache.DTYPE or rows.shape!=(c['rows'],):raise ValueError('Invalid cache array.')
                    grid=np.asarray(c['blocks'],dtype=np.int64).reshape(-1,4)
                    if not len(rows):continue
                    # Read actual cached Z bounds, never trust potentially stale LAS header bounds.
                    zlo,zhi=float(rows['z'].min()),float(rows['z'].max())
                    mid=np.column_stack(((grid[:,0]+.5)*m['cell'],(grid[:,1]+.5)*m['cell'],np.full(len(grid),(zlo+zhi)/2)))
                    half=np.array([m['cell']/2,m['cell']/2,(zhi-zlo)/2])
                    projected=project_points(mid,np.asarray(center),yaw,pitch)
                    epsilon=np.finfo(float).eps*128*max(1.,float(np.abs(mid).max()))
                    yreach=half@np.abs(basis[:,1])+epsilon
                    candidates=np.zeros(len(grid),dtype=bool)
                    for sign in (-1,1):
                        x=projected[:,0]+sign*shear*projected[:,2]
                        reach=half@np.abs(basis[:,0]+sign*shear*basis[:,2])+epsilon
                        candidates|=(x+reach>=bounds[0])&(x-reach<=bounds[1])
                    candidates&=(projected[:,1]+yreach>=bounds[2])&(projected[:,1]-yreach<=bounds[3])
                    selected=[rows[a:b].copy() for a,b in grid[candidates,2:]]
                    data=np.concatenate(selected) if selected else np.empty(0,dtype=section_cache.DTYPE)
                finally:rows._mmap.close()
                data=data[np.argsort(data['index'],kind='stable')]
                xyz=np.column_stack((data['x'],data['y'],data['z']))
                keep=mask(project_points(xyz,np.asarray(center),yaw,pitch),bounds,stereo_depth)
                n=int(keep.sum());matched+=n
                keys=np.r_[keys,rng.random(n)];points=np.concatenate((points,xyz[keep]))
                classes=np.r_[classes,data['classification'][keep]];lines=np.r_[lines,data['line'][keep]]
                files=np.r_[files,np.full(n,file_id,dtype=np.int32)]
                if len(keys)>limit:
                    chosen=np.argpartition(keys,limit-1)[:limit]
                    keys,points,classes,lines,files=(v[chosen] for v in (keys,points,classes,lines,files))
        section_cache.check_cancel(cancel)
        for cache,m in zip(caches,manifests):
            if section_cache.load(cache)!=m:raise ValueError('Cache changed during refinement.')
        return points,classes,lines,files,matched,crs
