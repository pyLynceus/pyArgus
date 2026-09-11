"""SH151 AT correction evaluation; run explicitly as a module."""

def main():
    from pathlib import Path
    import re,json
    import numpy as np
    from scipy.spatial import cKDTree
    from scipy.interpolate import RBFInterpolator
    from reference.sh151_gather import read_marks,CACHE
    from pyargus.qa.control_by_strip import _plane_at_mark

    root=Path('reference/reports/sh151_at_fit'); root.mkdir(exist_ok=True)
    text=Path('Z:/Users/BJordan/SH 151/AT/VRAT_FINAL/8242026BundleReportControl.txt').read_text()
    points=[]; name=None
    for line in text.splitlines():
        m=re.fullmatch(r'([A-Za-z0-9_]+):',line.strip())
        if m: name=m[1]
        if line.strip().startswith('Bundle Coord:') and name:
            vals=line.split('Bundle Coord:',1)[1].split()[:3]
            points.append(dict(id=name,xyz=list(map(float,vals))))
    marks=read_marks(); ids=list(marks); xy=np.array([marks[i][1:3] for i in ids]); tree=cKDTree(xy)
    rows=[]
    for p in points:
        distance,index=tree.query(p['xyz'][:2])
        if distance>1: continue
        mark=ids[index]; heights=[]; slopes=[]
        for f in CACHE.glob('*.npz'):
            with np.load(f,allow_pickle=False) as d:
                mask=(d['mark']==mark)&((d['x']-p['xyz'][0])**2+(d['y']-p['xyz'][1])**2<=2.5**2)
                if mask.sum()<8: continue
                z,slope=_plane_at_mark(d['x'][mask],d['y'][mask],d['z'][mask],*p['xyz'][:2])
                heights.append(z); slopes.append(slope)
        if heights:
            rows.append(dict(**p,cache_mark=mark,strips=len(heights),slope=float(np.median(slopes)),spread=float(np.ptp(heights)),lidar=float(np.median(heights)),delta=float(p['xyz'][2]-np.median(heights))))
    safe=[p for p in rows if p['slope']<.08 and p['spread']<.1 and p['strips']>=2]
    out=dict(bundle_points=len(points),cached_points=len(rows),low_slope_consistent=len(safe),rows=rows)
    if len(safe)>=6:
        xy=np.array([r['xyz'][:2] for r in safe]); origin=xy.mean(axis=0); xy=(xy-origin)/1000
        delta=np.array([r['delta'] for r in safe]); scores={}
        for smoothing in (0.,.001,.01,.1,1.,10.,100.):
            predicted=[]
            for i in range(len(xy)):
                mask=np.arange(len(xy))!=i
                f=RBFInterpolator(xy[mask],delta[mask],kernel='thin_plate_spline',smoothing=smoothing)
                predicted.append(float(f(xy[i:i+1])[0]))
            e=delta-np.array(predicted)
            scores[str(smoothing)]=dict(rmse=float(np.sqrt(np.mean(e*e))),p95=float(np.percentile(abs(e),95)))
        out['leave_one_out']=scores; out['uncorrected_rmse']=float(np.sqrt(np.mean(delta**2)))
    (root/'preflight.json').write_text(json.dumps(out,indent=2))
    (root/'bundle_targets.json').write_text(json.dumps(points,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k!='rows'},indent=2),flush=True)
    print('Target corrections:',[(r['id'],round(r['delta'],3)) for r in safe],flush=True)


if __name__ == '__main__':
    main()
