"""Read-only-source spatial cache experiment on explicitly supplied clouds."""
import argparse
import json
from pathlib import Path
import statistics
import time
import numpy as np
from pyargus.sections import extract_section
from pyargus.viewer3d import sample_clouds
from pyargus.job_manifest import identity
from reference.profile_workflow import measure,digest
from reference.section_cache import build,extract


def assert_equal(a,b):
    assert a.matched==b.matched and a.matched_by_file==b.matched_by_file
    assert a.inputs==b.inputs and a.crs==b.crs
    for field in ('points','classes','lines','files','point_indices'):
        np.testing.assert_array_equal(getattr(a,field),getattr(b,field))


def run(paths,out,repeats=2):
    paths=[str(Path(p).resolve()) for p in paths];out=Path(out);out.mkdir(parents=True,exist_ok=False)
    report=dict(schema_version=1,inputs=[identity(p) for p in paths],cache_module_sha256=digest('reference/section_cache.py'),benchmarks=[],builds=[],notes=['cProfile enabled; sources/network and OS caches are not flushed.', 'Original sources read-only; cache is local and contains derived attributes only.', 'Invalidation uses path, size and nanosecond mtime, not cryptographic content validation.', 'No GUI integration, renderer change, classification or alignment changes.'])
    def save():
        temp=out/'report.tmp';temp.write_text(json.dumps(report,indent=2),encoding='utf-8');temp.replace(out/'report.json')
    caches=[]
    for i,path in enumerate(paths):
        cache=out/f'cache_{i}';caches.append(str(cache));print('Building',path,flush=True)
        _,m=measure(f'build_{i}',lambda:build(path,cache),out)
        m['cache_bytes']=sum(p.stat().st_size for p in cache.rglob('*') if p.is_file());report['builds'].append(m);save()
        print('Build seconds:',m['wall_seconds'],'bytes:',m['cache_bytes'],flush=True)
    scene=sample_clouds(paths);xy=scene[0][:,:2];center=np.median(xy,axis=0)
    values,vectors=np.linalg.eigh(np.cov(xy.T));along=vectors[:,-1];across=np.array([-along[1],along[0]])
    stations=(xy-center)@along;lo,hi=np.percentile(stations,[5,95]);queries=[]
    for f in (.25,.5,.75):
        middle=center+along*(lo+(hi-lo)*f)
        queries.append(dict(name=f'across_{int(f*100)}',start=(middle-across*100).tolist(),end=(middle+across*100).tolist(),width=3.,limit=100000))
    queries.append(dict(name='along',start=(center+along*lo).tolist(),end=(center+along*hi).tolist(),width=3.,limit=100000))
    queries.append(dict(name='wide_sampled',start=(center+along*lo).tolist(),end=(center+along*hi).tolist(),width=200.,limit=1000))
    far=xy.max(axis=0)+1000;queries.append(dict(name='outside',start=far.tolist(),end=(far+[100,100]).tolist(),width=3.,limit=100))
    report['queries']=queries;save()
    del scene,xy
    for repeat in range(1,repeats+1):
        for q in queries:
            results={};metrics={};kwargs={k:q[k] for k in ('start','end','width','limit')}
            order=['scan','cache'] if repeat%2 else ['cache','scan']
            for mode in order:
                stats={};name=f'{q["name"]}_{repeat}_{mode}'
                fn=(lambda:extract_section(paths,**kwargs)) if mode=='scan' else (lambda:extract(caches,**kwargs,stats=stats))
                result,m=measure(name,fn,out);results[mode]=result
                m.update(mode=mode,query=q['name'],repeat=repeat,matched=result.matched,displayed=len(result.points),stats=stats);metrics[mode]=m
                print(name,round(m['wall_seconds'],3),'s;',result.matched,'matches',flush=True)
            assert_equal(results['scan'],results['cache'])
            for m in metrics.values():m['exact_agreement']=True;report['benchmarks'].append(m)
            save()
    assert report['inputs']==[identity(p) for p in paths]
    report['source_metadata_unchanged']=True;report['status']='completed';save()
    lines=['# Spatial section-cache experiment — September 24, 2026','',
    f'Inputs: {sum(m["stats"].get("source_points",0) for m in report["benchmarks"][:2]):,} points (see JSON for authoritative per-query totals).',
    'Two repeats per query, with scan/cache order reversed on the second repeat. cProfile enabled; OS/network caches not flushed.',
    '', '| Query | Matches | Scan median (s) | Cache median (s) | Speedup | Candidate fraction |', '|---|---:|---:|---:|---:|---:|']
    savings=[]
    for q in queries:
        ms=[m for m in report['benchmarks'] if m['query']==q['name']];scan=statistics.median(m['wall_seconds'] for m in ms if m['mode']=='scan');cached=statistics.median(m['wall_seconds'] for m in ms if m['mode']=='cache');cm=next(m for m in ms if m['mode']=='cache');savings.append(scan-cached)
        lines.append(f'| {q["name"]} | {cm["matched"]:,} | {scan:.3f} | {cached:.3f} | {scan/cached:.1f}x | {cm["stats"]["candidate_points"]/cm["stats"]["source_points"]:.1%} |')
    build_s=sum(m['wall_seconds'] for m in report['builds']);disk=sum(m['cache_bytes'] for m in report['builds']);mean_saving=statistics.mean(savings)
    lines+=['',f'Cache build: {build_s:.2f} seconds; cache disk size: {disk/1024**3:.3f} GiB.',f'Build cost / mean query saving: {build_s/mean_saving:.1f} queries for this equal-weight query mix.' if mean_saving>0 else 'No positive mean saving; no break-even.',
    '', 'Every query agreed exactly with the reference scan: total/per-file counts, displayed coordinates, classifications, flight-line IDs, original point indices and sampled order. Empty and heavily sampled sections were included.',
    '',f'Largest sampled process RSS: {max(m["rss_peak_sampled_bytes"] for m in report["builds"]+report["benchmarks"])/1024**3:.3f} GiB. Process-wide 25 ms sampling, not isolated allocation peak.',
    '', 'This is an experimental local sidecar, not a LAS replacement. It stores chunked, spatially sorted XYZ/class/line/original-index records; source-order replay preserves existing sampling behavior.',
    '', 'Limitations: metadata-only invalidation cannot detect content changes with deliberately preserved size/mtime. No cryptographic cache-integrity check, automatic rebuild, eviction, multi-process writer coordination or GUI fallback is implemented. LAZ/COPC, other cell sizes and very large projects have not been benchmarked. The GUI remains unchanged.',
    '',f'Full evidence and profiles: {out.resolve()}/report.json','']
    (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cloud',action='append',required=True);p.add_argument('--out',required=True);p.add_argument('--repeats',type=int,default=2);a=p.parse_args();run(a.cloud,a.out,a.repeats)
