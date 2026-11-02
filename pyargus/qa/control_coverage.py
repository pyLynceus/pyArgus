"""Read-only control/PID coverage screening; never supplies observations to a solve."""
from pathlib import Path
import csv
import html
import json
import numpy as np
from pyargus.core.units import M_PER_US_SURVEY_FOOT
from pyargus.analysis_records import plain

PRODUCTS = ('control_coverage.json', 'control_coverage_flights.csv',
            'control_coverage_points.csv', 'control_coverage.svg')
ROLES = ('fitting_control', 'reference', 'independent', 'excluded')


def collect(points, inventory, config, metres_per_unit, *, references=None,
            fitting_control=None, checks=(), cancel=lambda: False):
    """Audit ORIGINAL ground geometry, retaining every supplied survey location.

    Local support follows the report's OLS/hull gates, not the solver's different
    patch gates. A declared fitting control is not evidence of solver membership.
    """
    from pyargus.qa.alignment_report import assess
    from pyargus.project import _check_cancel
    if not np.isfinite(metres_per_unit) or metres_per_unit <= 0:
        raise ValueError('Control coverage requires finite positive cloud length units')
    fit = np.asarray(fitting_control if fitting_control is not None else [], dtype=float)
    if fit.size == 0:
        fit = np.empty((0, 3))
    if fit.ndim != 2 or fit.shape[1] != 3 or not np.isfinite(fit).all():
        raise ValueError('Fitting control must contain finite E/N/Z coordinates')
    locations, labels = [], []
    if references is not None:
        for name, xyz in zip(references['ids'], references['xyz']):
            locations.append(xyz); labels.append((name, 'control_csv', 'reference'))
    for i, xyz in enumerate(fit, 1):
        locations.append(xyz); labels.append((f'Control {i}', 'fitting_control_array', 'fitting_control'))
    observed = []
    if locations:
        survey = dict(ids=[str(i) for i in range(len(locations))], xyz=np.asarray(locations))
        observed = assess(points, survey, config, metres_per_unit, cancel=cancel)
    marks = []
    for row, (name, source, role) in zip(observed, labels):
        marks.append(_mark(row, name, source, role))
    for row in checks:
        role = 'excluded' if row['role'] == 'fitting_control_neighborhood' else row['role']
        marks.append(_mark(row, row['id'], 'report_checkpoints', role))
    # One CSV can be retained both as LP360 reference and report checks.
    # Coalesce the same declared role/ID/coordinate record, retaining both sources.
    unique = {}
    for mark in marks:
        key = (mark['role'],mark['id'],mark['easting'],mark['northing'],mark['survey_z'])
        if key in unique:
            unique[key]['source'] += ' + ' + mark['source']
        else:
            unique[key] = mark
    marks = list(unique.values())
    # Conflicting declarations at the same surveyed XY cannot be used both as
    # independent evidence and as control-coverage credit. Preserve both records.
    independent_xy = np.asarray([[m['easting'],m['northing']] for m in marks
                                 if m['role']=='independent']).reshape(-1,2)
    conflict_xy = []
    tolerance = .001/metres_per_unit  # 1 mm, to tolerate coordinate rounding only
    for mark in marks:
        mark.update(control_eligible=mark['role'] in ('fitting_control','reference'),
                    role_conflict=False,role_note='')
        if mark['control_eligible'] and len(independent_xy):
            if np.any(np.linalg.norm(independent_xy-[mark['easting'],mark['northing']],axis=1)<=tolerance):
                conflict_xy.append([mark['easting'],mark['northing']])
                mark.update(control_eligible=False,role_conflict=True,
                    role_note='Also supplied as an independent check; excluded from control-site thresholds pending role resolution.')
    if conflict_xy:
        for mark in marks:
            if mark['role']=='independent' and np.any(np.linalg.norm(np.asarray(conflict_xy)-[mark['easting'],mark['northing']],axis=1)<=tolerance):
                mark.update(role_conflict=True,
                    role_note='Also supplied as reference/control; excluded from independent accuracy statistics pending role resolution.')
    basis = 'fitting_control' if len(fit) else ('reference' if any(m['role'] == 'reference' for m in marks) else None)
    radius = config['radius_ft'] * M_PER_US_SURVEY_FOOT / metres_per_unit
    gap_limit = config['coverage_max_gap_ft'] * M_PER_US_SURVEY_FOOT / metres_per_unit
    flights = []
    ground = (np.asarray(points['classification']) == 2)
    for item in inventory['strips']:
        _check_cancel(cancel)
        strip = int(item['id'])
        keep = ground & (np.asarray(points['point_source_id']) == strip)
        xy = np.column_stack([np.asarray(points[k])[keep] for k in ('x', 'y')])
        xy = xy[np.isfinite(xy).all(axis=1)]
        flight = dict(strip=strip, source_id=item.get('source_id'),
                      trajectory_path=item.get('trajectory_path'), clouds=item.get('clouds', []),
                      ground_returns=len(xy), basis=basis, counts={}, usable_sites=0,
                      extent=[], length=None, width=None, along_span_fraction=None,
                      cross_span_fraction=None, maximum_gap=None, long_gaps=[], flags=[])
        for role in ROLES:
            supplied = [m for m in marks if m['role'] == role]
            supported = [m for m in supplied if _support(m, strip)['supported']]
            # IDs/rows at the same XY do not create additional geometric sites.
            sites = {(m['easting'], m['northing']) for m in supported}
            eligible = {(m['easting'],m['northing']) for m in supported if m['control_eligible']}
            flight['counts'][role] = dict(supplied=len(supplied), supported=len(supported),
                                          sites=len(sites), eligible_sites=len(eligible),
                                          rejected=len(supplied)-len(supported))
        supported = [m for m in marks if m['role'] == basis and m['control_eligible'] and _support(m, strip)['supported']]
        sites = np.asarray(sorted({(m['easting'], m['northing']) for m in supported})).reshape(-1, 2)
        flight['usable_sites'] = len(sites)
        flags = flight['flags']
        if any(m['role_conflict'] and _support(m,strip)['supported'] for m in marks):
            flags.append('Conflicting control/reference and independent roles at a surveyed location; resolve roles before accuracy acceptance.')
        if basis is None:
            flags.append('No fitting control or reference PIDs supplied; absolute anchoring is unassessed.')
        elif len(sites) < config['coverage_min_sites']:
            flags.append(f"Only {len(sites)} distinct supported {basis.replace('_', ' ')} site(s); planning threshold is {config['coverage_min_sites']}.")
        if not len(xy):
            flags.append('No finite class-2 ground extent; coverage geometry is unavailable.')
        else:
            center = xy.mean(axis=0)
            centered = xy - center
            values, vectors = np.linalg.eigh(centered.T @ centered)
            along = vectors[:, -1]
            if along[1] < 0 or (along[1] == 0 and along[0] < 0):
                along = -along
            across = np.array([-along[1], along[0]])
            axes = np.column_stack([along, across])
            uv = centered @ axes
            low, high = uv.min(axis=0), uv.max(axis=0)
            length, width = high-low
            flight.update(length=float(length), width=float(width), extent=[
                (center + np.array([a, b]) @ axes.T).tolist()
                for a, b in ((low[0], low[1]), (high[0], low[1]),
                             (high[0], high[1]), (low[0], high[1]))])
            if basis is not None and length > 0:
                controls = (sites-center) @ axes
                stations = np.unique(np.clip(controls[:, 0], low[0], high[0]))
                bounds = np.concatenate([[low[0]], stations, [high[0]]])
                gaps = np.diff(bounds)
                flight['maximum_gap'] = float(gaps.max())
                for a, b, gap in zip(bounds[:-1], bounds[1:], gaps):
                    if gap > gap_limit:
                        mid = (low[1]+high[1])/2
                        flight['long_gaps'].append(dict(length=float(gap), segment=[
                            (center+np.array([a, mid]) @ axes.T).tolist(),
                            (center+np.array([b, mid]) @ axes.T).tolist()]))
                if flight['long_gaps']:
                    flags.append(f"Projected control gap exceeds {config['coverage_max_gap_ft']:g} US survey ft, including unsupported ends.")
                if len(controls) >= 2:
                    spans = np.ptp(controls, axis=0)
                    flight['along_span_fraction'] = float(min(1., spans[0]/length))
                    flight['cross_span_fraction'] = float(min(1., spans[1]/width)) if width > 0 else None
                    if flight['along_span_fraction'] < .5:
                        flags.append('Supported sites span less than half the projected ground extent length.')
                    if width > 2*radius and flight['cross_span_fraction'] < .25:
                        flags.append('Supported sites span less than a quarter of the ground extent width; cross-corridor tilt is weakly checked.')
                    if len(controls) >= 3 and width > 2*radius:
                        normalized = (controls-controls.mean(axis=0))/np.array([length, width])
                        singular = np.linalg.svd(normalized, compute_uv=False)
                        if singular[0] == 0 or singular[-1] < .1*singular[0]:
                            flags.append('Supported sites have nearly collinear XY geometry; two-direction tilt is weakly checked.')
        flights.append(flight)
    for mark in marks:
        mark['flights'] = [_support(mark, flight['strip']) for flight in flights]
    return plain(dict(schema_version=1, coordinate_state='original before adjustment',
        units=inventory.get('units', 'project units'), basis=basis, points=marks, flights=flights,
        settings=dict(min_sites=config['coverage_min_sites'], max_gap_ft=config['coverage_max_gap_ft'],
                      radius_ft=config['radius_ft'], min_points=config['min_points'],
                      along_span_warning_fraction=.5, cross_span_warning_fraction=.25,
                      normalized_geometry_ratio=.1),
        summary=dict(supplied_records=len(marks), flights=len(flights),
                     flights_with_warnings=sum(bool(f['flags']) for f in flights),
                     fitting_control_records=len(fit), reference_records=sum(m['role']=='reference' for m in marks),
                     independent_records=sum(m['role']=='independent' for m in marks),
                     conflicting_role_records=sum(m['role_conflict'] for m in marks)),
        limitations=[
            'Advisory planning thresholds are not GDOT/ASPRS minimums, accuracy acceptance, or an observability proof.',
            'Counts describe original-cloud support under the report OLS/hull gates, not final solver observation membership or physical surface verification.',
            'Fitting controls are only the array actually supplied to the solve. Audit CSV PIDs are reference-only and never added to the solve.',
            'A reference/control and independent-check location coincident within 1 mm has conflicting roles; it receives no control-site credit and no independent accuracy credit until resolved.',
            'Independent and excluded checks do not satisfy control-site thresholds. Coincident supported XY records count once per role.',
            'Outlines are oriented bounding rectangles of finite class-2 returns, not exact flight footprints or confirmed coverage. Gaps use a straight principal-axis projection, including both ends, not curved-route stationing or elapsed trajectory time.',
            'A local plane does not verify a photo-ID corner horizontally, survey uncertainty, or the material beneath the sensor.']))


def _support(mark, strip):
    return next((row for row in mark['flights'] if row['strip'] == strip),
                dict(strip=strip, n=0, supported=False, reason='No local ground returns'))


def _mark(row, name, source, role):
    return dict(id=str(name), source=source, role=role,
                **{k:row[k] for k in ('easting', 'northing', 'survey_z')},
                flights=[dict(strip=int(strip), n=value['n'], supported=value['supported'],
                              reason=value['reason']) for strip, value in row['flights'].items()])


def write(folder, audit):
    """Publish exhaustive per-flight evidence plus a static, equal-scale map."""
    folder = Path(folder)
    (folder/'control_coverage.json').write_text(json.dumps(audit, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    with (folder/'control_coverage_flights.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['analysis_strip', 'original_line_id', 'trajectory', 'clouds', 'basis',
                         'usable_control_sites', 'fitting_supported', 'reference_supported',
                         'independent_supported', 'excluded_supported', 'along_span_fraction',
                         'cross_span_fraction', 'maximum_projected_gap', 'units', 'warnings'])
        for row in audit['flights']:
            writer.writerow([row['strip'],row['source_id'],row['trajectory_path'],' | '.join(row['clouds']),
                row['basis'],row['usable_sites']]+[row['counts'][role]['supported'] for role in ROLES]+[
                row['along_span_fraction'],row['cross_span_fraction'],row['maximum_gap'],audit['units'],' | '.join(row['flags'])])
    with (folder/'control_coverage_points.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['id','source','role','easting','northing','survey_z','analysis_strip','local_ground_returns','supported','reason','role_conflict','control_eligible','role_note'])
        for mark in audit['points']:
            for flight in audit['flights']:
                row = _support(mark, flight['strip'])
                writer.writerow([mark[k] for k in ('id','source','role','easting','northing','survey_z')]+[
                    row['strip'],row['n'],row['supported'],row['reason'],mark['role_conflict'],mark['control_eligible'],mark['role_note']])
    (folder/'control_coverage.svg').write_text(_svg(audit), encoding='utf-8')


def _svg(audit):
    coordinates = [p for row in audit['flights'] for p in row['extent']]
    coordinates += [[p['easting'],p['northing']] for p in audit['points']]
    if coordinates:
        xy = np.asarray(coordinates);low,high=xy.min(axis=0),xy.max(axis=0)
    else:
        low,high=np.zeros(2),np.ones(2)
    scale = min(880/max(high[0]-low[0],1.),550/max(high[1]-low[1],1.))
    mid = (low+high)/2
    def pt(p):return f'{500+(p[0]-mid[0])*scale:.3f},{340-(p[1]-mid[1])*scale:.3f}'
    colors=dict(fitting_control='#783f9a',reference='#b17a19',independent='#1b7894',excluded='#6d7781')
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="720" viewBox="0 0 1000 720">',
           '<rect width="1000" height="720" fill="#f5f8fa"/>',
           '<g font-family="sans-serif" font-size="15" fill="#193548"><text x="30" y="28">Control / PID coverage — original ground extents; north ↑</text>',
           '<text x="30" y="52">Purple: fitting · amber: reference · blue: independent · gray: excluded</text>']
    for row in audit['flights']:
        color='#ba742a' if row['flags'] else '#718c9c'
        parts.append(f'<polygon points="{" ".join(pt(p) for p in row["extent"])}" fill="none" stroke="{color}" stroke-width="1.5"/>')
        if row['extent']:
            parts.append(f'<text x="{pt(row["extent"][0]).split(",")[0]}" y="{pt(row["extent"][0]).split(",")[1]}">Flight {row["strip"]}</text>')
        for gap in row['long_gaps']:
            parts.append(f'<polyline points="{" ".join(pt(p) for p in gap["segment"])}" fill="none" stroke="#b44e37" stroke-dasharray="6 4"/>')
    for mark in audit['points']:
        x,y=pt([mark['easting'],mark['northing']]).split(',');supported=any(r['supported'] for r in mark['flights'])
        parts.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{colors[mark["role"]] if supported else "white"}" stroke="{colors[mark["role"]]}" stroke-width="2"><title>{html.escape(mark["id"]+" — "+mark["role"])}</title></circle>')
        if len(audit['points']) <= 60:
            parts.append(f'<text x="{float(x)+8:.3f}" y="{float(y)-7:.3f}" font-size="11">{html.escape(mark["id"])}</text>')
    parts.append('<text x="30" y="686">Hollow: no local support · dashed red: projected control gap · equal XY scale</text></g></svg>')
    return ''.join(parts)


def section(audit):
    """Accessible evidence remains readable without JavaScript; map is enhanced."""
    esc=lambda v:html.escape(str(v),quote=True)
    count=lambda f,r:f['counts'][r]['eligible_sites' if r in ('fitting_control','reference') else 'sites']
    rows=[]
    for f in audit['flights']:
        values=[f['strip'],f['source_id'],(f['basis'] or 'None').replace('_',' '),
                count(f,'fitting_control'),count(f,'reference'),count(f,'independent'),
                count(f,'excluded'),
                'Unavailable' if f['along_span_fraction'] is None else f"{100*f['along_span_fraction']:.1f}%",
                'Unavailable' if f['cross_span_fraction'] is None else f"{100*f['cross_span_fraction']:.1f}%",
                'Unavailable' if f['maximum_gap'] is None else f"{f['maximum_gap']:.2f}",
                ' | '.join(f['flags']) or 'No coverage warnings; accuracy acceptance remains separate']
        rows.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
    headers=['Analysis flight','Original line','Screening basis','Eligible fitting sites','Eligible reference sites',
             'Declared independent checks','Excluded check sites','Along span','Across span',
             'Largest projected gap','Review warnings']
    table='<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
    screening=audit.get('settings',{})
    thresholds=(f"Planning thresholds: {screening.get('min_sites','Unavailable')} distinct sites; projected gap {screening.get('max_gap_ft','Unavailable')} US survey ft. Local support: radius {screening.get('radius_ft','Unavailable')} US survey ft; minimum {screening.get('min_points','Unavailable')} class-2 returns.")
    options=''.join(f'<option value="{f["strip"]}">Flight {f["strip"]} / original line {esc(f["source_id"])}</option>' for f in audit['flights'])
    return f'''<section id="coverageAudit"><h2>Control / PID coverage audit</h2>
<p>Read-only screening of the <strong>original cloud geometry</strong>. Purple: supplied fitting control; amber: reference PIDs; blue: declared independent checks; gray: excluded check neighborhoods. Hollow markers have no qualifying local support. Conflicting source roles remain visible and receive no control-site or independent-accuracy credit. Independent checks never satisfy control-site thresholds.</p>
<p class="notice">Planning warnings are advisory and do not change the adjustment. Local support uses the report's circular OLS / ground-hull gates; it does not establish which marks the solver actually used. Outlines are oriented ground extent rectangles, not exact flight footprints. Gap distances are straight-axis projections, including both ends; curved-route distance is unassessed.</p>
<p>Screening basis: <strong>{esc((audit.get('basis') or 'No control/reference survey supplied').replace('_',' '))}</strong>. Distances: {esc(audit['units'])}. Duplicate supported XY locations count once per role.</p><p>{esc(thresholds)}</p>
<div class="toolbar"><label>Flight <select id="coverageFlight"><option value="all">All analysis flights</option>{options}</select></label>
<label>Survey role <select id="coverageRole"><option value="all">All roles</option><option value="fitting_control">Fitting control</option><option value="reference">Reference PIDs</option><option value="independent">Independent checks</option><option value="excluded">Excluded checks</option></select></label><span id="coverageMapCount"></span></div>
<canvas id="coverageMap" aria-label="North-up equal-scale survey locations and original ground extents"></canvas>
<noscript><p>Interactive filtering requires JavaScript. <a href="control_coverage.svg">Open the static control map</a>; the per-flight table remains available below.</p></noscript>
<div id="coverageDetail" class="notice"></div><div id="coveragePointTable" class="scroll"></div>
<h3>Control and check coverage by analysis flight</h3>{table if rows else '<p>Control coverage is unavailable without original per-flight point geometry.</p>'}
<details><summary>Control coverage methods and limits</summary><ul>{''.join('<li>'+esc(v)+'</li>' for v in audit['limitations'])}</ul></details>
</section>'''
