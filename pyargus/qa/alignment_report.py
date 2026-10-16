"""Repeatable alignment comparisons; checkpoint observations never enter the solve."""
from pathlib import Path
from datetime import datetime, timezone
import csv
import html
import json
import math
import numpy as np
from pyargus.analysis_records import plain
from pyargus.job_manifest import identity

FT_US = 1200 / 3937
DEFAULTS = dict(checkpoints='', order='pnez', role='reference', surface='unspecified', material='',
                pavement_tolerance_ft=.10, other_ground_tolerance_ft=.50, radius_ft=2., min_points=8)
PRODUCTS = ('report.html', 'alignment_comparison.json', 'overlap_comparison.csv', 'corrections.csv',
            'checkpoint_comparison.csv', 'checkpoint_flights.csv')


def settings(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError('Alignment report settings must be a dictionary')
    unknown = set(value or {}) - set(DEFAULTS)
    if unknown:
        raise ValueError('Unknown alignment report settings: ' + ', '.join(sorted(unknown)))
    result = dict(DEFAULTS, **(value or {}))
    for key in ('checkpoints', 'material'):
        if not isinstance(result[key], str):
            raise ValueError(f'Alignment report {key} must be text')
    for key, choices in [('order', ('pnez', 'penz')), ('role', ('reference', 'independent')),
                         ('surface', ('unspecified', 'pavement', 'other_ground'))]:
        if result[key] not in choices:
            raise ValueError(f'Alignment report {key} must be one of {choices}')
    for key in ('pavement_tolerance_ft', 'other_ground_tolerance_ft', 'radius_ft'):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'Alignment report {key} must be finite and positive')
    if type(result['min_points']) is not int or result['min_points'] < 3:
        raise ValueError('Alignment report minimum points must be an integer of at least 3')
    if result['checkpoints']:
        result['checkpoints'] = str(Path(result['checkpoints']).resolve())
    return result


def read_checks(config):
    if not config['checkpoints']:
        return None
    from pyargus.formats.control import read_control_csv
    before = identity(config['checkpoints'], hash_content=True)
    ids, e, n, z = read_control_csv(config['checkpoints'], config['order'])
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate IDs in alignment report checkpoint CSV')
    xyz = np.column_stack([e, n, z])
    if not np.isfinite(xyz).all():
        raise ValueError('Alignment report checkpoints contain nonfinite coordinates')
    if identity(config['checkpoints'], hash_content=True) != before:
        raise ValueError('Alignment report checkpoint CSV changed while reading')
    return dict(ids=ids, xyz=xyz, identity=before)


def _plane(xy, z, minimum, radius):
    count = len(z)
    result = dict(n=count, error=None, scatter=None, slope=None, supported=False, reason='Too few ground returns')
    if count < minimum:
        return result
    # Center on surveyed XY and scale by radius before conditioning the design.
    from scipy.spatial import ConvexHull, QhullError
    design = np.column_stack([xy / radius, np.ones(count)])
    if np.linalg.matrix_rank(design) < 3 or np.linalg.cond(design) > 30:
        result['reason'] = 'Local ground geometry is collinear or poorly conditioned'
        return result
    try:
        hull = ConvexHull(xy / radius)
    except QhullError:
        result['reason'] = 'Local ground geometry has no area'
        return result
    if np.any(hull.equations[:, -1] > 1e-9):
        result['reason'] = 'Surveyed XY lies outside local ground support'
        return result
    coefficients = np.linalg.lstsq(design, z, rcond=None)[0]
    residual = z - design @ coefficients
    result.update(error=float(coefficients[2]), scatter=float(np.sqrt(np.mean(residual**2))),
                  slope=float(np.linalg.norm(coefficients[:2]) / radius), supported=True, reason='')
    return result


def assess(points, checks, config, metres_per_unit, *, fitting_control=None, cancel=lambda: False):
    """Local OLS planes at surveyed XY, merged and per analysis strip, without fitting checks."""
    if checks is None:
        return []
    from scipy.spatial import cKDTree
    from pyargus.project import _check_cancel
    ground = points['classification'] == 2
    xy = np.column_stack([points['x'][ground], points['y'][ground]])
    z, strips = points['z'][ground], points['point_source_id'][ground]
    tree = cKDTree(xy)
    radius = config['radius_ft'] * FT_US / metres_per_unit
    tolerance_ft = config.get(config['surface'] + '_tolerance_ft')
    tolerance = None if tolerance_ft is None else tolerance_ft * FT_US / metres_per_unit
    fit = np.asarray(fitting_control) if fitting_control is not None else np.empty((0, 3))
    rows = []
    for name, mark in zip(checks['ids'], checks['xyz']):
        _check_cancel(cancel)
        near = np.asarray(tree.query_ball_point(mark[:2], radius), dtype=int)
        delta, heights, sid = xy[near] - mark[:2], z[near] - mark[2], strips[near]
        fitting = bool(len(fit) and np.any(np.linalg.norm(fit[:, :2] - mark[:2], axis=1) <= radius))
        row = dict(id=name, easting=float(mark[0]), northing=float(mark[1]), survey_z=float(mark[2]),
                   role='fitting_control_neighborhood' if fitting else config['role'], surface=config['surface'],
                   material=config['material'], tolerance=tolerance,
                   merged=_plane(delta, heights, config['min_points'], radius), flights={})
        for strip in np.unique(sid):
            keep = sid == strip
            row['flights'][str(int(strip))] = _plane(delta[keep], heights[keep], config['min_points'], radius)
        rows.append(row)
    return rows


def _statistics(values, tolerance):
    if not values:
        return dict(n=0, mean=None, rmse=None, median=None, p95_absolute=None, exceeding=None)
    a = np.asarray(values)
    return dict(n=len(a), mean=float(a.mean()), rmse=float(np.sqrt(np.mean(a*a))),
                median=float(np.median(a)), p95_absolute=float(np.percentile(np.abs(a), 95)),
                exceeding=None if tolerance is None else int(np.sum(np.abs(a) > tolerance)))


def compare_checks(before, after):
    assert [r['id'] for r in before] == [r['id'] for r in after]
    rows = []
    for a, b in zip(before, after):
        row = {k: v for k, v in a.items() if k not in ('merged', 'flights')}
        row.update(before=a['merged'], after=b['merged'], flights=[])
        row['paired_support'] = a['merged']['supported'] and b['merged']['supported']
        row['exceeds_after'] = (abs(b['merged']['error']) > row['tolerance']
                                if b['merged']['supported'] and row['tolerance'] is not None else None)
        for strip in sorted(set(a['flights']) | set(b['flights']), key=int):
            row['flights'].append(dict(strip=strip, before=a['flights'].get(strip), after=b['flights'].get(strip)))
        rows.append(row)
    return rows


def _csv(path, headers, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f); writer.writerow(headers); writer.writerows(rows)


def generate(folder, alignment, before_qa, after_qa, before_checks, after_checks, config, crs, *, inputs):
    """Write one portable HTML comparison plus machine-readable evidence in an unpublished run folder."""
    folder = Path(folder)
    rows = compare_checks(before_checks, after_checks)
    paired = [r for r in rows if r['paired_support'] and r['role'] != 'fitting_control_neighborhood']
    independent = [r for r in paired if r['role'] == 'independent']
    tol = rows[0]['tolerance'] if rows else None
    pairs_before = {(p['a'], p['b']): p for p in before_qa.get('strip_dz', [])}
    pairs_after = {(p['a'], p['b']): p for p in after_qa.get('strip_dz', [])}
    overlap = [dict(a=a, b=b, before=pairs_before.get((a,b)), after=pairs_after.get((a,b)))
               for a, b in sorted(set(pairs_before) | set(pairs_after))]
    corrections = [dict(strip=s, dx=v[0], dy=v[1], dz=v[2]) for s, v in alignment['offsets'].items()]
    evidence = plain(dict(schema_version=1, created_utc=datetime.now(timezone.utc).isoformat(),
        review_status='Needs review', units=crs.axis_info[0].unit_name, crs=crs.to_wkt(),
        settings=config, inputs=inputs, corrections=corrections, boresight_radians=alignment['boresight'],
        solver=dict(patch_rms_before=alignment['patch_rms_before'], patch_rms_after=alignment['patch_rms_after'],
                    observations=alignment['observations'], control_anchored=alignment['control_anchored']),
        overlap=overlap, checkpoints=rows,
        checkpoint_summary=dict(supplied=len(rows), paired_support=len(paired), independent_paired_support=len(independent),
            before=_statistics([r['before']['error'] for r in paired], tol),
            after=_statistics([r['after']['error'] for r in paired], tol),
            independent_before=_statistics([r['before']['error'] for r in independent], tol),
            independent_after=_statistics([r['after']['error'] for r in independent], tol)),
        limitations=[
            'Checkpoint comparisons use class-2 ground, a circular neighborhood, and an OLS plane evaluated at surveyed XY; no extrapolation outside its convex hull. Maximum scaled design condition is 30.',
            'Before/after checkpoint statistics use the same IDs supported in both states. All unsupported and fitting-control-neighborhood records remain listed.',
            'Local scatter measures fit residuals, not survey uncertainty. Class 2 does not by itself establish the intended physical surface.',
            'Survey independence and surface/material are user declarations. Checks within one report radius of supplied fitting-control XY are excluded from independent/reference summary statistics.',
            'Overlap metrics come from each state\'s own QA cells; matching a strip pair does not establish identical cell samples before and after.',
            'After statistics use actual LAS/LAZ coordinates read back after export quantization. Solver residuals are fitting diagnostics, not independent accuracy.',
            'No scan-angle, time or reflectance diagnosis is included in this automatic report. No other-ground assessment is inferred from pavement checks.',
            'Completion and tolerance counts do not constitute accuracy acceptance.']))
    (folder/'alignment_comparison.json').write_text(json.dumps(evidence, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    _csv(folder/'overlap_comparison.csv', ['strip_a','strip_b','before_cells','after_cells','before_rmse','after_rmse','before_median','after_median'],
         [[r['a'],r['b']]+[(r[state] or {}).get(key) for key in ('cells','rmse','median') for state in ('before','after')] for r in overlap])
    # Explicit ordering above follows the paired before/after headers.
    _csv(folder/'corrections.csv', ['analysis_strip','dx','dy','dz'], [[r[k] for k in ('strip','dx','dy','dz')] for r in corrections])
    _csv(folder/'checkpoint_comparison.csv', ['id','easting','northing','survey_z','role','surface','material','before_error','after_error','before_supported','after_supported','before_reason','after_reason','before_returns','after_returns','after_scatter','tolerance','exceeds_after'],
         [[r[k] for k in ('id','easting','northing','survey_z','role','surface','material')]+[r['before']['error'],r['after']['error'],r['before']['supported'],r['after']['supported'],r['before']['reason'],r['after']['reason'],r['before']['n'],r['after']['n'],r['after']['scatter'],r['tolerance'],r['exceeds_after']] for r in rows])
    _csv(folder/'checkpoint_flights.csv', ['id','analysis_strip','before_error','after_error','before_returns','after_returns','before_reason','after_reason'],
         [[r['id'],f['strip']]+[(f[state] or {}).get(key) for key in ('error','n','reason') for state in ('before','after')] for r in rows for f in r['flights']])
    esc=lambda v:html.escape(str(v),quote=True)
    num=lambda v:'Unavailable' if v is None else f'{v:.4f}'
    def table(headers, records):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in r)+'</tr>' for r in records)+'</tbody></table></div>'
    pair_table=table(['Flight A','Flight B','Cells before','Cells after','RMSE before','RMSE after','Median before','Median after'],
        [[r['a'],r['b']]+[str((r[state] or {}).get(key, 'Unavailable')) if key=='cells' else num((r[state] or {}).get(key)) for key in ('cells','rmse','median') for state in ('before','after')] for r in overlap])
    correction_table=table(['Analysis flight','ΔX','ΔY','ΔZ'],[[r['strip'],num(r['dx']),num(r['dy']),num(r['dz'])] for r in corrections])
    source_table=table(['Input','Identity'],[[i['path'],('SHA256 '+i['sha256']) if 'sha256' in i else f"{i['size_bytes']} bytes; mtime_ns {i['mtime_ns']}"] for i in inputs])
    unit=esc(evidence['units']);stats=evidence['checkpoint_summary'];b=stats['before'];a=stats['after']
    findings=[]
    comparable=[r for r in overlap if r['before'] is not None and r['after'] is not None]
    raised=sum(r['after']['rmse'] > r['before']['rmse'] + 1e-12 for r in comparable)
    if raised:findings.append(f'{raised} flight pair(s) have higher cell RMSE after export. Review the overlap maps and changed cell counts.')
    if rows:
        findings.append(f"{len(rows)-sum(r['paired_support'] for r in rows)} supplied checks lack support in one or both states; these are retained as unavailable.")
        fitting_count=sum(r['role']=='fitting_control_neighborhood' for r in rows)
        if fitting_count:findings.append(f'{fitting_count} checks overlap supplied fitting-control neighborhoods and are excluded from summary accuracy statistics.')
        if a['exceeding'] is not None:findings.append(f"{a['exceeding']} of {a['n']} paired {config['role']} comparisons exceed the declared {config['surface']} tolerance after export.")
        else:findings.append('No tolerance assessment is available without both paired support and a declared surface category.')
        if a['rmse'] is not None and b['rmse'] is not None and a['rmse']>b['rmse']+1e-12:findings.append('RMSE at the same supported survey IDs is higher after export; review before accepting the adjustment.')
    if not findings:findings.append('Review the overlap results and correction magnitudes. No survey accuracy acceptance is inferred.')
    findings_html='<ul>'+''.join('<li>'+esc(t)+'</li>' for t in findings)+'</ul>'
    missing='No survey checks supplied; absolute vertical accuracy has not been evaluated.' if not rows else ('No independent checkpoints have paired support; absolute vertical accuracy is not established.' if not independent else f'{len(independent)} declared independent checkpoints have support before and after; review their residuals and survey provenance.')
    data=json.dumps(evidence,separators=(',',':'),allow_nan=False).replace('<',chr(92)+'u003c').replace('>',chr(92)+'u003e').replace('&',chr(92)+'u0026')
    script=(Path(__file__).parents[1]/'assets'/'alignment_report.js').read_text(encoding='utf-8')
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>pyArgus alignment comparison</title><style>
body{{font:15px/1.55 'Segoe UI',system-ui,sans-serif;color:#193548;background:#f3f6f8;margin:0}}main{{max-width:1160px;margin:auto;padding:28px 22px}}h1{{font-size:30px;margin:5px 0}}h2{{font-size:21px;margin-top:32px}}.eyebrow,.muted{{color:#526c7e}}.notice{{padding:14px 18px;border-left:4px solid #b58132;background:#fff4df}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card,section{{background:white;padding:16px;border:1px solid #d8e2e8;border-radius:7px}}.card strong{{display:block;font-size:25px}}section{{margin-top:18px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:8px;text-align:left;border-bottom:1px solid #d9e2e8}}td{{overflow-wrap:anywhere}}th{{background:#edf2f5}}.toolbar{{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:12px 0}}button,select,input{{font:inherit;padding:5px}}a{{color:#145d8b}}canvas{{width:100%;height:310px;background:#f5f8fa}}.plots{{display:grid;grid-template-columns:1fr 1fr;gap:15px}}.downloads{{display:flex;flex-wrap:wrap;gap:14px}}@media(max-width:760px){{.cards,.plots{{grid-template-columns:1fr 1fr}}main{{padding:16px 10px}}}}@media(max-width:500px){{.cards,.plots{{grid-template-columns:1fr}}}}
</style></head><body><main><div class="eyebrow">pyArgus · automatic alignment comparison · {esc(evidence['created_utc'])}</div><h1>Alignment before and after</h1><p>Exported cloud comparison · units: <strong>{unit}</strong> · surface declaration: <strong>{esc(config['surface'])}</strong></p><p class="notice"><strong>Needs review.</strong> {esc(missing)} Flight-line agreement and survey accuracy are separate assessments.</p>
<div class="cards"><div class="card"><strong>{num(alignment['patch_rms_before'])} → {num(alignment['patch_rms_after'])}</strong>solver patch RMS ({unit}); fitting evidence</div><div class="card"><strong>{len(overlap)}</strong>flight pairs with QA support in either state</div><div class="card"><strong>{stats['paired_support']} / {stats['supplied']}</strong>paired survey comparisons / supplied records</div><div class="card"><strong>{num(b['rmse'])} → {num(a['rmse'])}</strong>paired survey RMSE ({unit}); role: {esc(config['role'])}</div></div>
<section><h2>Items to review</h2>{findings_html}</section>
<section><h2>Flight-line agreement</h2><p>Ground-cell comparisons from the before and after QA reports. Each state can contain different cells; counts remain visible. Missing overlap is unavailable evidence.</p>{pair_table if overlap else '<p>No flight pair has qualifying ground-cell overlap.</p>'}<p><a href="before/report.html">Before QA and maps</a> · <a href="after/report.html">After QA and maps</a></p></section>
<section><h2>Corrections applied</h2>{correction_table}<p>Boresight [roll, pitch, heading], radians: {esc(alignment['boresight'])}. Analysis flight IDs map to original LAS line IDs, trajectories and files in <a href="alignment.json">alignment.json</a>. Original LAS line IDs remain preserved.</p></section>
<section id="checks"><h2>Survey checks at the same locations</h2><p>All supplied records remain visible, including unsupported checks. Positive error means cloud above survey. Summary RMSE uses the same supported IDs before and after; fitting-control neighborhoods are excluded. A declared reference comparison does not establish independent accuracy.</p><p>Radius: {config['radius_ft']:g} US survey ft; minimum {config['min_points']} ground returns; surveyed XY must lie inside the local ground hull. Pavement tolerance: ±{config['pavement_tolerance_ft']:g} US survey ft; other ground: ±{config['other_ground_tolerance_ft']:g} US survey ft. Only the declared surface tolerance is evaluated. Material: {esc(config['material'] or 'Not declared')}.</p>
<div class="toolbar"><label>Find ID <input id="findId" size="10"></label><label>Show <select id="rowFilter"><option value="all">All supplied checks</option><option value="exceeding">Exceeding after tolerance</option><option value="unsupported">Unsupported before or after</option></select></label><span id="rowCount"></span></div><div class="plots"><div><h3>Check locations</h3><canvas id="checkMap"></canvas></div><div><h3>Before and after height errors</h3><canvas id="errorPlot"></canvas></div></div><div id="selectedCheck" class="notice"></div><div id="flightTable" class="scroll"></div><div id="checkTable" class="scroll"></div></section>
<section><h2>Inputs, settings and evidence</h2><div class="downloads"><a href="alignment_comparison.json">Full comparison JSON</a><a href="checkpoint_comparison.csv">Check residuals CSV</a><a href="checkpoint_flights.csv">Per-flight checks CSV</a><a href="overlap_comparison.csv">Flight-pair comparison CSV</a><a href="corrections.csv">Corrections CSV</a><a href="project.json">Saved project and report settings</a></div><details><summary>Source identities</summary>{source_table}</details><details><summary>Methods and limitations</summary><ul>{''.join('<li>'+esc(t)+'</li>' for t in evidence['limitations'])}</ul></details></section><footer><p>Keep this run folder together. Reports are retained per run; generating a report does not approve the adjustment.</p></footer></main><script>window.alignmentReportData={data};</script><script>{script}</script></body></html>'''
    (folder/'report.html').write_text(page,encoding='utf-8')
    return evidence
