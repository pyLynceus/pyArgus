"""SH151 AT correction evaluation; run explicitly as a module."""

def main():
    from pathlib import Path
    import json,html
    import numpy as np
    from pyargus.at_fit import choose_model,correction_grid,evaluate_grid
    from reference.sh151_gather import read_marks
    from scipy.spatial import Delaunay

    root=Path('reference/reports/sh151_at_fit')
    targets=json.loads((root/'bundle_targets.json').read_text())
    inventory=json.loads((root/'source_inventory.json').read_text())
    rows=[]
    for k,target in enumerate(targets):
        xyz=np.array(target['xyz']); measurements=[]
        for path in sorted((root/'surface_cache').glob('*.npz')):
            with np.load(path,allow_pickle=False) as archive:
                a=archive['data']; a=a[a[:,0]==k,1:]
            if len(a)<8: continue
            q=a[:,:2]-xyz[:2]
            design=np.column_stack((q,np.ones(len(q))))
            if np.linalg.matrix_rank(design)<3: continue
            try:
                if Delaunay(q).find_simplex([[0,0]])[0]<0: continue
            except Exception: continue
            keep=np.ones(len(a),dtype=bool)
            for _ in range(3):
                coef=np.linalg.lstsq(design[keep],a[keep,2],rcond=None)[0]
                residual=a[:,2]-design@coef
                sigma=1.4826*np.median(abs(residual[keep]-np.median(residual[keep])))
                new=abs(residual-np.median(residual[keep]))<=max(.015,3*sigma)
                if new.sum()<8 or np.linalg.matrix_rank(design[new])<3: break
                keep=new
            coef=np.linalg.lstsq(design[keep],a[keep,2],rcond=None)[0]
            roughness=float(np.sqrt(np.mean((a[keep,2]-design[keep]@coef)**2)))
            measurements.append(dict(strip=path.stem,z=float(coef[2]),slope=float(np.linalg.norm(coef[:2])),roughness=roughness,n=int(keep.sum())))
        row=dict(**target,measurements=measurements,excluded=[])
        good=[m for m in measurements if m['roughness']<=.05 and m['slope']<=.08]
        if len(good)<2: row['excluded'].append('fewer than two low-slope, smooth, enclosing surface samples')
        if target['id'] in ('CAL225','CAL226','CAL17'): row['excluded'].append('natural-ground / tall-grass description')
        if good:
            row['lidar']=float(np.median([m['z'] for m in good])); row['delta']=float(xyz[2]-row['lidar'])
            row['spread']=float(np.ptp([m['z'] for m in good]))
            if row['spread']>.1: row['excluded'].append('strip spread above 0.10 ft')
            if abs(row['delta'])>1: row['excluded'].append('difference above 1 ft requires review')
        rows.append(row)
    used=[r for r in rows if not r['excluded']]
    xy=np.array([r['xyz'][:2] for r in used]); delta=np.array([r['delta'] for r in used])
    selection=choose_model(xy,delta)
    model=dict(release_status='candidate_only_not_applied', reference='VRAT_FINAL explicit Bundle Coord XYZ',units='US survey feet',rows=rows,
        selection=selection,used=[r['id'] for r in used],source_inventory=inventory)
    print(json.dumps(dict(targets=len(targets),used=len(used),baseline=selection['baseline_rmse'],best=selection['best'],accepted=selection['accepted']),indent=2),flush=True)
    if selection['accepted']:
        import laspy
        bounds=[]
        for p in inventory:
            with laspy.open(p['path']) as reader: bounds.append((reader.header.mins[:2],reader.header.maxs[:2]))
        lo=np.min([p[0] for p in bounds],axis=0); hi=np.max([p[1] for p in bounds],axis=0)
        best=selection['best']
        x,y,g=correction_grid(xy,delta,best['kind'],best['alpha'],(lo[0],hi[0],lo[1],hi[1]))
        np.savez(root/'correction_grid.npz',x=x,y=y,delta=g)
        fitted=evaluate_grid(x,y,g,xy[:,0],xy[:,1])
        model['fit_rmse']=float(np.sqrt(np.mean((delta-fitted)**2)))
        model['grid_range']=[float(g.min()),float(g.max())]
        for r,value in zip(used,fitted): r.update(correction=float(value),after_lidar_minus_at=float(value-r['delta']))
        print('Fitted RMSE',model['fit_rmse'],'grid range',model['grid_range'],flush=True)
    (root/'model_review.json').write_text(json.dumps(model,indent=2))
    parts=['<!doctype html><meta charset="utf-8"><title>SH151 AT correction</title><style>body{font:16px Segoe UI;max-width:1100px;margin:30px auto}td,th{padding:7px;border-bottom:1px solid #ccc}table{border-collapse:collapse}</style><h1>SH 151 — AT-referenced vertical correction</h1>',
        '<p><strong>Candidate only. No LAS exports produced by this analysis.</strong></p><p>Reference: explicit final bundle-adjusted XYZ coordinates. All flight lines receive the same continuous Z-only field. This is an AT fit, not independent survey accuracy.</p>',
        f'<p>{len(used)} / {len(targets)} targets accepted. Uncorrected target RMS: {selection["baseline_rmse"]:.4f} ft. Leave-one-out RMS: {selection["best"]["loo_rmse"]:.4f} ft. Five spatial-block RMS: {selection["best"]["spatial_rmse"]:.4f} ft. These cross-validation results were used for model selection, not independent certification.</p>',
        '<p>Outside the target network the bounded field is extrapolated and has not been validated. No XYZ reprojection or horizontal shift. Corrections are evaluated on a 50-ft grid with bilinear interpolation.</p>',
        '<table><tr><th>Target</th><th>AT minus lidar</th><th>Applied Z</th><th>After lidar minus AT</th><th>Excluded reason</th></tr>']
    for r in rows:
        def number(key): return f'{r[key]:+.4f}' if key in r else '—'
        parts.append(f'<tr><td>{html.escape(r["id"])}</td><td>{number("delta")}</td><td>{number("correction")}</td><td>{number("after_lidar_minus_at")}</td><td>{html.escape("; ".join(r["excluded"]))}</td></tr>')
    parts.append('</table><p>Model details and source records: <a href="model_review.json">model_review.json</a></p>')
    (root/'report.html').write_text('\n'.join(parts),encoding='utf-8')


if __name__ == '__main__':
    main()
