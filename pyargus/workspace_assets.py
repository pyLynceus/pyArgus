"""Bounded display sampling for generated ESRI ASCII surface layers."""
import math
import numpy as np

def surface_points(path,limit=100000):
    with open(path,encoding='utf-8') as stream:
        header={}
        for _ in range(6):
            key,value=stream.readline().split();header[key.lower()]=float(value)
        cols,rows=int(header['ncols']),int(header['nrows'])
        cell=header['cellsize'];nodata=header.get('nodata_value',-9999.)
        if cols<=0 or rows<=0 or cell<=0:raise ValueError('Invalid surface dimensions')
        x0=header.get('xllcorner',header.get('xllcenter',0)-cell/2)
        y0=header.get('yllcorner',header.get('yllcenter',0)-cell/2)
        step=max(1,math.ceil(cols*rows/limit));parts=[]
        for row in range(rows):
            values=np.fromstring(stream.readline(),sep=' ')
            if len(values)!=cols:raise ValueError('Malformed ESRI ASCII grid row')
            ids=np.arange((-row*cols)%step,cols,step)
            ids=ids[np.isfinite(values[ids])&(values[ids]!=nodata)]
            parts.append(np.column_stack([x0+(ids+.5)*cell,np.full(len(ids),y0+(rows-row-.5)*cell),values[ids]]))
    return np.concatenate(parts)
