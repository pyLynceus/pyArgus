"""Read-only LAS header inventory, map geometry and workflow guidance."""
from pathlib import Path
import math
import numpy as np


def read_extents(paths, cache=None, cancel=lambda: False):
    """Read headers only. Cache by size/mtime; never read or decompress points."""
    import laspy
    from pyargus.job_manifest import identity
    rows=[]; cache=dict(cache or {})
    for name in paths:
        if cancel():raise InterruptedError('Overview cancelled')
        path=str(Path(name).resolve())
        try:
            source=identity(path)
            old=cache.get(path)
            if old and old.get('source')==source:
                rows.append(dict(old));continue
            with laspy.open(path, read_evlrs=False) as las:
                h=las.header;crs=h.parse_crs();count=int(h.point_count)
                bounds=np.r_[h.mins,h.maxs].astype(float)
                if not np.isfinite(bounds).all() or np.any(bounds[3:]<bounds[:3]):
                    raise ValueError('Invalid LAS header bounds')
                # Do not load EVLR payloads: these can contain large waveform data.
                row=dict(path=path,source=source,points=count,bounds=bounds.tolist(),
                    crs=crs.to_wkt() if crs and crs.is_projected else None,
                    crs_name=crs.name if crs else 'CRS not declared',
                    units=crs.axis_info[0].unit_name if crs and crs.is_projected else 'unknown',
                    error=None if count else 'Empty cloud')
                if count and not row['crs']:row['error']='Projected CRS required in header/VLR for mapping (EVLR payloads are not read)'
            if identity(path)!=source:raise ValueError('Source changed while reading header; refresh')
            cache[path]=dict(row);rows.append(row)
        except (OSError,ValueError,RuntimeError,laspy.errors.LaspyException) as exc:
            rows.append(dict(path=path,source=None,points=None,bounds=None,crs=None,
                crs_name='Unavailable',units='unknown',error=str(exc)))
    return rows,{r['path']:cache[r['path']] for r in rows if r['path'] in cache}


def coordinate_groups(rows):
    from pyproj import CRS
    groups=[]
    for row in rows:
        if row['error'] or not row['crs']:continue
        crs=CRS(row['crs'])
        group=next((g for g in groups if CRS(g['crs'])==crs),None)
        if group is None:
            group=dict(crs=row['crs'],name=row['crs_name'],units=row['units'],rows=[]);groups.append(group)
        group['rows'].append(row)
    return groups


def combined_bounds(rows):
    if not rows:return None
    bounds=np.array([r['bounds'] for r in rows],dtype=float)
    return np.r_[bounds[:,:3].min(axis=0),bounds[:,3:].max(axis=0)]


def map_transform(bounds,width,height,padding=22):
    lo=np.asarray(bounds[:2],float);hi=np.asarray(bounds[3:5],float)
    span=np.maximum(hi-lo,1.)
    scale=min(max(1,width-2*padding)/span[0],max(1,height-2*padding)/span[1])
    return (lo+hi)/2,scale,np.array([width/2,height/2])


def map_pixels(xy,transform):
    center,scale,offset=transform
    return (np.asarray(xy)-center)*[scale,-scale]+offset


def map_world(xy,transform):
    center,scale,offset=transform
    return (np.asarray(xy)-offset)/[scale,-scale]+center


def camera_plane(center,yaw,pitch,pan,span,zoom,width,height):
    """View rectangle intersected with the horizontal plane at camera-center Z.

    Edge-on views have no finite rectangle. This is navigation, not coverage.
    """
    if abs(math.sin(math.radians(pitch)))<.1:return None
    scale=min(width,height)*.85/span*zoom
    a,b=np.deg2rad([yaw,pitch])
    matrix=np.array([[np.cos(a),np.sin(a)],[-np.sin(a)*np.sin(b),np.cos(a)*np.sin(b)]])
    screen=np.array([[0,0],[width,0],[width,height],[0,height]])
    q=(screen-[width/2,height/2]-pan)/[scale,-scale]
    return np.linalg.solve(matrix,q.T).T+np.asarray(center)[:2]


def workflow_summary(tracker, stage_rows, clouds, settings=None, running=None,
                     missing_clocks=0, issues=0):
    """Describe tracker evidence without changing decisions or starting work."""
    from pyargus.workspace_state import STAGES
    rows={stage:(status,detail) for stage,status,detail in stage_rows}
    roots={tracker.cloud_root(p) for p in clouds}
    jobs={tracker.cloud_root(j['settings']['cloud']):j for j in tracker.current_jobs('Classification')
          if j.get('stage_class','ClassifyStage')=='ClassifyStage' and j.get('settings',{}).get('cloud')}
    current={root:jobs[root] for root in roots if root in jobs}
    accepted=sum(tracker.job_status(j,settings(j) if settings else None)=='Accepted' for j in current.values())
    missing=len(roots-set(current))
    coverage=f'{len(current)}/{len(roots)} active inputs have ground runs; {accepted} accepted'
    stage=None;kind='history';label='Job history';detail='Review existing job records.'
    if running:
        headline=f'{running} running';detail='Wait for completion; results still require review.';kind='busy';label='Job running'
    elif not roots:
        headline='Add project clouds';detail='Add LAS/LAZ files to establish processing inputs.';kind='add';label='Add data…'
    else:
        for name in STAGES:
            state,why=rows.get(name,('Not started','Run or explicitly skip'))
            if name=='Classification' and missing and (current or state=='Accepted') and state in ('Accepted','Needs review','Not started'):
                stage=name;kind='task';label='Prepare classification';headline='Ground classification is partial'
                detail=coverage+f'; {missing} input(s) have no ground attempt.';break
            if state not in ('Accepted','Skipped'):
                stage=name;detail=why
                if state in ('Needs review','Unverified import'):
                    headline=f'Review {name}';label=headline
                elif state=='Running':headline=f'{name} running';label='Job running';kind='busy'
                elif name=='Inspect' and missing_clocks:
                    headline='Set trajectory time bases';detail=f'{missing_clocks} trajectory file(s) need an explicit clock setting.';kind='settings';label='Trajectory settings'
                else:
                    headline=('Revisit ' if state=='Outdated' else 'Retry ' if state in ('Failed','Cancelled') else 'Prepare ')+name
                    kind='task' if name!='Delivery' else 'delivery';label=headline
                break
        else:
            headline='Listed stages reviewed';detail='All listed stages accepted or explicitly skipped. Check deliverables.';kind='delivery';label='Review delivery'
    return dict(headline=headline,detail=detail,stage=stage,kind=kind,label=label,
        coverage=coverage,missing_ground=missing,ground_total=len(roots),ground_recorded=len(current),
        ground_accepted=accepted,open_issues=issues,
        reviewed=sum(rows.get(s,('Not started',''))[0] in ('Accepted','Skipped') for s in STAGES),total=len(STAGES))
