"""Exact point lookup on an explicit reference TIN, without filling holes.

An auxiliary Delaunay is only an acceleration index: a simplex can be used
only when its three vertex IDs exactly match a supplied, active face.
All other locations search a bounding-volume tree of the remaining supplied
faces. Neither path ever interpolates a newly invented triangle.
"""
import numpy as np
from scipy.spatial import Delaunay,QhullError


def _keys(faces):
    return np.ascontiguousarray(np.sort(faces,axis=1),dtype=np.int64).view([('a','<i8'),('b','<i8'),('c','<i8')]).ravel()


class ReferenceTin:
    def __init__(self,points,faces,leaf_size=24):
        self.points=np.asarray(points,dtype=float);self.faces=np.asarray(faces,dtype=np.int64)
        if self.points.ndim!=2 or self.points.shape[1]!=3 or not np.isfinite(self.points).all():raise ValueError('TIN points must be finite XYZ.')
        if self.faces.ndim!=2 or self.faces.shape[1]!=3 or not len(self.faces) or self.faces.min()<0 or self.faces.max()>=len(self.points):raise ValueError('Invalid explicit TIN face indices.')
        if leaf_size<1:raise ValueError('TIN leaf size must be positive.')
        p=self.points[self.faces];self.p0=p[:,0];a=p[:,1]-p[:,0];b=p[:,2]-p[:,0];det=a[:,0]*b[:,1]-a[:,1]*b[:,0]
        threshold=np.finfo(float).eps*64*np.maximum(1.,np.linalg.norm(a[:,:2],axis=1)*np.linalg.norm(b[:,:2],axis=1))
        if np.any(abs(det)<=threshold):raise ValueError('Reference TIN contains degenerate XY faces.')
        self.inv=np.column_stack((b[:,1]/det,-b[:,0]/det,-a[:,1]/det,a[:,0]/det)).reshape(-1,2,2);self.dz=np.column_stack((a[:,2],b[:,2]));self.origin=self.points[:,:2].min(axis=0)
        self.lower=p[:,:,:2].min(axis=1);self.upper=p[:,:,:2].max(axis=1);self.extent=(self.lower.min(axis=0),self.upper.max(axis=0))
        self.slopes=np.linalg.norm(np.einsum('ni,nij->nj',self.dz,self.inv),axis=1);self.projected_area=float(np.sum(abs(det))/2)
        self.index=None;self.index_to_face=None;remaining=np.arange(len(self.faces))
        try:
            self.index=Delaunay(self.points[:,:2]-self.origin)
            _,d,f=np.intersect1d(_keys(self.index.simplices),_keys(self.faces),return_indices=True)
            self.index_to_face=np.full(len(self.index.simplices),-1,dtype=np.int64);self.index_to_face[d]=f
            remaining=np.setdiff1d(remaining,f,assume_unique=True)
        except QhullError:self.index=None
        self.nodes=[]
        def build(ids):
            low=self.lower[ids].min(axis=0);high=self.upper[ids].max(axis=0);at=len(self.nodes);self.nodes.append(None)
            if len(ids)<=leaf_size:self.nodes[at]=(low,high,-1,-1,ids)
            else:
                centers=(self.lower[ids]+self.upper[ids])/2;axis=int(np.argmax(np.ptp(centers,axis=0)));order=np.argsort(centers[:,axis],kind='stable');mid=len(ids)//2
                left=build(ids[order[:mid]]);right=build(ids[order[mid:]]);self.nodes[at]=(low,high,left,right,None)
            return at
        self.tree=build(remaining) if len(remaining) else -1
        self.metadata=dict(faces=len(self.faces),fast_index_matched_faces=len(self.faces)-len(remaining),fallback_faces=len(remaining),tree_nodes=len(self.nodes),projected_area=self.projected_area,minimum_normal_z=float((1/np.sqrt(1+self.slopes**2)).min()))

    def locate(self,x,y):
        x,y=np.broadcast_arrays(np.asarray(x,dtype=float),np.asarray(y,dtype=float));shape=x.shape;q=np.column_stack((x.ravel(),y.ravel()));out=np.full(len(q),-1,dtype=np.int64)
        finite=np.isfinite(q).all(axis=1);candidate=np.flatnonzero(finite & np.all(q>=self.extent[0],axis=1) & np.all(q<=self.extent[1],axis=1))
        if self.index is not None and len(candidate):
            d=self.index.find_simplex(q[candidate]-self.origin);valid=d>=0;out[candidate[valid]]=self.index_to_face[d[valid]]
            # Validate even accelerated containment on the supplied face.
            chosen=candidate[out[candidate]>=0];fi=out[chosen]
            w=np.einsum('nij,nj->ni',self.inv[fi],q[chosen]-self.p0[fi,:2]);inside=np.all(w>=-1e-10,axis=1)&(w.sum(axis=1)<=1+1e-10);out[chosen[~inside]]=-1
        pending=candidate[out[candidate]<0]
        if self.tree>=0 and len(pending):
            todo=[(self.tree,pending)]
            while todo:
                node,ids=todo.pop();low,high,left,right,faces=self.nodes[node]
                ids=ids[out[ids]<0];ids=ids[np.all(q[ids]>=low-1e-8,axis=1)&np.all(q[ids]<=high+1e-8,axis=1)]
                if not len(ids):continue
                if faces is None:todo.append((right,ids));todo.append((left,ids));continue
                # Bound temporary query x face arrays even in a sparse giant triangle.
                for start in range(0,len(ids),4096):
                    sel=ids[start:start+4096];delta=q[sel,None,:]-self.p0[faces,:2];w=np.einsum('fij,nfj->nfi',self.inv[faces],delta);inside=np.all(w>=-1e-10,axis=2)&(w.sum(axis=2)<=1+1e-10);hit=inside.any(axis=1)
                    out[sel[hit]]=faces[inside[hit].argmax(axis=1)]
        return out.reshape(shape)

    def sample(self,x,y):
        x,y=np.broadcast_arrays(np.asarray(x,dtype=float),np.asarray(y,dtype=float));face=self.locate(x,y);flat=face.ravel();q=np.column_stack((x.ravel(),y.ravel()));z=np.full(len(flat),np.nan);valid=flat>=0;f=flat[valid]
        w=np.einsum('nij,nj->ni',self.inv[f],q[valid]-self.p0[f,:2]);z[valid]=self.p0[f,2]+np.einsum('ni,ni->n',w,self.dz[f])
        return z.reshape(x.shape),face

    def z_at(self,x,y):return self.sample(x,y)[0]
