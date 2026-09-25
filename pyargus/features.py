"""Editable candidate linework, separate from point clouds and processing history."""
from copy import deepcopy
from pathlib import Path
import json
import uuid
import numpy as np

KINDS = ('Pavement edge', 'Curb', 'Barrier top', 'Wall top', 'Wall base',
         'Top of slope', 'Toe of slope', 'Drainage', 'Other')


def validate(items):
    from pyproj import CRS
    ids = set()
    for f in items:
        if not isinstance(f['id'], str) or f['id'] in ids:
            raise ValueError('Feature IDs must be unique.')
        ids.add(f['id'])
        if not f['name'].strip() or f['kind'] not in KINDS or f['status'] not in ('Candidate', 'Accepted'):
            raise ValueError('Invalid feature name, type or status.')
        if not isinstance(f['vertices'], list): raise ValueError('Invalid vertices.')
        for v in f['vertices']:
            if np.shape(v['xyz']) != (3,) or not np.isfinite(v['xyz']).all():
                raise ValueError('Vertex coordinates must be finite XYZ values.')
            if not v.get('source') or not v['source'].get('path'):
                raise ValueError('Each vertex needs a source cloud identity.')
        if f['vertices']:
            crs = CRS(f['crs'])
            if not crs.is_projected: raise ValueError('Features require a projected CRS.')
            factors=[axis.unit_conversion_factor for axis in crs.axis_info]
            if not np.allclose(factors,factors[0],rtol=1e-12,atol=0):
                raise ValueError('Feature XYZ axes must use matching linear units.')
        if f['status'] == 'Accepted' and len(f['vertices']) < 2:
            raise ValueError('An accepted line needs at least two vertices.')
        if f['status']=='Accepted' and not any(v['xyz']!=f['vertices'][0]['xyz'] for v in f['vertices'][1:]):
            raise ValueError('An accepted line must have nonzero length.')


def sources_current(f):
    from pyargus.job_manifest import identity
    for v in f['vertices']:
        try:
            if identity(v['source']['path']) != v['source']: return False
        except OSError: return False
    return True


class Features:
    def __init__(self, items=()):
        self.items = deepcopy(list(items)); validate(self.items)
        self.undo_stack = []; self.redo_stack = []

    def get(self, fid):
        return next(f for f in self.items if f['id'] == fid)

    def change(self, action):
        before = deepcopy(self.items)
        try:
            result = action(); validate(self.items)
        except Exception:
            self.items = before; raise
        self.undo_stack.append(before); self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()
        return result

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(deepcopy(self.items)); self.items = self.undo_stack.pop()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(deepcopy(self.items)); self.items = self.redo_stack.pop()

    def new(self, name, kind):
        f = dict(id=uuid.uuid4().hex, name=name.strip(), kind=kind, status='Candidate', crs=None, vertices=[])
        self.change(lambda:self.items.append(f)); return f['id']

    def vertex(self, fid, xyz, source, crs, index=None):
        from pyproj import CRS
        def edit():
            f=self.get(fid)
            if f['crs'] and CRS(f['crs']) != CRS(crs): raise ValueError('Feature and cloud CRS differ.')
            f['crs']=CRS(crs).to_wkt()
            v=dict(xyz=list(map(float,xyz)), source=deepcopy(source), method='displayed cloud point')
            if index is None: f['vertices'].append(v)
            else: f['vertices'][index]=v
            f['status']='Candidate'
        self.change(edit)

    def update_xyz(self, fid, index, xyz):
        def edit():
            f=self.get(fid); f['vertices'][index]['xyz']=list(map(float,xyz))
            f['vertices'][index]['method']='manual XYZ edit'; f['status']='Candidate'
        self.change(edit)

    def metadata(self, fid, name, kind, status):
        def edit():
            f=self.get(fid)
            if status=='Accepted' and not sources_current(f):
                raise ValueError('Source cloud missing or changed; retrace/review against the current source.')
            f.update(name=name.strip(),kind=kind,status=status)
        self.change(edit)

    def delete_vertex(self, fid, index):
        def edit():
            f=self.get(fid); f['vertices'].pop(index); f['status']='Candidate'
        self.change(edit)

    def delete(self, fid):
        self.change(lambda:self.items.remove(self.get(fid)))

    def reverse(self, fid):
        def edit():
            f=self.get(fid); f['vertices'].reverse(); f['status']='Candidate'
        self.change(edit)

    def split(self, fid, index):
        def edit():
            f=self.get(fid)
            if not 0 < index < len(f['vertices'])-1: raise ValueError('Select an interior vertex to split.')
            other=deepcopy(f); other.update(id=uuid.uuid4().hex,name=f['name']+' (split)',status='Candidate')
            other['vertices']=other['vertices'][index:]
            f['vertices']=f['vertices'][:index+1]; f['status']='Candidate'
            self.items.append(other)
        self.change(edit)

    def join(self, first, second):
        from pyproj import CRS
        def edit():
            a,b=self.get(first),self.get(second)
            if first==second or not a['vertices'] or not b['vertices']: raise ValueError('Choose two nonempty lines.')
            if CRS(a['crs']) != CRS(b['crs']) or a['kind'] != b['kind']:
                raise ValueError('Join requires the same CRS and feature type.')
            # Deliberate order: first line end to second line start; never silently reverse.
            vertices=deepcopy(b['vertices'])
            if a['vertices'][-1]['xyz']==vertices[0]['xyz']: vertices=vertices[1:]
            a['vertices'].extend(vertices); a['status']='Candidate'; self.items.remove(b)
        self.change(edit)


def export_dxf(items, path, accepted_only=True):
    """New DXF plus a provenance sidecar; never overwrite an existing deliverable."""
    import ezdxf
    from pyproj import CRS
    selected=deepcopy([f for f in items if not accepted_only or f['status']=='Accepted'])
    validate(selected)
    if not selected: raise ValueError('No features match the export selection.')
    if any(len(f['vertices'])<2 for f in selected): raise ValueError('Every exported line needs at least two vertices.')
    crs=CRS(selected[0]['crs'])
    if any(CRS(f['crs']) != crs for f in selected): raise ValueError('Export requires a common CRS.')
    if any(not sources_current(f) for f in selected): raise ValueError('A feature source is missing or changed; export refused.')
    path=Path(path); sidecar=path.with_suffix('.features.json')
    if path.exists() or sidecar.exists(): raise ValueError('Choose a new DXF filename; DXF or sidecar already exists.')
    doc=ezdxf.new('R2010')
    # Map units are preserved; US survey feet must not be labeled international feet.
    factor=crs.axis_info[0].unit_conversion_factor
    doc.units=6 if abs(factor-1)<1e-12 else 21 if abs(factor-1200/3937)<1e-12 else 2 if abs(factor-.3048)<1e-12 else 0
    doc.appids.new('PYARGUS')
    for f in selected:
        layer=f['kind'].upper().replace(' ','_')+'_'+f['status'].upper()
        if layer not in doc.layers: doc.layers.new(layer,dxfattribs={'color':3 if f['status']=='Accepted' else 2})
        entity=doc.modelspace().add_polyline3d([v['xyz'] for v in f['vertices']],dxfattribs={'layer':layer})
        entity.set_xdata('PYARGUS',[(1000,f['id'])])
    made=[]
    try:
        with path.open('x',encoding='utf-8') as stream:
            made.append(path); doc.write(stream)
        with sidecar.open('x',encoding='utf-8') as stream:
            made.append(sidecar); json.dump(dict(schema_version=1,crs=crs.to_wkt(),features=selected),stream,indent=2,allow_nan=False)
    except Exception:
        for created in made: created.unlink(missing_ok=True)
        raise
    return path,sidecar
