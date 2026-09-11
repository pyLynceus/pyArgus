"""AT-referenced vertical correction: smooth, bounded, shared by every strip."""
import numpy as np
from scipy.interpolate import RBFInterpolator


def predict(xy,delta,query,kind,alpha=1.):
    xy=np.asarray(xy,dtype=float); delta=np.asarray(delta,dtype=float); query=np.asarray(query,dtype=float)
    if len(xy)<4 or not np.isfinite(xy).all() or not np.isfinite(delta).all() or not np.isfinite(query).all():
        raise ValueError('Correction needs at least four finite reference positions and heights')
    origin=xy.mean(axis=0); x=(xy-origin)/1000.; q=(query-origin)/1000.
    if kind=='bias': result=np.full(len(q),np.median(delta))
    elif kind=='plane':
        design=np.column_stack((x,np.ones(len(x))))
        if np.linalg.matrix_rank(design)<3: raise ValueError('Targets do not constrain a plane')
        coef=np.linalg.lstsq(design,delta,rcond=None)[0]
        result=np.column_stack((q,np.ones(len(q))))@coef
    else:
        result=RBFInterpolator(x,delta,kernel='thin_plate_spline',smoothing=float(kind))(q)
    # Do not allow uncontrolled spline extrapolation or overshoot.
    return alpha*np.clip(result,min(0.,float(delta.min())),max(0.,float(delta.max())))


def choose_model(xy,delta):
    xy=np.asarray(xy,dtype=float); delta=np.asarray(delta,dtype=float)
    if len(xy)<12: raise ValueError('At least twelve screened targets are needed for spatial validation')
    centered=xy-xy.mean(axis=0)
    axis=np.linalg.svd(centered,full_matrices=False)[2][0]
    order=np.argsort(centered@axis)
    blocks=np.array_split(order,5)
    baseline=float(np.sqrt(np.mean(delta**2)))
    candidates=[]
    for kind in ('bias','plane','0.1','1','10','100','1000'):
        loo=np.zeros(len(xy)); blocked=np.zeros(len(xy))
        for group,out in [(np.array([i]),loo) for i in range(len(xy))]+[(b,blocked) for b in blocks]:
            train=np.ones(len(xy),dtype=bool); train[group]=False
            out[group]=predict(xy[train],delta[train],xy[group],kind)
        for alpha in (.25,.5,.75,1.):
            a=delta-alpha*loo; b=delta-alpha*blocked
            candidates.append(dict(kind=kind,alpha=alpha,loo_rmse=float(np.sqrt(np.mean(a*a))),
                spatial_rmse=float(np.sqrt(np.mean(b*b))),loo_residuals=a.tolist(),spatial_residuals=b.tolist()))
    best=min(candidates,key=lambda c:max(c['loo_rmse'],c['spatial_rmse']))
    return dict(baseline_rmse=baseline,best=best,candidates=candidates,
        accepted=max(best['loo_rmse'],best['spatial_rmse'])<baseline*.98)


def correction_grid(xy,delta,kind,alpha,bounds,cell=50.):
    xmin,xmax,ymin,ymax=bounds
    x=np.arange(np.floor(xmin/cell)*cell,np.ceil(xmax/cell)*cell+cell*.5,cell)
    y=np.arange(np.floor(ymin/cell)*cell,np.ceil(ymax/cell)*cell+cell*.5,cell)
    if len(x)<2 or len(y)<2 or len(x)*len(y)>2000000: raise ValueError('Invalid or excessive correction grid size')
    grid=np.empty((len(x),len(y)))
    for start in range(0,len(x),50):
        xx,yy=np.meshgrid(x[start:start+50],y,indexing='ij')
        grid[start:start+50]=predict(xy,delta,np.column_stack((xx.ravel(),yy.ravel())),kind,alpha).reshape(xx.shape)
    return x,y,grid


def evaluate_grid(x,y,grid,e,n):
    from scipy.interpolate import RegularGridInterpolator
    e,n=np.asarray(e),np.asarray(n)
    return RegularGridInterpolator((x,y),grid,bounds_error=True)(np.column_stack((e,n)))


def export_cloud(source,destination,x,y,grid,*,expected_size=None,expected_mtime_ns=None,log=lambda s:None):
    """Stream Z-only correction to a new file, then verify every written record."""
    from pathlib import Path
    import hashlib
    import laspy
    source,destination=Path(source),Path(destination)
    if destination.exists() or source.resolve()==destination.resolve():
        raise ValueError('Correction output must be a new file')
    stat=source.stat()
    if expected_size is not None and (stat.st_size,stat.st_mtime_ns)!=(expected_size,expected_mtime_ns):
        raise ValueError('Source changed since fitting')
    original_hash=hashlib.sha256(); expected_hash=hashlib.sha256()
    count=0; lo=np.inf; hi=-np.inf; last=0
    import time
    with laspy.open(source) as reader:
        if reader.header.point_format.id in (4,5,9,10):
            raise ValueError('Waveform LAS requires a separate waveform-preservation workflow')
        header=reader.header.copy()
        with laspy.open(destination,mode='w',header=header) as writer:
            for points in reader.chunk_iterator(200000):
                original_hash.update(points.array.tobytes())
                delta=evaluate_grid(x,y,grid,np.asarray(points.x),np.asarray(points.y))
                points.z=np.asarray(points.z)+delta
                expected_hash.update(points.array.tobytes())
                writer.write_points(points)
                count+=len(points); lo=min(lo,float(delta.min())); hi=max(hi,float(delta.max()))
                if time.monotonic()-last>10:
                    log(f'{source.name}: corrected {count:,}/{header.point_count:,} points'); last=time.monotonic()
            if header.evlrs: writer.write_evlrs(header.evlrs)
    if (stat.st_size,stat.st_mtime_ns)!=(source.stat().st_size,source.stat().st_mtime_ns):
        raise ValueError('Source changed during export')
    log(f'{destination.name}: verifying all output point records')
    actual=hashlib.sha256(); verified=0
    with laspy.open(destination) as reader:
        if not np.array_equal(reader.header.scales,header.scales) or not np.array_equal(reader.header.offsets,header.offsets):
            raise ValueError('Output scale/offset mismatch')
        if reader.header.point_format!=header.point_format or reader.header.parse_crs()!=header.parse_crs():
            raise ValueError('Output schema/CRS mismatch')
        for points in reader.chunk_iterator(500000):
            actual.update(points.array.tobytes()); verified+=len(points)
    if actual.digest()!=expected_hash.digest() or verified!=count or count!=header.point_count:
        raise ValueError('Written point records failed verification')
    return dict(source=str(source),output=destination.name,points=count,delta_range=[lo,hi],
        source_record_sha256=original_hash.hexdigest(),output_record_sha256=actual.hexdigest(),
        verified=True,z_quantization=float(header.scales[2]))
