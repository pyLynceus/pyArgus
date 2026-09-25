"""Multi-file lidar projects: validate, match, analyze, and export with provenance.

LAS point_source_id values are never rewritten. Analysis uses separate internal
strip keys so a reused line number on another trajectory cannot merge flights.
Trajectory files are kept separate: interpolation never bridges file boundaries.
"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import html
import json
import tempfile

import numpy as np

from pyargus.formats import sbet, trajectory, trj


@dataclass
class TrajectoryInput:
    path: str
    time_mode: str = "week"
    gps_week: int | None = None
    confirmed: bool = False


@dataclass
class Project:
    clouds: list[str] = field(default_factory=list)
    trajectories: list[TrajectoryInput] = field(default_factory=list)
    map_crs: str | None = None  # declaration for untagged files, not a transform
    same_vertical: bool = False
    gps_week: int | None = None  # required for LAS week-time input
    vertical: str | float | None = None  # SBET only
    allow_network: bool = False
    bindings: dict[str, str] = field(default_factory=dict)  # cloud -> trajectory
    max_gap: float = 1.0
    max_points: int = 25_000_000
    shared_strip_ids: bool = False  # explicit namespace declaration without trajectories

    def save(self, path):
        path = Path(path)
        payload = dict(version=1, **asdict(self))
        # Store absolute references so moving the manifest doesn't change inputs.
        payload['clouds'] = [str(Path(p).resolve()) for p in self.clouds]
        for item in payload['trajectories']:
            item['path'] = str(Path(item['path']).resolve())
        payload['bindings'] = {str(Path(k).resolve()): str(Path(v).resolve())
                               for k, v in self.bindings.items()}
        with path.open('x', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)

    @classmethod
    def load(cls, path):
        path = Path(path)
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.pop('version', None) != 1:
            raise ValueError('unsupported pyArgus project version')
        def resolve(value):
            p = Path(value)
            return str((path.parent / p).resolve()) if not p.is_absolute() else str(p.resolve())
        payload['clouds'] = [resolve(p) for p in payload['clouds']]
        payload['trajectories'] = [TrajectoryInput(**dict(t, path=resolve(t['path'])))
                                   for t in payload.get('trajectories', [])]
        payload['bindings'] = {resolve(k): resolve(v) for k, v in payload.get('bindings', {}).items()}
        try:
            return cls(**payload)
        except TypeError as exc:
            raise ValueError(f'invalid project settings: {exc}') from exc


class Cancelled(Exception):
    pass


def _check_cancel(cancel):
    if cancel():
        raise Cancelled('project job cancelled')


def _paths(values, label):
    paths = [Path(v).resolve() for v in values]
    if len(set(paths)) != len(paths):
        raise ValueError(f'duplicate {label} path; select each source only once')
    for p in paths:
        if not p.is_file():
            raise ValueError(f'no such {label}: {p}')
    return paths


def _week(value):
    if value is None:
        return None
    if isinstance(value, bool) or int(value) != value or value < 0:
        raise ValueError('GPS week must be a nonnegative integer')
    return int(value)


def _cloud_headers(project):
    import laspy
    import pyproj
    paths = _paths(project.clouds, 'LAS/LAZ')
    if not paths:
        raise ValueError('add at least one LAS/LAZ file')
    if type(project.same_vertical) is not bool or not project.same_vertical:
        raise ValueError('confirm that all clouds share their vertical datum and XYZ units')
    if type(project.allow_network) is not bool or type(project.shared_strip_ids) is not bool:
        raise ValueError('project confirmation settings must be booleans')
    if not np.isfinite(project.max_gap) or project.max_gap <= 0:
        raise ValueError('maximum trajectory gap must be positive and finite')
    if project.max_points < 1 or int(project.max_points) != project.max_points:
        raise ValueError('analysis point limit must be a positive integer')
    declared = pyproj.CRS.from_user_input(project.map_crs) if project.map_crs else None
    common, metadata = None, []
    for path in paths:
        if path.suffix.lower() not in ('.las', '.laz'):
            raise ValueError(f'not a LAS/LAZ path: {path}')
        with laspy.open(path) as reader:
            h = reader.header
            crs = h.parse_crs()
            if crs is None:
                if declared is None:
                    raise ValueError(f'{path.name}: no CRS; supply the CRS declaration for untagged clouds')
                crs = declared
            elif declared is not None and not crs.equals(declared):
                raise ValueError(f'{path.name}: declared project CRS disagrees with the LAS CRS')
            horizontal = crs.sub_crs_list[0] if crs.is_compound else crs
            if not horizontal.is_projected:
                raise ValueError(f'{path.name}: a projected CRS is required')
            factors = [a.unit_conversion_factor for a in crs.axis_info]
            if not factors or not np.allclose(factors, factors[0], rtol=1e-12, atol=0):
                raise ValueError(f'{path.name}: mixed XYZ units; convert all axes to one linear unit first')
            if common is not None and not common.equals(crs):
                raise ValueError(f'{path.name}: CRS mismatch; project import does not reproject clouds')
            common = crs
            dims = set(h.point_format.dimension_names)
            if project.trajectories and 'gps_time' not in dims:
                raise ValueError(f'{path.name}: no GPS timestamps to match trajectories')
            gps_type = int(h.global_encoding.gps_time_type) if 'gps_time' in dims else None
            if gps_type == 0 and project.gps_week is None and project.trajectories:
                raise ValueError(f'{path.name}: LAS uses seconds of week; supply the project GPS week')
            if h.point_count == 0:
                raise ValueError(f'{path.name}: empty point cloud')
            metadata.append(dict(path=str(path), points=int(h.point_count), gps_type=gps_type,
                                 bounds=[h.mins.tolist(), h.maxs.tolist()],
                                 size=path.stat().st_size, mtime_ns=path.stat().st_mtime_ns))
    _week(project.gps_week)
    return common, metadata


@dataclass
class Track:
    input: TrajectoryInput
    records: np.ndarray
    line: int | None
    native: bool
    time: np.ndarray | None = None
    signature: tuple | None = None


def _read_tracks(project):
    paths = _paths([t.path for t in project.trajectories], 'trajectory')
    tracks = []
    for settings, path in zip(project.trajectories, paths):
        if type(settings.confirmed) is not bool:
            raise ValueError('trajectory confirmation must be a boolean')
        signature = (path.stat().st_size,path.stat().st_mtime_ns)
        native = trajectory.is_trj(path)
        if native:
            parsed = trj.read_trj(path)
            data, line = parsed.records, parsed.line_number or None
            if settings.time_mode not in ('same', 'week'):
                raise ValueError(f'{path.name}: select same stored timestamps or GPS week seconds')
            trajectory.validate_trj_time(data['time'], settings.time_mode)
        else:
            data, line = sbet.read_sbet(path), None
            if settings.time_mode != 'week':
                raise ValueError(f'{path.name}: SBET timestamps must be GPS seconds of week')
        if len(data) < 2 or not all(np.isfinite(data[n]).all() for n in data.dtype.names):
            raise ValueError(f'{path.name}: need at least two finite trajectory records')
        _week(settings.gps_week)
        if signature != (path.stat().st_size,path.stat().st_mtime_ns):
            raise ValueError(f'{path.name}: trajectory changed during import')
        tracks.append(Track(settings, data, line, native,signature=signature))
    return tracks


def _point_times(raw, gps_type, project):
    t = np.asarray(raw, dtype=float)
    if not np.isfinite(t).all():
        raise ValueError('LAS has nonfinite GPS times')
    if gps_type == 0:
        if np.any((t < 0) | (t >= 604800)):
            raise ValueError('LAS header says week time, but timestamps are outside that range')
        return t + (_week(project.gps_week) * 604800 - 1e9)
    return t


def _unchanged(metadata):
    p = Path(metadata['path'])
    stat = p.stat()
    if (stat.st_size,stat.st_mtime_ns) != (metadata['size'],metadata['mtime_ns']):
        raise ValueError(f'{p.name}: input changed during the project job; restart from stable inputs')


def _coverage(times, query, max_gap):
    """Include records and interpolable intervals, excluding internal outages."""
    right = np.searchsorted(times, query, side='left')
    clipped = np.minimum(right, len(times)-1)
    exact = times[clipped] == query
    between = (right > 0) & (right < len(times))
    gap = times[clipped] - times[np.maximum(clipped-1, 0)]
    return exact | (between & (gap <= max_gap))


@dataclass
class LoadedProject:
    project: Project
    crs: object
    inventory: dict
    tracks: list[Track]
    points: dict | None
    assignments: np.ndarray | None
    sources: list[slice]


def load(project, *, keep_points=False, log=lambda text: None, cancel=lambda: False, chunk_sink=None):
    """Stream inventory/matching; retain arrays only for requested analysis."""
    import laspy
    crs, clouds = _cloud_headers(project)
    tracks = _read_tracks(project)
    total = sum(c['points'] for c in clouds)
    if keep_points and total > project.max_points:
        raise ValueError(f'{total:,} points exceed the {project.max_points:,} analysis limit; '
                         'inventory is streaming, but QA/alignment need arrays. '
                         'Select a smaller block or raise the point limit for available RAM.')
    bindings = {str(Path(k).resolve()): str(Path(v).resolve()) for k,v in project.bindings.items()}
    track_paths = [str(Path(t.input.path).resolve()) for t in tracks]
    if not set(bindings).issubset(c['path'] for c in clouds) or not set(bindings.values()).issubset(track_paths):
        raise ValueError('trajectory binding references an input not selected in this project')
    # First scan establishes the LAS clock, before inferring any SBET week.
    time_min, time_max = np.inf, -np.inf
    gps_types = {c['gps_type'] for c in clouds}
    if tracks and len(gps_types) != 1:
        raise ValueError('mixed LAS GPS time encodings; normalize the clocks before combining files')
    if tracks:
        for c in clouds:
            log(f"Checking timestamps: {Path(c['path']).name}")
            with laspy.open(c['path']) as reader:
                for chunk in reader.chunk_iterator(500_000):
                    _check_cancel(cancel)
                    t = _point_times(chunk.gps_time, c['gps_type'], project)
                    time_min, time_max = min(time_min, float(t.min())), max(time_max, float(t.max()))
        min_week, max_week = (int(np.floor((t+1e9)/604800)) for t in (time_min,time_max))
        for track in tracks:
            t = track.records['time'].astype(float, copy=True)
            if track.native and track.input.time_mode == 'same':
                track.time = _point_times(t, next(iter(gps_types)), project)
            else:
                week = track.input.gps_week if track.input.gps_week is not None else project.gps_week
                if week is None:
                    if min_week != max_week:
                        raise ValueError('clouds span GPS weeks; supply a GPS week for each week-time trajectory')
                    week = min_week
                if t[0] < 0 or t[0] >= 604800 or t[-1] >= 1209600:
                    raise ValueError(f'{Path(track.input.path).name}: invalid trajectory week seconds')
                track.time = t + (_week(week)*604800 - 1e9)
    inventory = dict(clouds=clouds, trajectories=[], points=total, matched=0,
                     unmatched=0, ambiguous=0, crs=crs.to_string(), strips=[])
    for t in tracks:
        inventory['trajectories'].append(dict(path=str(Path(t.input.path).resolve()), line=t.line,
            records=len(t.records), time=[float(t.time[0]),float(t.time[-1])],
            gaps=int((np.diff(t.time) > project.max_gap).sum()), native=t.native))
    parts, assignments, sources, offset, counts = [], [], [], 0, {}
    for c in clouds:
        _check_cancel(cancel)
        _unchanged(c)
        log(f"Importing: {Path(c['path']).name} ({c['points']:,} points)")
        sources.append(slice(offset, offset+c['points']))
        offset += c['points']
        c.update(matched=0, unmatched=0, ambiguous=0)
        read_count = 0
        with laspy.open(c['path']) as reader:
            for chunk in reader.chunk_iterator(500_000):
                _check_cancel(cancel)
                read_count += len(chunk)
                p = {k: np.array(chunk[k]) for k in ('x','y','z','classification','point_source_id')}
                if not all(np.isfinite(p[k]).all() for k in ('x','y','z')):
                    raise ValueError(f"{c['path']}: nonfinite point coordinates")
                sid = p['point_source_id']
                if (sid == 0).any():
                    raise ValueError(f"{c['path']}: point_source_id 0 has no flight-line identity; assign IDs before project import")
                chosen = np.full(len(chunk), -1, dtype=np.int32)
                hits = np.zeros(len(chunk), dtype=np.int32)
                if tracks:
                    p['gps_time'] = _point_times(chunk.gps_time,c['gps_type'],project)
                    for j, t in enumerate(tracks):
                        if c['path'] in bindings and bindings[c['path']] != track_paths[j]:
                            continue
                        mask = _coverage(t.time,p['gps_time'],project.max_gap)
                        if t.line is not None:
                            mask &= sid == t.line
                        chosen[mask & (hits == 0)] = j
                        hits[mask] += 1
                    chosen[hits > 1] = -2
                    for name,mask in (('matched',hits==1),('unmatched',hits==0),('ambiguous',hits>1)):
                        n = int(mask.sum()); inventory[name] += n; c[name] += n
                pairs, ns = np.unique(np.column_stack([chosen,sid]),axis=0,return_counts=True)
                for (j,s), n in zip(pairs,ns):
                    key = int(j),int(s)
                    item = counts.setdefault(key, dict(count=0, clouds=set()))
                    item['count'] += int(n); item['clouds'].add(c['path'])
                if chunk_sink is not None:
                    chunk_sink(p,chosen)
                if keep_points:
                    parts.append(p); assignments.append(chosen)
        if read_count != c['points']:
            raise ValueError(f"{c['path']}: point count differs from the header")
        _unchanged(c)
    if not tracks and not project.shared_strip_ids:
        repeated = [s for (_,s),value in counts.items() if len(value['clouds'])>1]
        if repeated:
            raise ValueError(f'line IDs {repeated} repeat across clouds without trajectories; '
                             'confirm they identify the same flights across tiles, or add trajectories')
    for j,t in enumerate(inventory['trajectories']):
        t['matched_points'] = sum(v['count'] for (k,_),v in counts.items() if k==j)
        if not t['matched_points']: log(f"Unused trajectory: {t['path']}")
    points = {k:np.concatenate([p[k] for p in parts]) for k in parts[0]} if keep_points else None
    assignment = np.concatenate(assignments) if keep_points else None
    for internal, ((j,s), item) in enumerate(sorted(counts.items()),1):
        # Retain original ID separately; only this analysis array is remapped.
        if keep_points:
            if 'original_point_source_id' not in points:
                points['original_point_source_id'] = points['point_source_id'].copy()
                points['point_source_id'] = np.empty(total,dtype=np.int64)
            mask = (assignment == j) & (points['original_point_source_id'] == s)
            points['point_source_id'][mask] = internal
        inventory['strips'].append(dict(id=internal, source_id=s, trajectory=j,
            trajectory_path=track_paths[j] if j >= 0 else None, points=item['count'],
            clouds=sorted(item['clouds'])))
    log(f"Project: {len(clouds)} clouds, {len(tracks)} trajectories, {len(counts)} analysis strips")
    if tracks:
        log(f"Trajectory matches: {inventory['matched']:,}; unmatched: {inventory['unmatched']:,}; ambiguous: {inventory['ambiguous']:,}")
    return LoadedProject(project,crs,inventory,tracks,points,assignment,sources)


def _report(data, out, *, control=None):
    from pyargus.qa import report
    unit = data.crs.axis_info[0].unit_name
    # Algorithms' cell/radius values are in map units, as in single-cloud QA.
    result = report.generate(data.points,out,title='pyArgus project',control=control,units=unit)
    (Path(out)/'inventory.json').write_text(json.dumps(data.inventory,indent=2),encoding='utf-8')
    rows = ['<section><h2>Project inputs and trajectory matching</h2>',
            f"<p>{data.inventory['matched']:,} matched; {data.inventory['unmatched']:,} unmatched; "
            f"{data.inventory['ambiguous']:,} ambiguous returns.</p>" if data.tracks else
            '<p>No trajectories supplied. Equal flight-line IDs across files are treated as the same strip.</p>',
            '<p>Strip numbers in this report are internal analysis IDs. Exported LAS flight-line IDs are preserved.</p>',
            '<table><tr><th>Analysis strip</th><th>LAS line ID</th><th>Trajectory</th><th>Clouds</th></tr>']
    for s in data.inventory['strips']:
        rows.append(f"<tr><td>{s['id']}</td><td>{s['source_id']}</td><td>"
            f"{html.escape(s['trajectory_path'] or ('ambiguous' if s['trajectory']==-2 else 'unmatched / none'))}</td>"
            f"<td>{html.escape('; '.join(s['clouds']))}</td></tr>")
    rows.append('</table><p>Matching time and line IDs does not establish absolute accuracy.</p></section>')
    path = Path(out)/'report.html'
    page = path.read_text(encoding='utf-8')
    # Append within the report's outer container; all source text is escaped.
    page = page.rsplit('</div>',1)[0] + '\n'.join(rows) + '</div>'
    path.write_text(page,encoding='utf-8')
    from pyargus.analysis_records import plain
    (Path(out)/'summary.json').write_text(json.dumps(plain(dict(result, report='report.html')), indent=2, allow_nan=False), encoding='utf-8')
    return result


def _target(out):
    out = Path(out).resolve()
    if out.exists():
        raise ValueError(f'output already exists: {out}; choose a new folder')
    if not out.parent.is_dir():
        raise ValueError('output parent folder does not exist')
    return out


def _qa_impl(project, out, *, control=None, log=lambda text: None, cancel=lambda: False):
    _, headers = _cloud_headers(project)
    if sum(h['points'] for h in headers) > project.max_points:
        from pyargus.large_qa import qa as large_qa
        return large_qa(project,out,control=control,log=log,cancel=cancel)
    out = _target(out)
    data = load(project,keep_points=True,log=log,cancel=cancel)
    if data.tracks and (data.inventory['unmatched'] or data.inventory['ambiguous']):
        raise ValueError('project QA refused: unresolved trajectory matches; use Inspect / match '
                         'and resolve missing or ambiguous matches before comparing strips')
    _check_cancel(cancel)
    with tempfile.TemporaryDirectory(prefix='.pyargus-qa-',dir=out.parent) as temp:
        result = _report(data,temp,control=control)
        project.save(Path(temp)/'project.json')
        _check_cancel(cancel)
        Path(temp).rename(out)
    result['report'] = str(out/'report.html')
    log(f"Project QA: {out/'report.html'}")
    return result


def _align_impl(project, out, *, cell=6., min_points=6, solve_boresight=True,
          control=None, log=lambda text: None, cancel=lambda: False):
    from pyargus.align import attach, solve_alignment
    from pyargus.formats.las import drop_copc_records
    import laspy
    out = _target(out)
    if not project.trajectories:
        raise ValueError('project alignment requires trajectories')
    data = load(project,keep_points=True,log=log,cancel=cancel)
    if any(not t.native for t in data.tracks) and project.vertical is not None:
        if isinstance(project.vertical,str):
            import pyproj
            vertical_crs=pyproj.CRS.from_user_input(project.vertical)
            if not vertical_crs.is_vertical:
                raise ValueError('SBET vertical setting must be a vertical CRS or geoid N in meters')
            if not np.isclose(vertical_crs.axis_info[0].unit_conversion_factor,
                              data.crs.axis_info[0].unit_conversion_factor,rtol=1e-12,atol=0):
                raise ValueError('SBET vertical CRS units differ from LAS XYZ units; choose a matching vertical CRS')
        elif not np.isfinite(project.vertical):
            raise ValueError('SBET geoid undulation must be finite')
    inv, pts = data.inventory,data.points
    if inv['unmatched'] or inv['ambiguous']:
        raise ValueError(f"alignment refused: {inv['unmatched']:,} unmatched and "
                         f"{inv['ambiguous']:,} ambiguous returns; inspect the project and resolve matching first")
    ground = pts['classification'] == 2
    missing = set(np.unique(pts['point_source_id'])) - set(np.unique(pts['point_source_id'][ground]))
    if missing:
        raise ValueError(f'no ground points in analysis strip(s) {sorted(missing)}; classify first')
    bundles, ids, attached_tracks = [], [], {}
    for j,t in enumerate(data.tracks):
        _check_cancel(cancel)
        mask = (data.assignments==j) & ground
        if not mask.any():
            continue
        records,xyz,_ = trajectory.load_alignment(t.input.path,data.crs,vertical=project.vertical,
            allow_network=project.allow_network,trj_time=t.input.time_mode,trj_confirmed=t.input.confirmed)
        path=Path(t.input.path)
        if t.signature != (path.stat().st_size,path.stat().st_mtime_ns):
            raise ValueError(f'{path.name}: trajectory changed after matching; restart the job')
        records = records.copy(); records['time'] = t.time
        sub = {k:v[mask] for k,v in pts.items() if k!='original_point_source_id'}
        a = attach.bundles_from_cloud(sub,records,*xyz,time_mode='same')
        bundles.extend(a.bundles); ids.extend(a.strip_ids)
        attached_tracks[j] = records,xyz,a.heading_source
        log(f"Attached {Path(t.input.path).name}: {len(a.bundles)} strips; track error {np.degrees(a.track_error):.2f} degrees")
    if len(bundles)<2:
        raise ValueError('alignment requires at least two overlapping flight lines')
    _check_cancel(cancel)
    log('Solving all matched strips together')
    result = solve_alignment(bundles,cell=cell,min_points=min_points,solve_boresight=solve_boresight,
                             control=control)
    offsets = {sid:result.offsets[i] for i,sid in enumerate(ids)}
    corrected = np.column_stack([pts[k] for k in ('x','y','z')])
    for j,(records,xyz,heading) in attached_tracks.items():
        _check_cancel(cancel)
        mask = data.assignments==j
        sub = {k:v[mask] for k,v in pts.items() if k!='original_point_source_id'}
        corrected[mask], skipped = attach.apply_corrections(sub,records,*xyz,heading,
                                    result.boresight,offsets,time_mode='same')
        if skipped:
            raise ValueError('correction coverage changed after matching; refusing partial export')
    output_map = []
    with tempfile.TemporaryDirectory(prefix='.pyargus-align-',dir=out.parent) as temp:
        temp = Path(temp)
        log('Writing before-adjustment QA')
        _report(data,temp/'before',control=None if control is None else
                (np.arange(len(control)),control[:,0],control[:,1],control[:,2]))
        for index,(metadata,rows) in enumerate(zip(inv['clouds'],data.sources),1):
            _check_cancel(cancel)
            _unchanged(metadata)
            source = metadata['path']
            name = f'{index:04d}_{Path(source).stem}_adjusted{Path(source).suffix.lower()}'
            dest = temp/name
            log(f'Writing {name}')
            cloud = laspy.read(source)
            cloud.x,cloud.y,cloud.z = corrected[rows].T
            # a COPC source is written as a plain cloud: laspy cannot write
            # its octree records, and moved points would falsify them anyway
            drop_copc_records(cloud.header)
            cloud.write(dest)
            # Evaluate the actual quantized exported coordinates, not solver predictions.
            written = laspy.read(dest)
            for k in ('x','y','z'):
                pts[k][rows] = np.asarray(written[k])
            output_map.append(dict(source=str(Path(source).resolve()),output=name))
        _check_cancel(cancel)
        log('Writing after-adjustment QA from exported coordinates')
        _report(data,temp/'after',control=None if control is None else
                (np.arange(len(control)),control[:,0],control[:,1],control[:,2]))
        project.save(temp/'project.json')
        summary = dict(outputs=output_map,boresight=result.boresight.tolist(),
            offsets={str(k):v.tolist() for k,v in offsets.items()},inventory=inv,
            parameters=dict(cell=cell,min_points=min_points,solve_boresight=solve_boresight,offsets='z'),
            patch_rms_before=result.rms_before,patch_rms_after=result.rms_after,
            accuracy='relative strip adjustment; absolute accuracy requires independent checkpoints')
        (temp/'alignment.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        _check_cancel(cancel)
        temp.rename(out)
    log(f'Wrote {len(output_map)} corrected clouds and before/after QA: {out}')
    return summary


def qa(project, out, *, control=None, log=lambda text: None, cancel=lambda: False):
    from pyargus.analysis_records import analysis_job, finish, project_settings, defaults
    inputs = list(project.clouds) + [t.path for t in project.trajectories]
    from pyargus.qa.report import generate
    settings = project_settings(project, control, report_defaults=defaults(generate))
    with analysis_job("project-qa", out, settings, inputs=inputs, log=log) as record:
        result = _qa_impl(project, out, control=control, log=log, cancel=cancel)
        finish(record, result, outputs=[Path(out)/"report.html", Path(out)/"summary.json", Path(out)/"project.json"])
        return result


def align(project, out, *, cell=6., min_points=6, solve_boresight=True,
          control=None, log=lambda text: None, cancel=lambda: False):
    from pyargus.analysis_records import analysis_job, finish, project_settings, defaults
    inputs = list(project.clouds) + [t.path for t in project.trajectories]
    from pyargus.align import solve_alignment
    settings = project_settings(project, control, solver_defaults=defaults(solve_alignment), cell=cell, min_points=min_points,
                                solve_boresight=solve_boresight, offsets="z")
    with analysis_job("project-align", out, settings, inputs=inputs, log=log) as record:
        result = _align_impl(project, out, cell=cell, min_points=min_points,
                             solve_boresight=solve_boresight, control=control, log=log, cancel=cancel)
        outputs = [Path(out)/item["output"] for item in result["outputs"]]
        outputs += [Path(out)/"alignment.json", Path(out)/"before"/"summary.json", Path(out)/"after"/"summary.json"]
        finish(record, dict(result, corrections_written=True,
                           before_qa=json.loads((Path(out)/"before"/"summary.json").read_text()),
                           after_qa=json.loads((Path(out)/"after"/"summary.json").read_text())), outputs=outputs)
        return result
