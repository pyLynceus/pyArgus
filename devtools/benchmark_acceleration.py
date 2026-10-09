"""Repeatable display/CPU-tile experiment; writes evidence only in build/."""
import argparse
import json
import platform
from pathlib import Path
import statistics
import time
import numpy as np

def median(values):
    return dict(median_ms=1000*statistics.median(values),runs_ms=[1000*v for v in values])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=Path("build/acceleration-20261008/benchmark.json"))
    args=parser.parse_args()
    from pyargus.viewer3d import Viewer
    from pyargus.classify import tiles
    from tests.test_tiled_ground import scene,reader_for
    import tkinter as tk
    result=dict(machine=platform.node(),platform=platform.platform(),method="Warm repeated Tk redraw, includes framebuffer readback and Tk idle presentation; synthetic morphology tiles exclude source-file IO")
    root=tk.Tk();root.withdraw()
    viewer=Viewer(root);viewer.window.geometry("1100x800")
    rng=np.random.default_rng(38)
    pts=rng.uniform(-200,200,(150000,3));pts[:,2]*=.1
    viewer.scene=(pts,rng.choice([2,5,6],len(pts)),np.zeros(len(pts),dtype=int),np.zeros(len(pts),dtype=int),len(pts),None)
    viewer.visible=[tk.BooleanVar(master=viewer.window,value=True)]
    viewer.center=np.zeros(3);viewer.span=600
    try:
        root.update()
        result["canvas"]=[viewer.canvas.winfo_width(),viewer.canvas.winfo_height()]
        if min(result["canvas"])<100:raise RuntimeError("Invalid benchmark viewport")
        result["display_points"]=len(pts)
        result["frames"]={}
        for stereo in (False,True):
            viewer.stereo.set(stereo)
            for backend in ("CPU","GPU"):
                viewer.renderer.set(backend);viewer.change_renderer()
                if backend=="GPU" and viewer.gpu is None:raise RuntimeError(viewer.render_note.get())
                values=[]
                for frame in range(24):
                    viewer.yaw=25+frame*.8
                    started=time.perf_counter();viewer.draw();root.update_idletasks()
                    if frame>=4:values.append(time.perf_counter()-started)
                result["frames"][backend+("_stereo" if stereo else "_mono")]=median(values)
        result["gpu"]=viewer.gpu.device
        result["uploads"]=viewer.gpu.uploads
    finally:
        viewer.close();root.destroy()
    x,y,z=scene(seed=72,n=300000)
    result["tiles"]={}
    original=None
    # Alternate worker order across three repeats to reduce ordering bias.
    for repeat in range(3):
        for workers in ((1,2) if repeat%2==0 else (2,1)):
            held={};cpu=time.process_time();wall=time.perf_counter()
            surface=tiles.tiled_surface(reader_for(x,y,z),[0,0],[900,900],
                cell=3.,window=30.,tile_size=225.,workers=workers,stats=held)
            row=dict(wall_seconds=time.perf_counter()-wall,cpu_seconds=time.process_time()-cpu,**held)
            if original is None:original=surface
            for name in ("dem","dem_slope","object_cells","low_cells"):
                np.testing.assert_array_equal(getattr(surface,name),getattr(original,name))
            result["tiles"].setdefault(str(workers),[]).append(row)
    result["tiles_exact"]=True
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(dict(gpu=result["gpu"],frames={k:v["median_ms"] for k,v in result["frames"].items()},
                         tiles={k:statistics.median(v["wall_seconds"] for v in values) for k,values in result["tiles"].items()},
                         evidence=str(args.out.resolve())),indent=2),flush=True)
if __name__=="__main__":
    main()
