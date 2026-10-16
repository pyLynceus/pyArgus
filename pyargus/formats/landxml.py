"""LandXML TIN import retaining the supplied faces, in map X/Y/Z order.

LandXML point text is northing/easting/elevation. Hidden faces (i=1) are
excluded. This reader never rebuilds a surface from points or breaklines.
Explicit Boundary elements are refused until their clipping semantics are
implemented; face-defined holes and boundaries are retained exactly.
"""
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

@dataclass
class LandXmlSurface:
    name: str
    points: np.ndarray
    faces: np.ndarray
    metadata: dict


def read_landxml(path, surface_name=None):
    from pyargus.job_manifest import identity
    path=Path(path);before=identity(path)
    # Do not fetch a schema, resolve external entities, or process DTDs.
    with path.open('rb') as stream:
        tail=b''
        while block:=stream.read(1024*1024):
            upper=(tail+block).upper().replace(b'\x00',b'')
            if b'<!DOCTYPE' in upper or b'<!ENTITY' in upper:
                raise ValueError('LandXML DTD/entity declarations are not supported.')
            tail=upper[-16:]
    stack=[];names=[];selected=None;active=None;units=None;application={};coordinate_system=None
    for event,e in ET.iterparse(path,events=('start','end')):
        tag=e.tag.rsplit('}',1)[-1]
        if event=='start':
            stack.append(tag)
            if len(stack)==1 and tag!='LandXML':raise ValueError('Expected a LandXML root element.')
            if tag in ('Imperial','Metric'):
                if units is not None:raise ValueError('Multiple LandXML unit declarations.')
                units=dict(e.attrib)
            elif tag=='Application':application=dict(e.attrib)
            elif tag=='Surface':
                name=e.attrib.get('name','');names.append(name)
                active=(dict(name=name,ids=[],points=[],faces=[],hidden=0,breaklines=0,definitions=0) if (name==surface_name or (surface_name is None and len(names)==1)) else None)
            elif active is not None and tag=='Definition':
                active['definitions']+=1
                if e.attrib.get('surfType')!='TIN':raise ValueError('LandXML comparison requires an explicit TIN definition.')
            elif active is not None and tag=='Breakline':active['breaklines']+=1
            elif active is not None and tag=='Boundary':
                raise ValueError('Explicit LandXML Boundary clipping is not supported; export a face-trimmed TIN.')
            continue
        if tag=='CoordinateSystem':coordinate_system=dict(attributes=dict(e.attrib),text=(e.text or '').strip())
        if active is not None:
            if tag=='P' and len(stack)>=3 and stack[-3:]==['Definition','Pnts','P']:
                try:
                    pid=int(e.attrib['id']);v=[float(x) for x in (e.text or '').split()]
                except (KeyError,ValueError) as exc:raise ValueError('Invalid LandXML surface point.') from exc
                if pid<=0 or len(v)!=3 or not np.isfinite(v).all():raise ValueError('Surface points need a positive ID and finite northing/easting/elevation.')
                active['ids'].append(pid);active['points'].append((v[1],v[0],v[2]))
            elif tag=='F' and len(stack)>=3 and stack[-3:]==['Definition','Faces','F']:
                flag=e.attrib.get('i','0').lower()
                if flag not in ('0','1','false','true'):raise ValueError('Unknown LandXML face invisibility flag.')
                if flag in ('1','true'):active['hidden']+=1
                else:
                    try:f=[int(v) for v in (e.text or '').split()]
                    except ValueError as exc:raise ValueError('Invalid LandXML triangle references.') from exc
                    if len(f)!=3 or len(set(f))!=3:raise ValueError('LandXML faces need three distinct point references.')
                    active['faces'].append(f)
            elif tag=='Surface':selected=active;active=None
        stack.pop();e.clear()
    if surface_name is None and len(names)!=1:raise ValueError(f'Choose one LandXML surface explicitly; found {names}.')
    if surface_name is not None and names.count(surface_name)>1:raise ValueError('Duplicate LandXML surface names.')
    if selected is None:raise ValueError(f'LandXML surface not found: {surface_name!r}; available {names}.')
    if selected['definitions']!=1 or not selected['points'] or not selected['faces']:raise ValueError('Need one nonempty explicit TIN definition.')
    ids=selected['ids']
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate LandXML point IDs.')
    lookup={pid:i for i,pid in enumerate(ids)}
    try:faces=np.array([[lookup[v] for v in f] for f in selected['faces']],dtype=np.int64)
    except KeyError as exc:raise ValueError(f'Unknown LandXML point reference: {exc.args[0]}.') from exc
    if len(np.unique(np.sort(faces,axis=1),axis=0))!=len(faces):raise ValueError('Duplicate LandXML faces.')
    if not units or not units.get('linearUnit'):raise ValueError('LandXML needs an explicit linear unit declaration.')
    points=np.array(selected['points'],dtype=np.float64);points.setflags(write=False);faces.setflags(write=False)
    if identity(path)!=before:raise ValueError('LandXML changed while reading.')
    metadata=dict(source=before,surfaces=names,linear_unit=units['linearUnit'],units=units,application=application,coordinate_system=coordinate_system,point_order='LandXML N/E/Z converted to map X/Y/Z',vertices=len(points),active_faces=len(faces),hidden_faces=selected['hidden'],breaklines=selected['breaklines'],extent_min=points.min(axis=0).tolist(),extent_max=points.max(axis=0).tolist(),triangulation='Original supplied faces; no retriangulation')
    return LandXmlSurface(selected['name'],points,faces,metadata)
