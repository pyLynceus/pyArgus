"""Validated review bookmarks and annotations; no processing decisions or point edits."""
from copy import deepcopy
from pathlib import Path
import math
import uuid
import numpy as np
from pyargus.job_manifest import identity,utc_now

STATES=('Open','In review','Resolved')
CATEGORIES=('Ground classification','Noise','Strip mismatch','Surface','Linework','Other')
COLORS=('Dataset','Flight line','Elevation','Classification')


def text(value,label,limit,empty=False):
    if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):
        raise ValueError(f'{label} must be text of at most {limit} characters.')
    return value.strip()


def vector(value,size,label):
    try:result=np.asarray(value,dtype=float)
    except (TypeError,ValueError):raise ValueError(f'Invalid {label}.') from None
    if result.shape!=(size,) or not np.isfinite(result).all():raise ValueError(f'Invalid {label}.')
    return result.tolist()


def number(value,label,low=None,high=None):
    if isinstance(value,bool):raise ValueError(f'Invalid {label}.')
    try:result=float(value)
    except (TypeError,ValueError):raise ValueError(f'Invalid {label}.') from None
    if not math.isfinite(result) or (low is not None and result<low) or (high is not None and result>high):
        raise ValueError(f'Invalid {label}.')
    return result


def source(value):
    if not isinstance(value,dict) or not isinstance(value.get('path'),str) or not Path(value['path']).is_absolute():
        raise ValueError('Review source needs an absolute path.')
    if any(type(value.get(k)) is not int or value[k]<0 for k in ('size_bytes','mtime_ns')):
        raise ValueError('Review source needs recorded size and modification time.')
    if value.get('identity_method')!='size_and_mtime':raise ValueError('Unsupported review source identity.')
    return deepcopy(value)


def validate_state(value):
    from pyargus.display_filters import parse_classes
    if not isinstance(value,dict) or value.get('schema_version')!=1:raise ValueError('Unsupported saved review view.')
    state=deepcopy(value)
    if not isinstance(state.get('inputs'),list) or not state['inputs']:raise ValueError('A saved view needs clouds.')
    state['inputs']=[source(item) for item in state['inputs']]
    paths=[s['path'] for s in state['inputs']]
    if len(set(paths))!=len(paths) or any(Path(p).suffix.lower() not in ('.las','.laz') for p in paths):
        raise ValueError('Invalid saved cloud list.')
    camera=state.get('camera')
    if not isinstance(camera,dict):raise ValueError('Saved view needs a camera.')
    camera['center']=vector(camera.get('center'),3,'camera center')
    camera['pan_units']=vector(camera.get('pan_units'),2,'camera pan')
    for key,low,high in [('yaw',None,None),('pitch',-90,90),('zoom',.05,100),('span',1e-12,None)]:
        camera[key]=number(camera.get(key),key,low,high)
    if state.get('crs') is not None:
        from pyproj import CRS
        from pyproj.exceptions import CRSError
        try:CRS(text(state['crs'],'CRS',100000))
        except CRSError:raise ValueError('Invalid saved CRS.') from None
    display=state.get('display')
    if not isinstance(display,dict) or display.get('mode') not in COLORS:raise ValueError('Invalid saved display.')
    parse_classes(text(display.get('classes'),'class filter',2048))
    line=text(display.get('line'),'LAS line',20)
    if line.lower()!='all' and (not line.isdecimal() or not 0<=int(line)<=65535):raise ValueError('Invalid LAS line filter.')
    display['depth']=number(display.get('depth'), 'stereo depth',0,6)
    for key in ('stereo','swap'):
        if type(display.get(key)) is not bool:raise ValueError('Invalid stereo flag.')
    if not isinstance(state.get('visible'),list) or len(state['visible'])!=len(paths) or any(type(x) is not bool for x in state['visible']):
        raise ValueError('Saved cloud visibility differs from its cloud list.')
    section=state.get('section')
    if section is not None:
        if not isinstance(section,dict):raise ValueError('Invalid saved section.')
        from pyargus.sections import section_coordinates
        section['start']=vector(section.get('start'),2,'section A');section['end']=vector(section.get('end'),2,'section B')
        section['width']=number(section.get('width'),'section width',1e-12)
        section_coordinates([],[],section['start'],section['end'],section['width'])
    selected=state.get('section_source','')
    if selected not in ('','Compare all loaded clouds',*paths):raise ValueError('Saved Section source is not a saved cloud.')
    if type(state.get('confirmed')) is not bool:raise ValueError('Invalid comparison confirmation.')
    profile=state.get('profile',{})
    if profile.get('mode') not in ('Dataset','Flight line','Classification'):raise ValueError('Invalid profile color.')
    profile['exaggeration']=number(profile.get('exaggeration'),'profile exaggeration',1e-12,1000)
    profile_line=text(profile.get('line'),'profile line',20)
    if profile_line.lower()!='all' and (not profile_line.isdecimal() or not 0<=int(profile_line)<=65535):raise ValueError('Invalid profile line.')
    if not isinstance(state.get('layout'),dict):raise ValueError('Missing review layout.')
    layout=state['layout'];layout['mode']='Review'
    for key in ('dock','extract_on_release'):
        if type(layout.get(key)) is not bool:raise ValueError('Invalid review layout flag.')
    text(layout.get('pane'),'review pane',100)
    if layout.get('preset') not in ('Custom','Full 3D','3D + Profile','Comparison review'):raise ValueError('Invalid layout preset.')
    layout['split_fraction']=min(.85,max(.15,number(layout.get('split_fraction'),'review split',0,1)))
    if type(state.get('details')) is not bool:raise ValueError('Invalid section options setting.')
    refs=state.get('references',[])
    if not isinstance(refs,list):raise ValueError('Invalid reference layers.')
    for ref in refs:
        if not isinstance(ref,dict):raise ValueError('Invalid reference layer.')
        text(ref.get('id'),'reference ID',100);source(ref.get('source'))
        if type(ref.get('visible')) is not bool:raise ValueError('Invalid reference visibility.')
    if len({r['id'] for r in refs})!=len(refs):raise ValueError('Duplicate reference layers.')
    route=state.get('route')
    if route is not None:
        if not isinstance(route,dict):raise ValueError('Invalid section route.')
        reference=next((r for r in refs if r['id']==route.get('layer')),None)
        if reference is None or reference['source']!=route.get('source'):raise ValueError('Saved route reference is missing.')
        if type(route.get('segment')) is not int or route['segment']<0:raise ValueError('Invalid route entity.')
        for key in ('station','span','width','spacing'):
            number(route.get(key),'route '+key,0 if key=='station' else 1e-12)
    return state


def context_errors(state):
    """Metadata checks only; never hash or read a full cloud to recall a view."""
    errors=[];seen=set()
    for recorded in [*state['inputs'],*[r['source'] for r in state.get('references',[])]]:
        if recorded['path'] in seen:continue
        seen.add(recorded['path'])
        try:current=identity(recorded['path'])
        except OSError:errors.append('Missing: '+recorded['path']);continue
        if current!=recorded:errors.append('Changed: '+recorded['path'])
    return errors


def view_center(camera):
    """Center of the visible camera plane, an approximate issue anchor, not a measurement."""
    yaw,pitch=np.deg2rad([camera['yaw'],camera['pitch']])
    right=np.array([np.cos(yaw),np.sin(yaw),0])
    up=np.array([-np.sin(yaw)*np.sin(pitch),np.cos(yaw)*np.sin(pitch),np.cos(pitch)])
    return (np.asarray(camera['center'])-right*camera['pan_units'][0]+up*camera['pan_units'][1]).tolist()


class ReviewMemory:
    def __init__(self,data=None):
        self.data=deepcopy(data) if data is not None else dict(schema_version=1,views=[],issues=[],last_review=None)
        if not isinstance(self.data,dict) or self.data.get('schema_version')!=1:raise ValueError('Unsupported review notes format.')
        ids=set();numbers=set()
        for key in ('views','issues'):
            rows=self.data.get(key)
            if not isinstance(rows,list) or len(rows)>10000:raise ValueError('Invalid review records.')
            for row in rows:
                if not isinstance(row,dict):raise ValueError('Invalid review record.')
                item_id=text(row.get('id'),'record ID',100)
                if item_id in ids:raise ValueError('Duplicate review record ID.')
                ids.add(item_id);row['title']=text(row.get('title'),'title',120)
                row['view']=validate_state(row.get('view'))
                if key=='issues':
                    if row.get('state') not in STATES or row.get('category') not in CATEGORIES:raise ValueError('Invalid issue properties.')
                    row['note']=text(row.get('note'),'note',4000,empty=True)
                    if type(row.get('number')) is not int or row['number']<1 or row['number'] in numbers:raise ValueError('Invalid issue number.')
                    numbers.add(row['number']);self.validate_anchor(row.get('anchor'),row['view'])
        next_number=self.data.get('next_issue_number',max(numbers,default=0)+1)
        if type(next_number) is not int or next_number<=max(numbers,default=0):raise ValueError('Invalid next issue number.')
        self.data['next_issue_number']=next_number
        if self.data.get('last_review') is not None:self.data['last_review']=validate_state(self.data['last_review'])

    @staticmethod
    def validate_anchor(anchor,state):
        if not isinstance(anchor,dict) or anchor.get('kind') not in ('picked-sample','view-center'):raise ValueError('Invalid issue location.')
        anchor['xyz']=vector(anchor.get('xyz'),3,'issue XYZ')
        if anchor['kind']=='picked-sample':
            if anchor.get('file') not in [s['path'] for s in state['inputs']]:raise ValueError('Issue point is not from a saved cloud.')
            for key,maximum in [('classification',255),('line',65535)]:
                if type(anchor.get(key)) is not int or not 0<=anchor[key]<=maximum:raise ValueError('Invalid picked point metadata.')

    def get(self,kind,item_id):
        item=next((x for x in self.data[kind] if x['id']==item_id),None)
        if item is None:raise ValueError('Select a review record first.')
        return item

    def save_view(self,title,state,item_id=None):
        state=validate_state(state);title=text(title,'view name',120)
        if item_id is None:
            if len(self.data['views'])>=10000:raise ValueError('Review view limit reached.')
            row=dict(id=uuid.uuid4().hex,title=title,view=state,created=utc_now(),updated=utc_now());self.data['views'].append(row)
        else:
            row=self.get('views',item_id);row.update(title=title,view=state,updated=utc_now())
        return row

    def issue(self,title,state,pick=None):
        if len(self.data['issues'])>=10000:raise ValueError('Review issue limit reached.')
        state=validate_state(state)
        anchor=dict(kind='view-center',xyz=view_center(state['camera'])) if pick is None else dict(
            kind='picked-sample',xyz=[pick['x'],pick['y'],pick['z']],file=pick['file'],classification=pick['classification'],line=pick['line'])
        self.validate_anchor(anchor,state)
        row=dict(id=uuid.uuid4().hex,number=self.data['next_issue_number'],
                 title=text(title,'issue title',120),category='Other',state='Open',note='',anchor=anchor,view=state,created=utc_now(),updated=utc_now())
        self.data['issues'].append(row);self.data['next_issue_number']+=1;return row

    def update_issue(self,item_id,title,category,state,note):
        title=text(title,'issue title',120);note=text(note,'note',4000,empty=True)
        if category not in CATEGORIES or state not in STATES:raise ValueError('Choose valid issue properties.')
        row=self.get('issues',item_id);row.update(title=title,category=category,state=state,note=note,updated=utc_now())
        return row
