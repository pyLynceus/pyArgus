"""Cross-sections normal to a polyline; stationing is horizontal map distance."""
import numpy as np
from pyargus.sections import section_coordinates


def route_xy(vertices):
    points=np.asarray(vertices,dtype=float)
    if points.ndim!=2 or points.shape[1] not in (2,3) or len(points)<2 or not np.isfinite(points).all():
        raise ValueError('A route needs at least two finite XY vertices.')
    points=points[:,:2]
    # Vertical-only edges and consecutive duplicates have no horizontal length.
    points=points[np.r_[True,np.any(np.diff(points,axis=0)!=0,axis=1)]]
    lengths=np.linalg.norm(np.diff(points,axis=0),axis=1)
    cumulative=np.r_[0.,np.cumsum(lengths)]
    if not len(lengths) or not np.isfinite(cumulative).all() or cumulative[-1]<=0 or np.any(np.diff(cumulative)<=0):
        raise ValueError('Route must have finite, resolvable horizontal length.')
    return points,lengths,cumulative


def corridor_at(vertices,station,span,width):
    """A is left and B right looking forward; bisect bends at exact vertices.

    Closed routes stop at their last vertex (no automatic wrap). Reversals at
    an exact vertex are refused because a normal there is not well defined.
    """
    points,lengths,chain=route_xy(vertices)
    if not np.isfinite([station,span,width]).all() or span<=0 or width<=0:
        raise ValueError('Station must be finite; span and width must be positive.')
    if not 0<=station<=chain[-1]:raise ValueError(f'Station must be between 0 and {chain[-1]:.6f}.')
    i=min(int(np.searchsorted(chain,station,side='right'))-1,len(lengths)-1)
    tangent=(points[i+1]-points[i])/lengths[i]
    center=points[i]+(station-chain[i])*tangent
    tolerance=np.finfo(float).eps*32*max(1.,chain[-1])
    vertex=int(np.argmin(np.abs(chain-station)))
    if 0<vertex<len(points)-1 and abs(chain[vertex]-station)<=tolerance:
        tangent=(points[vertex]-points[vertex-1])/lengths[vertex-1]+(points[vertex+1]-points[vertex])/lengths[vertex]
        norm=np.linalg.norm(tangent)
        if norm<1e-8:raise ValueError('Route reverses direction at this station; choose a station beside the vertex.')
        tangent/=norm;center=points[vertex]
    left=np.array([-tangent[1],tangent[0]])
    a,b=center+left*span/2,center-left*span/2
    section_coordinates([],[],a,b,width)
    return a,b,float(chain[-1])
