"""Breakline file dispatch. DXF coordinates stay in their supplied map frame."""
from pathlib import Path
import numpy as np


def read_breaklines(path):
    if Path(path).suffix.lower() != '.dxf':
        from .geojson import read_breaklines_geojson
        return read_breaklines_geojson(path)
    try:
        import ezdxf
    except ImportError as exc:
        raise ImportError('DXF import requires pyArgus[cad] (ezdxf).') from exc
    document = ezdxf.readfile(path)
    result = []
    ignored = {'TEXT','MTEXT','POINT','DIMENSION','HATCH'}
    for entity in document.modelspace():
        kind = entity.dxftype()
        context = f'{Path(path).name}: {kind} on layer {entity.dxf.layer}'
        closed = False
        if kind in ignored:
            continue
        if kind == 'POLYLINE' and entity.is_3d_polyline:
            if entity.dxf.flags & 6:
                raise ValueError(context + ': fitted curves must be exported as straight 3D polylines.')
            points = list(entity.points())
            closed = entity.is_closed
        elif kind == 'LINE':
            points = [entity.dxf.start,entity.dxf.end]
            if all(p.z == 0 for p in points):
                raise ValueError(context + ': zero-elevation LINE is ambiguous; export a surveyed 3D POLYLINE.')
        elif kind == 'LWPOLYLINE' or (kind == 'POLYLINE' and entity.is_2d_polyline):
            if entity.has_arc or (kind == 'POLYLINE' and entity.dxf.flags & 6):
                raise ValueError(context + ': curved segments must be exported as straight 3D polylines.')
            elevation = entity.dxf.elevation
            z = elevation if kind == 'LWPOLYLINE' else elevation.z
            if z == 0:
                raise ValueError(context + ': planar line has no usable elevation; export surveyed 3D polylines.')
            points = list(entity.vertices_in_wcs() if kind == 'LWPOLYLINE' else entity.points_in_wcs())
            closed = entity.closed if kind == 'LWPOLYLINE' else entity.is_closed
        else:
            raise ValueError(context + ': unsupported breakline geometry. Export a breakline-only DXF of straight 3D polylines; explode blocks first.')
        xyz = np.asarray(points,dtype=float)
        if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz)<2 or not np.isfinite(xyz).all():
            raise ValueError(context + ': needs at least two finite XYZ vertices.')
        if closed and not np.array_equal(xyz[0],xyz[-1]): xyz = np.vstack((xyz,xyz[0]))
        if not np.any(np.linalg.norm(np.diff(xyz[:,:2],axis=0),axis=1)>0):
            raise ValueError(context + ': has no horizontal length.')
        result.append(xyz)
    if not result: raise ValueError(f'{path}: no supported breaklines in model space.')
    return result
