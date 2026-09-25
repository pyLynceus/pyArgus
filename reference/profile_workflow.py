"""Serial performance baseline; never changes source clouds or GUI workspaces.
Run: python -m reference.profile_workflow --cloud FILE [--cloud FILE] --out NEW_DIR
"""
import argparse
import cProfile
import ctypes
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import pstats
import shutil
import subprocess
import threading
import time


def rss_reader():
    """Current Windows working set, or unavailable; sampled, not allocation peak."""
    if os.name != 'nt':
        return lambda: None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    def read():
        counter=Counters();counter.cb=ctypes.sizeof(counter)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counter),counter.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counter.WorkingSetSize)
    return read


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def measure(name,work,out):
    gc.collect()
    read_rss=rss_reader();baseline=read_rss();samples=[];stop=threading.Event()
    def sample():
        while not stop.wait(.025):
            value=read_rss()
            if value is not None:samples.append(value)
    thread=threading.Thread(target=sample,daemon=True);thread.start()
    profiler=cProfile.Profile();cpu=time.process_time();start=time.perf_counter()
    try:
        profiler.enable();value=work();profiler.disable()
    finally:
        profiler.disable();elapsed=time.perf_counter()-start;cpu=time.process_time()-cpu
        stop.set();thread.join()
    final=read_rss();samples += [v for v in (baseline,final) if v is not None]
    profiler.dump_stats(str(out/(name+'.prof')))
    stats=pstats.Stats(profiler)
    top=[]
    for (filename,line,function),(primitive,calls,self_time,cumulative,callers) in sorted(stats.stats.items(),key=lambda kv:kv[1][3],reverse=True)[:30]:
        top.append(dict(file=filename,line=line,function=function,calls=calls,self_seconds=self_time,cumulative_seconds=cumulative))
    return value,dict(name=name,wall_seconds=elapsed,cpu_seconds=cpu,
        rss_start_bytes=baseline,rss_peak_sampled_bytes=max(samples) if samples else None,
        profile=name+'.prof',top_cumulative=top)


def scan(paths):
    import laspy
    count=0
    for path in paths:
        with laspy.open(path) as f:
            for chunk in f.chunk_iterator(250000):count+=len(chunk)
    return dict(points=count)


def redraw(scene):
    import tkinter as tk
    import numpy as np
    from pyargus.viewer3d import Viewer
    root=tk.Tk();root.attributes('-alpha',0.0);root.geometry('1100x760')
    viewer=Viewer(root,parent=root);root.update()
    try:
        if min(viewer.canvas.winfo_width(),viewer.canvas.winfo_height())<100:
            raise ValueError('Benchmark canvas has not been laid out; invalid redraw measurement')
        viewer.scene=scene;viewer.visible=[tk.BooleanVar(master=root,value=True) for _ in range(int(scene[3].max())+1)]
        viewer.center=(scene[0].min(axis=0)+scene[0].max(axis=0))/2
        viewer.span=max(float(np.linalg.norm(np.ptp(scene[0],axis=0))),1.)
        viewer.draw();viewer.window.update_idletasks()
        frames=[]
        for yaw in range(0,180,15):
            viewer.yaw=yaw;start=time.perf_counter();viewer.draw();viewer.window.update_idletasks();frames.append(time.perf_counter()-start)
        return dict(points=len(scene[0]),canvas=[viewer.canvas.winfo_width(),viewer.canvas.winfo_height()],frames_seconds=frames,median_frame_seconds=float(np.median(frames)),p95_frame_seconds=float(np.percentile(frames,95)))
    finally:
        viewer.close();root.destroy();gc.collect()


def run(paths,out,repeats=2,production=False):
    import laspy
    import numpy as np
    from pyargus.job_manifest import identity
    from pyargus.viewer3d import sample_clouds,sample_viewport
    from pyargus.sections import extract_section
    paths=[Path(p).resolve() for p in paths];out=Path(out).resolve()
    if not paths or len(set(paths))!=len(paths):raise ValueError('Provide distinct source clouds')
    if repeats<1:raise ValueError('Repeats must be positive')
    before=[identity(p) for p in paths]
    out.mkdir(parents=True,exist_ok=False)
    cache=out/'local-copies';cache.mkdir()
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    except (OSError,subprocess.CalledProcessError):commit=None
    report=dict(schema_version=1,harness_sha256=digest(__file__),source_commit=commit,python=platform.python_version(),platform=platform.platform(),inputs=before,
        notes=['cProfile enabled: instrumented timings, not application stopwatch timings.',
        'OS/server caches are not flushed; copy and hash verification warm caches. No cold-cache claim.',
        'CPU time includes all process threads; wall minus CPU is not a direct network-time measurement.',
        'RSS is process-wide, sampled every 25 ms; Python/native allocators retain memory across stages.',
        'QA uses local classified benchmark copies in BOTH variants, without trajectories; variant does not measure network QA. No accuracy claim.',
        'Redraw measures Tk draw plus idle updates at a fixed canvas/sample, not end-to-end mouse latency.'],copies=[],measurements=[])
    def save():
        temp=out/'report.tmp';temp.write_text(json.dumps(report,indent=2),encoding='utf-8');temp.replace(out/'report.json')
    local=[]
    for i,path in enumerate(paths):
        target=cache/f'{i:03d}_{path.name}'
        start=time.perf_counter();shutil.copy2(path,target);seconds=time.perf_counter()-start
        original_hash=digest(path);copy_hash=digest(target)
        if original_hash!=copy_hash:raise ValueError('Local copy hash mismatch')
        local.append(target);report['copies'].append(dict(source=str(path),local=str(target),sha256=copy_hash,copy_seconds=seconds))
        print('Verified local copy:',path.name,flush=True)
    with laspy.open(paths[0]) as f:
        lo=np.asarray(f.header.mins);hi=np.asarray(f.header.maxs)
    center=(lo+hi)/2;span=hi-lo
    start=[float(lo[0]+span[0]*.25),float(center[1])];end=[float(lo[0]+span[0]*.75),float(center[1])]
    width=3.;bounds=[-float(span[0])*.1,float(span[0])*.1,-float(span[1])*.1,float(span[1])*.1]
    report['parameters']=dict(section_start=start,section_end=end,section_width=width,refine_center=center.tolist(),refine_bounds=bounds,sample_limit=150000,repeats=repeats,classification=dict(cell=3.,slope=.15,window=60.,threshold=1.5),production=production)
    save()
    def timed(variant,repeat,operation,work,summary=lambda value:value):
        name=f'{variant}_{repeat}_{operation}';print('Starting',name,flush=True)
        value,metrics=measure(name,work,out)
        metrics.update(variant=variant,repeat=repeat,operation=operation,result=summary(value))
        report['measurements'].append(metrics);save();print(f'{name}: {metrics["wall_seconds"]:.3f}s wall, {metrics["cpu_seconds"]:.3f}s CPU',flush=True)
        return value
    for repeat in range(1,repeats+1):
        variants=[('source',paths),('local',local)]
        if repeat%2==0:variants.reverse()
        for variant,files in variants:
            files=list(map(str,files))
            timed(variant,repeat,'scan',lambda:scan(files))
            scene=timed(variant,repeat,'overview',lambda:sample_clouds(files),lambda s:dict(displayed=len(s[0]),total=s[4]))
            timed(variant,repeat,'redraw',lambda:redraw(scene))
            del scene
            timed(variant,repeat,'section',lambda:extract_section(files,start,end,width),lambda s:dict(matched=s.matched,displayed=len(s.points)))
            timed(variant,repeat,'refine',lambda:sample_viewport(files,center,0.,90.,bounds),lambda s:dict(matched=s[4],displayed=len(s[0])))
            if production:
                from pyargus.classify.job import classify_ground_whole
                from pyargus.project import Project,qa
                classified=[]
                for i,path in enumerate(files):
                    target=out/f'{variant}_{repeat}_{i}_BENCHMARK_ONLY.las';classified.append(str(target))
                    timed(variant,repeat,f'classify_{i}',lambda p=path,t=target:classify_ground_whole(p,t,cell=3.,slope=.15,window=60.,threshold=1.5,log=lambda _:None))
                timed(variant,repeat,'qa',lambda:qa(Project(classified,same_vertical=True,max_points=1),out/f'{variant}_{repeat}_qa'),lambda s:dict(mode=s.get('mode'),points=s.get('points')))
    if before!=[identity(p) for p in paths]:raise ValueError('Source metadata changed during benchmark')
    report['source_metadata_unchanged']=True;report['status']='completed';save()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cloud',action='append',required=True);p.add_argument('--out',required=True)
    p.add_argument('--repeats',type=int,default=2)
    p.add_argument('--production',action='store_true',help='Also create separate benchmark-only classification and disk-QA outputs')
    a=p.parse_args();run(a.cloud,a.out,a.repeats,a.production)

if __name__=='__main__':main()
