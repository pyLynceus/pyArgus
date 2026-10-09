"""Bounded DXF review layers; independent of terrain breakline ingestion."""
from collections import Counter
from pathlib import Path
import uuid
import numpy as np


def read_dxf(path, crs, planar=False, elevation=0., tolerance=.1, cancel=None):
    import ezdxf
    from ezdxf.path import make_path
    from ezdxf.colors import aci2rgb
    from pyproj import CRS
    from pyargus.job_manifest import identity
    frame=CRS(crs)
    if not frame.is_projected:raise ValueError('Declare a projected cloud CRS.')
    if not np.isfinite([elevation,tolerance]).all() or tolerance<=0:raise ValueError('Enter finite elevation and positive curve tolerance.')
    source=identity(path);doc=ezdxf.readfile(path)
    units={1:.0254,2:.3048,4:.001,5:.01,6:1.,7:1000.,21:1200/3937}
    declared=int(doc.header.get('$INSUNITS',0));factor=frame.axis_info[0].unit_conversion_factor
    if declared and (declared not in units or not np.isclose(units[declared],factor,rtol=1e-10,atol=0)):
        raise ValueError('DXF units differ from the declared cloud units (or are unsupported). Convert/export the DXF first; import does not rescale.')
    groups={};skipped=Counter();count=0
    for entity in doc.modelspace():
        if cancel is not None and cancel.is_set():raise InterruptedError('Import stopped')
        kind=entity.dxftype();name=entity.dxf.layer
        if kind=='POINT':points=[entity.dxf.location]
        elif kind=='LINE':points=[entity.dxf.start,entity.dxf.end]
        elif kind=='POLYLINE' and entity.is_3d_polyline:
            if entity.dxf.flags&6:skipped['fitted POLYLINE']+=1;continue
            points=list(entity.points())
            if entity.is_closed and points:points.append(points[0])
        elif kind in ('LWPOLYLINE','ARC','CIRCLE','ELLIPSE','SPLINE') or (kind=='POLYLINE' and entity.is_2d_polyline):
            points=[]
            for point in make_path(entity).flattening(tolerance):
                points.append(point)
                if count+len(points)>200000:raise ValueError('DXF exceeds 200,000 review vertices; split the file or increase curve tolerance.')
                if cancel is not None and cancel.is_set():raise InterruptedError('Import stopped')
        else:skipped[kind]+=1;continue
        xyz=np.asarray(points,dtype=float)
        if xyz.ndim!=2 or xyz.shape[1]!=3 or not len(xyz) or not np.isfinite(xyz).all():raise ValueError(f'Invalid geometry on layer {name}.')
        if not planar and np.all(xyz[:,2]==0):raise ValueError(f'Layer {name} contains zero-elevation geometry. Import as 2D plan linework with an explicit display elevation, or provide surveyed XYZ.')
        if planar:xyz[:,2]=elevation
        count+=len(xyz)
        if count>200000:raise ValueError('DXF exceeds 200,000 review vertices; split the file.')
        if name not in groups:
            layer=doc.layers.get(name);rgb=layer.rgb
            if rgb is None:rgb=aci2rgb(max(1,min(255,abs(layer.dxf.color))))
            groups[name]=dict(id=uuid.uuid4().hex,name=name,source=source,crs=frame.to_wkt(),
                planar=bool(planar),elevation=float(elevation) if planar else None,
                tolerance=float(tolerance),color='#%02x%02x%02x'%tuple(rgb),width=2,visible=True,on_top=True,segments=[])
        groups[name]['segments'].append(xyz.tolist())
    if identity(path)!=source:raise ValueError('DXF changed during import; retry.')
    if not groups:raise ValueError('No supported linework found. Blocks and annotation must be exploded/exported separately.')
    return list(groups.values()),dict(skipped)


def validate(layers):
    from pyproj import CRS
    ids=set();count=0
    for layer in layers:
        if layer['id'] in ids:raise ValueError('Duplicate linework layer ID.')
        ids.add(layer['id']);CRS(layer['crs'])
        if not isinstance(layer['color'],str) or len(layer['color'])!=7 or not layer['color'].startswith('#'):raise ValueError('Invalid layer color.')
        int(layer['color'][1:],16)
        if not 1<=int(layer['width'])<=6:raise ValueError('Line width must be 1–6.')
        for segment in layer['segments']:
            a=np.asarray(segment)
            if a.ndim!=2 or a.shape[1]!=3 or not len(a) or not np.isfinite(a).all():raise ValueError('Invalid linework vertices.')
            count+=len(a)
        if count>1000000:raise ValueError('Workspace linework exceeds one million vertices.')


def paint(pixels, cloud, lines, scale, pan, strength=0., eye=0):
    """Depth-test sampled screen-space line segments against visible cloud pixels."""
    from pyargus.anaglyph import eye_pixels
    h,w=pixels.shape[:2]
    def screen(q):return eye_pixels(q,scale,w,h,pan,strength,eye)
    depth=np.full((h,w),-np.inf)
    if len(cloud):
        p=np.rint(screen(cloud)).astype(np.int64)
        keep=(p[:,0]>=0)&(p[:,0]<w)&(p[:,1]>=0)&(p[:,1]<h)
        np.maximum.at(depth,(p[keep,1],p[keep,0]),cloud[keep,2])
    for q,color,width,on_top in lines:
        xy=screen(q)
        pairs=list(zip(range(len(q)-1),range(1,len(q)))) if len(q)>1 else [(0,0)]
        for i,j in pairs:
            # Clip to the viewport before allocating samples (Liang-Barsky).
            a,b=xy[i],xy[j];delta=b-a;lo,hi=0.,1.
            for d,offset in ((-delta[0],a[0]+6),(delta[0],w+6-a[0]),(-delta[1],a[1]+6),(delta[1],h+6-a[1])):
                if d==0:
                    if offset<0:hi=-1;break
                elif d<0:lo=max(lo,offset/d)
                else:hi=min(hi,offset/d)
            if lo>hi:continue
            n=max(1,int(np.ceil(np.max(np.abs(delta))*(hi-lo))))+1
            t=np.linspace(lo,hi,n);p=np.rint(a+t[:,None]*delta).astype(int)
            z=q[i,2]+t*(q[j,2]-q[i,2])
            low=-(width//2);high=low+width
            for dx in range(low,high):
                for dy in range(low,high):
                    x,y=p[:,0]+dx,p[:,1]+dy
                    keep=(x>=0)&(x<w)&(y>=0)&(y<h)
                    ids=np.flatnonzero(keep)
                    if not on_top:ids=ids[z[ids]>=depth[y[ids],x[ids]]-1e-9]
                    pixels[y[ids],x[ids]]=color
