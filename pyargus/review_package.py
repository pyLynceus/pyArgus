"""Offline review archives. External datasets are inspected by metadata only."""
from copy import deepcopy
import csv
import hashlib
import html
import io
import json
import os
from pathlib import Path
import platform
import tempfile
import uuid
import zipfile

from pyargus import __version__
from pyargus.job_manifest import utc_now
from pyargus.review_memory import ReviewMemory, validate_state
from pyargus.workspace_state import Tracker, STAGES

MAX_MEMBER_BYTES = 128 * 1024**2
MAX_TOTAL_BYTES = 512 * 1024**2


def stopped(cancel):
    if cancel():
        raise InterruptedError('Review package stopped; no archive published.')


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')


def csv_bytes(headings, rows):
    """Quote cells and neutralize spreadsheet formula prefixes in textual fields."""
    def cell(value):
        if value is None:
            return ''
        if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n'))):
            return "'"+value
        return value
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(headings)
    for row in rows:
        writer.writerow([cell(value) for value in row])
    return stream.getvalue().encode('utf-8-sig')


def collect_sources(snapshot):
    data = snapshot['workspace']; sources = {}

    def add(path, role, expected=None):
        if not path:
            return
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError('Review package references require absolute paths.')
        path = str(Path(path).resolve())
        row = sources.setdefault(path, dict(path=path, roles=[], expectations=[]))
        if role not in row['roles']:
            row['roles'].append(role)
        if expected is not None:
            item = dict(role=role, size_bytes=expected.get('size_bytes'), mtime_ns=expected.get('mtime_ns'))
            if item not in row['expectations']:
                row['expectations'].append(item)

    def view(state, role):
        if not state:
            return
        for source in state['inputs']:
            add(source['path'], role, source)
        for reference in state.get('references', []):
            source = reference['source']; add(source['path'], role+' / DXF reference', source)

    add(snapshot.get('workspace_path'), 'Workspace file')
    for layer in data.get('layers', []):
        add(layer['path'], 'Registered '+layer['kind'])
    for path in data.get('project', {}).get('clouds', []):
        add(path, 'Processing cloud')
    for trajectory in data.get('project', {}).get('trajectories', []):
        add(trajectory['path'], 'Processing trajectory')
    for path, version in data.get('cloud_versions', {}).items():
        add(path, 'Recorded cloud version')
        add(version.get('root'), 'Lineage original'); add(version.get('parent'), 'Lineage parent')
    for job in data.get('jobs', []):
        for key in ('inputs', 'outputs'):
            for path, size, modified in job.get(key, []):
                add(path, job['stage']+' '+job['id']+' / '+key,
                    dict(size_bytes=size, mtime_ns=modified) if size is not None and modified is not None else None)
        for path in job.get('records', []):
            add(path, 'External job record '+job['id'])
    notes = snapshot['review_notes']
    for row in [*notes['views'], *notes['issues']]:
        view(row['view'], ('Issue I-%03d' % row['number']) if 'number' in row else 'Saved view '+row['title'])
    view(notes.get('last_review'), 'Resume Review'); view(snapshot.get('current_view', {}).get('state'), 'Current display')
    for layer in data.get('linework', []):
        add(layer['source']['path'], 'Imported linework', layer['source'])
    for feature in data.get('features', []):
        for vertex in feature['vertices']:
            add(vertex['source']['path'], 'Feature '+feature['name'], vertex['source'])
    for path in (data.get('active_cloud'), data.get('trajectory')):
        add(path, 'Selected task input')
    comparison = snapshot.get('comparison', {})
    for key in ('original', 'result'):
        add(comparison.get('preferences', {}).get(key), 'Comparison '+key)
    for source in snapshot.get('section', {}).get('inputs', []):
        add(source['path'], 'Extracted section', source)
    for source in comparison.get('prepared', {}).get('inputs', []):
        add(source['path'], 'Prepared comparison', source)
    for step in comparison.get('prepared', {}).get('jobs', []):
        for key in ('source', 'result'):
            path, size, modified = step[key]
            add(path, 'Prepared comparison lineage', dict(size_bytes=size, mtime_ns=modified))
    for row in snapshot.get('header_inventory', []):
        if row.get('source'):add(row['path'], 'Cached header inventory', row['source'])
    return list(sources.values())


def observe(path):
    try:
        stat = Path(path).stat()
        return dict(kind='Directory' if Path(path).is_dir() else 'File', size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
    except FileNotFoundError:
        return dict(kind='Missing', error='Reference is missing or unavailable.')
    except OSError as exc:
        return dict(kind='Unavailable', error=str(exc))


def inspect_sources(rows, cancel=lambda: False, progress=lambda text: None):
    for i, row in enumerate(rows):
        stopped(cancel); progress(f'Checking reference {i+1}/{len(rows)}: {Path(row["path"]).name}')
        row['observed'] = observe(row['path'])
        row['status'] = row['observed']['kind'] if row['observed']['kind'] in ('Missing', 'Unavailable') else 'Available'
        for item in row['expectations']:
            item['status'] = row['status'] if row['status'] != 'Available' else 'Matches recorded metadata' if all(
                item[k] == row['observed'][k] for k in ('size_bytes', 'mtime_ns')) else 'Changed since recording'
        changed = sum(item['status'] == 'Changed since recording' for item in row['expectations'])
        row['changed_records'] = changed
        if changed:
            row['status'] = f'Changed for {changed} recorded reference(s)'
    return rows


def view_status(state, sources, references):
    if state is None:
        return ['No captured view']
    warnings = []
    for recorded in [*state['inputs'], *[r['source'] for r in state.get('references', [])]]:
        observed = sources[recorded['path']]['observed']
        if observed['kind'] in ('Missing', 'Unavailable'):
            warnings.append(observed['kind']+': '+recorded['path'])
        elif any(observed[k] != recorded[k] for k in ('size_bytes', 'mtime_ns')):
            warnings.append('Changed: '+recorded['path'])
    for ref in state.get('references', []):
        if references.get(ref['id']) != ref['source']:
            warnings.append('Reference layer not registered with this identity: '+ref['id'])
    return warnings


def prepare_report(snapshot, cancel=lambda: False, progress=lambda text: None):
    snapshot = deepcopy(snapshot)
    notes = ReviewMemory(snapshot.get('review_notes')).data; snapshot['review_notes'] = notes
    if snapshot.get('current_view', {}).get('state') is not None:
        snapshot['current_view']['state'] = validate_state(snapshot['current_view']['state'])
    sources = inspect_sources(collect_sources(snapshot), cancel, progress)
    index = {s['path']:s for s in sources}
    registered = {r['id']:r['source'] for r in snapshot['workspace'].get('linework', [])}
    contexts = []
    for kind in ('views', 'issues'):
        for row in notes[kind]:
            contexts.append(dict(id=row['id'], kind=kind, warnings=view_status(row['view'], index, registered)))
    current = snapshot.get('current_view', {})
    if current.get('state'):
        current['source_warnings'] = view_status(current['state'], index, registered)
    tracker = Tracker(deepcopy(snapshot['workspace'])); attempts = []
    settings = snapshot.get('current_settings', {})
    for job in tracker.data['jobs']:
        stopped(cancel)
        try:
            status = tracker.job_status(job, settings.get(job['id']))
            why = tracker.stale_reason(job, settings.get(job['id'])) if status == 'Outdated' else ''
        except (KeyError, TypeError, ValueError) as exc:
            status, why = 'Unverified record', str(exc)
        attempts.append(dict(id=job['id'], stage=job['stage'], recorded_status=job['status'], current_status=status,
            reason=why or '', started=job.get('started', ''), elapsed=job.get('elapsed', 0), error=job.get('error'),
            settings=deepcopy(job.get('settings', {})), inputs=job.get('inputs', []), outputs=job.get('outputs', []),
            external_records=job.get('records', []), notes=job.get('notes', []),
            settings_checked=job['id'] in settings and settings[job['id']] is not None))
    stages = []
    for stage in STAGES:
        stopped(cancel)
        try:
            status = tracker.status(stage, lambda j:settings.get(j['id']))
        except (KeyError, TypeError, ValueError):
            status = 'Unverified record'
        reasons = sorted({a['reason'] for a in attempts if a['stage'] == stage and a['reason']})
        stages.append(dict(stage=stage, status=status, detail='; '.join(reasons)))
    from pyargus.project_overview import workflow_summary
    project = snapshot['workspace'].get('project', {})
    try:
        workflow = workflow_summary(tracker, [(s['stage'],s['status'],s['detail']) for s in stages],
            project.get('clouds', []), lambda j:settings.get(j['id']),
            missing_clocks=sum(t.get('time_mode') not in ('same','week') for t in project.get('trajectories', [])),
            issues=sum(i['state'] != 'Resolved' for i in notes['issues']))
    except (KeyError, TypeError, ValueError) as exc:
        workflow = dict(headline='Review workspace records', detail=str(exc), coverage='Unavailable')
    return dict(schema_version=1, package_id=uuid.uuid4().hex, created_utc=utc_now(), captured_utc=snapshot.get('captured_utc'),
        title=snapshot.get('title') or 'pyArgus QA review', operator_note=snapshot.get('operator_note', ''),
        workspace_path=snapshot.get('workspace_path'), software=snapshot.get('software') or dict(pyargus=__version__, python=platform.python_version()),
        scope=dict(external_payloads_included=False, source_identity_method='size_and_mtime',
            status_basis='Recorded workflow decisions and current metadata/settings; no new numerical QA or accuracy certification.'),
        sources=sources, stages=stages, attempts=attempts, decisions=deepcopy(tracker.data['decisions']),
        workflow=workflow, contexts=contexts, current_view=current, section=snapshot.get('section', {}),
        comparison=snapshot.get('comparison', {}), header_inventory=snapshot.get('header_inventory', []),
        review_notes=notes, workspace=deepcopy(snapshot['workspace']))


def render_html(report, previews, section_csv):
    e = lambda value:html.escape(str(value if value is not None else ''), quote=True)
    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(
            '<tr>'+''.join('<td>'+e(cell)+'</td>' for cell in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    links = [('package.json','Export summary / source checks'),('workspace-snapshot.argus.json','Workspace snapshot'),
        ('review-notes.json','Review notes'),('sources.csv','Source inventory'),('issues.csv','Issue register'),
        ('stages.csv','Stage summary'),('attempts.csv','Attempt history'),('manifest.json','Package integrity manifest')]
    notes = report['review_notes']; contexts = {r['id']:r['warnings'] for r in report['contexts']}
    issues = ''.join('<article><h3>'+e('I-%03d — ' % r['number']+r['title'])+'</h3><p>'+e(r['category']+' · '+r['state'])+'</p><p class="note">'+e(r['note'])+'</p><p>'+e(
        ('Displayed sample point' if r['anchor']['kind']=='picked-sample' else 'Approximate camera-plane location')+': '+', '.join(f'{x:.3f}' for x in r['anchor']['xyz']))+'</p><p>'+e(
        'Context: '+('; '.join(contexts[r['id']]) or 'Recorded source metadata matches at export.'))+'</p><details><summary>View settings and references</summary><pre>'+e(json.dumps(r['view'], indent=2, ensure_ascii=False))+'</pre></details></article>' for r in notes['issues']) or '<p>No issues recorded.</p>'
    views = ''.join('<details><summary>'+e(r['title'])+'</summary><p>'+e('; '.join(contexts[r['id']]) or 'Recorded source metadata matches at export.')+'</p><pre>'+e(json.dumps(r['view'], indent=2, ensure_ascii=False))+'</pre></details>' for r in notes['views']) or '<p>No named views recorded.</p>'
    images = ''.join('<figure><img src="'+e(name)+'" alt="'+e(meta['caption'])+'"><figcaption>'+e(meta['caption'])+'</figcaption></figure>' for name, meta in previews.items())
    source_rows = [(s['path'], '; '.join(s['roles']), s['status'], s['observed'].get('kind'), s['observed'].get('size_bytes'),
        s['observed'].get('error', '')) for s in report['sources']]
    workflow = report['workflow']; comparison = report['comparison']
    counts = f'{len(notes["issues"])} issues · {sum(r["state"]!="Resolved" for r in notes["issues"])} unresolved · {len(notes["views"])} saved views · {len(report["attempts"])} recorded attempts'
    section = report['section']; section_text = '<pre>'+e(json.dumps(section, indent=2, ensure_ascii=False))+'</pre>' if section else '<p>No extracted section captured.</p>'
    if section_csv:
        section_text += '<p><a href="section-sample.csv">Extracted section sample CSV</a> — all sampled inputs/classes/lines, independent of display filters; not a full-cloud export.</p>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\' data:; style-src \'unsafe-inline\'">'
        '<title>'+e(report['title'])+'</title><style>body{font:15px/1.5 system-ui,sans-serif;color:#182b3c;background:#f4f7f9;margin:0}main{max-width:1250px;margin:auto;padding:28px}h1{margin:0}h2{margin-top:32px}a{color:#075a8c}p,td,pre{overflow-wrap:anywhere}.summary,article,details{background:white;border:1px solid #cdd9df;border-radius:6px;padding:12px;margin:12px 0}.notice{background:#fff4d9;padding:14px;border-left:4px solid #c6932b}.note{white-space:pre-wrap}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:white;font-size:13px}td,th{text-align:left;padding:9px;border:1px solid #d6e0e5;vertical-align:top}th{background:#e4edf2}pre{white-space:pre-wrap;max-height:420px;overflow:auto;font-size:12px}img{max-width:100%;height:auto}figure{margin:12px 0}figcaption{font-size:13px;color:#455969}nav{display:flex;gap:12px;flex-wrap:wrap}@media print{body{background:white}main{padding:0}.scroll,pre{overflow:visible;max-height:none}details{break-inside:avoid}table{font-size:10px}}</style></head><body><main>'
        '<h1>'+e(report['title'])+'</h1><p>Exported '+e(report['created_utc'])+' · Package '+e(report['package_id'])+'</p>'
        '<p class="notice">Review records and source references only. External LAS/LAZ, trajectories, DXF, surfaces and report contents are not copied. Extract this ZIP, then open report.html. Source checks use size and modification time. Accepted/Resolved are operator decisions, not survey accuracy certification.</p>'
        '<nav><a href="#issues">Issues</a><a href="#views">Saved views</a><a href="#stages">Stage history</a><a href="#sources">Sources</a><a href="#files">Package files</a></nav>'
        '<section class="summary"><h2>Project status</h2><p>'+e(counts)+'</p><h3>'+e(workflow['headline'])+'</h3><p>'+e(workflow['detail'])+'</p><p>'+e(workflow['coverage'])+'</p><p class="note">'+e(report['operator_note'])+'</p><p>Workspace: '+e(report['workspace_path'])+'</p><p>Software: '+e(json.dumps(report['software'], ensure_ascii=False))+'</p></section>'
        '<h2>Current display</h2><p>'+e(report['current_view'].get('warning', '') or 'Captured current view only. Saved views below are definitions; no cloud reload or screenshot replay was performed.')+'</p>'+images+
        '<details><summary>Current view / sample settings</summary><pre>'+e(json.dumps(report['current_view'], indent=2, ensure_ascii=False))+'</pre></details>'
        '<h2>Version comparison</h2><pre>'+e(json.dumps(comparison, indent=2, ensure_ascii=False))+'</pre>'
        '<h2>Extracted section</h2>'+section_text+'<h2 id="issues">Issue register</h2>'+issues+'<h2 id="views">Saved views</h2>'+views+
        '<h2 id="stages">Stage summary at export</h2>'+table(('Stage','Current status','Notes'),[(s['stage'],s['status'],s['detail']) for s in report['stages']])+
        '<h3>Attempt history</h3>'+table(('Stage','Started UTC','Recorded status','Current status','Reason/error','Elapsed s','Attempt ID'),
            [(a['stage'],a['started'],a['recorded_status'],a['current_status'],a['reason'] or a['error'],a['elapsed'],a['id']) for a in report['attempts']])+
        '<h3>Review decisions</h3>'+table(('Stage','Decision','Note','UTC'),[(d['stage'],d['decision'],d['note'],d['time']) for d in report['decisions']])+
        '<h2>Cached header inventory</h2><p>Existing overview metadata, not refreshed or scanned during this export. Header bounds are rectangles, not occupied coverage or accuracy evidence.</p>'+table(('Cloud','Header points','CRS / units','Header warning'),[(r['path'],r.get('points'),str(r.get('crs_name',''))+' / '+str(r.get('units','')),r.get('error')) for r in report['header_inventory']])+
        '<h2 id="sources">Source inventory</h2><p>Available means accessible at export, not validated accuracy. A changed identity may belong to an older attempt. Each recorded expectation is retained in package.json. Missing/unavailable sources remain in the report. Absolute paths require access to the original storage.</p>'+table(('Path','Roles','Metadata status','Type','Bytes at export','Access error'),source_rows)+
        '<h2 id="files">Package files</h2><ul>'+''.join('<li><a href="'+e(path)+'">'+e(label)+'</a></li>' for path,label in links)+'</ul>'
        '<p>Stage statuses are computed from metadata and the current settings captured by this GUI where available; attempts with no current settings retain a settings_checked=false flag. Source observations are at export time. Workspace autosaves may continue after the in-memory snapshot was captured.</p>'
        '<p>The workspace snapshot can be opened in pyArgus when its original paths are accessible. It is not a portable copy of the project data. Unsaved issue editor text is excluded; Apply note before exporting.</p></main></body></html>').encode('utf-8')


def section_chunks(section):
    headings = ['x','y','z','station','across','classification','line','file','source_path','source_point_index']
    yield csv_bytes(headings, [])
    for offset in range(0, len(section.points), 1000):
        rows = []
        for i in range(offset, min(offset+1000, len(section.points))):
            file_id = int(section.files[i])
            rows.append([*map(float,section.points[i]),int(section.classes[i]),int(section.lines[i]),file_id,
                section.inputs[file_id]['path'],int(section.point_indices[i])])
        # Strip the per-chunk BOM and empty header; the archive has a single header/BOM.
        data = csv_bytes([], rows).decode('utf-8-sig').split('\r\n', 1)[1]
        yield data.encode('utf-8')


def export_package(target, snapshot, *, previews=None, section=None, cancel=lambda: False, progress=lambda text: None):
    """Publish a new ZIP only after every member and metadata check succeeds."""
    target = Path(target).resolve()
    if target.suffix.lower() != '.zip' or not target.parent.is_dir():
        raise ValueError('Choose a ZIP file in an existing output folder.')
    if target.exists():
        raise ValueError('Choose a new filename; review-package export does not overwrite files.')
    stopped(cancel); report = prepare_report(snapshot, cancel, progress)
    if str(target) in {s['path'] for s in report['sources']}:
        raise ValueError('Choose a separate package file, outside the referenced source paths.')
    preview_meta = {}; previews = previews or {}
    current_warnings = report['current_view'].get('source_warnings', [])
    if current_warnings and previews:
        raise ValueError('Current display sources changed; reload before exporting previews, or export records without previews.')
    for name, item in previews.items():
        if name not in ('current-cloud.png','current-profile.png') or not isinstance(item['data'], bytes) or not item['data'].startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid review preview.')
        preview_meta[name] = dict(caption=item['caption'])
    if section is not None:
        expected = report['section'].get('inputs')
        if expected != section.inputs or report['section'].get('sampled') != len(section.points):
            raise ValueError('Section sample differs from captured section metadata.')
        for recorded in section.inputs:
            observed = next(r for r in report['sources'] if r['path'] == recorded['path'])['observed']
            if any(observed.get(k) != recorded[k] for k in ('size_bytes','mtime_ns')):
                raise ValueError('Extracted section source changed; re-extract before including its sample.')
    report['previews'] = preview_meta; report['section_sample_included'] = section is not None
    metadata = {k:v for k,v in report.items() if k not in ('workspace','review_notes')}
    issue_rows = [(f'I-{r["number"]:03d}',r['title'],r['category'],r['state'],r['note'],r['anchor']['kind'],*r['anchor']['xyz'],
        '; '.join(next(c['warnings'] for c in report['contexts'] if c['id']==r['id']))) for r in report['review_notes']['issues']]
    entries = {
        'report.html':[render_html(report, preview_meta, section is not None)],
        'package.json':[json_bytes(metadata)], 'workspace-snapshot.argus.json':[json_bytes(report['workspace'])],
        'review-notes.json':[json_bytes(report['review_notes'])],
        'sources.csv':[csv_bytes(('path','roles','status','kind','size_bytes','mtime_ns','changed_records'),
            [(s['path'],'; '.join(s['roles']),s['status'],s['observed']['kind'],s['observed'].get('size_bytes'),s['observed'].get('mtime_ns'),s['changed_records']) for s in report['sources']])],
        'issues.csv':[csv_bytes(('issue','title','category','state','note','anchor_kind','x','y','z','context_warnings'),issue_rows)],
        'stages.csv':[csv_bytes(('stage','current_status','detail'),[(s['stage'],s['status'],s['detail']) for s in report['stages']])],
        'attempts.csv':[csv_bytes(('attempt_id','stage','started','recorded_status','current_status','reason','elapsed_seconds'),
            [(a['id'],a['stage'],a['started'],a['recorded_status'],a['current_status'],a['reason'],a['elapsed']) for a in report['attempts']])],
        'README.txt':[b'Extract this ZIP, then open report.html. No external datasets or report contents are copied. Absolute references require the original storage. Source identities use size/mtime; manifest hashes cover archive members only. Review decisions do not certify accuracy.\n'],
        **{name:[item['data']] for name,item in previews.items()}}
    if section is not None:
        entries['section-sample.csv'] = section_chunks(section)
    temporary = None; files = []; total = 0
    try:
        stopped(cancel)
        with tempfile.NamedTemporaryFile(prefix='.'+target.stem+'-',suffix='.tmp',dir=target.parent,delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, chunks in entries.items():
                stopped(cancel); progress('Writing '+name); digest=hashlib.sha256(); size=0
                with archive.open(name, 'w') as member:
                    for chunk in chunks:
                        stopped(cancel); size += len(chunk); total += len(chunk)
                        if size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                            raise ValueError('Review package exceeds its bounded export limit.')
                        member.write(chunk); digest.update(chunk)
                files.append(dict(path=name,size_bytes=size,sha256=digest.hexdigest()))
            archive.writestr('manifest.json',json_bytes(dict(schema_version=1,package_id=report['package_id'],files=files,
                note='SHA256 covers packaged members; manifest excludes itself. External source contents are not hashed.')))
        # File references must remain stable through publication. Directories are metadata-only inventory.
        for source in report['sources']:
            stopped(cancel)
            if source['path'] != report['workspace_path'] and source['observed']['kind'] != 'Directory' and observe(source['path']) != source['observed']:
                raise ValueError('Reference changed during export; retry: '+source['path'])
        stopped(cancel)
        if os.name == 'nt':
            os.rename(temporary, target)  # Windows rename fails if a competing target already exists.
        else:
            os.link(temporary, target); temporary.unlink()  # No replace/overwrite race on POSIX.
        return dict(path=str(target),package_id=report['package_id'],created_utc=report['created_utc'],members=len(files)+1,
            issues=len(report['review_notes']['issues']),views=len(report['review_notes']['views']),
            warnings=sum(s['status']!='Available' for s in report['sources']))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
