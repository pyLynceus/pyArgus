"""Read-only, bounded 3D inspection for the Tk desktop. No analysis mutations."""
import math
import queue
import threading
import time
from pathlib import Path
import numpy as np


def sample_clouds(paths, limit=150000, cancel=None, progress=lambda s: None):
    import laspy
    headers = []
    crs = None
    for path in paths:
        with laspy.open(path) as source:
            current = source.header.parse_crs()
            if current is None or not current.is_projected:
                raise ValueError('3D multi-file viewing requires a declared projected LAS CRS.')
            if crs is not None and current != crs:
                raise ValueError('Cloud coordinate systems differ; reproject before viewing together.')
            crs = current
            factors = [a.unit_conversion_factor for a in current.axis_info]
            if not np.allclose(factors, factors[0], rtol=1e-12, atol=0):
                raise ValueError('3D viewing requires matching XYZ units.')
            headers.append(source.header.point_count)
    total = sum(headers)
    if not total or limit < 1:
        raise ValueError('Select nonempty clouds and a positive sample limit.')
    step = max(1, math.ceil(total / limit))
    xyz, classes, lines, files = [], [], [], []
    offset = 0
    for file_id, (path, count) in enumerate(zip(paths, headers)):
        progress(f'Reading {Path(path).name}')
        with laspy.open(path) as source:
            for chunk in source.chunk_iterator(250000):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('Loading stopped')
                ids = np.arange((-offset) % step, len(chunk), step)
                xyz.append(np.column_stack((chunk.x[ids], chunk.y[ids], chunk.z[ids])))
                classes.append(np.asarray(chunk.classification)[ids])
                lines.append(np.asarray(chunk.point_source_id)[ids])
                files.append(np.full(len(ids), file_id, dtype=np.int32))
                offset += len(chunk)
    points = np.concatenate(xyz)
    if not np.isfinite(points).all():
        raise ValueError('Cloud contains nonfinite positions.')
    return points, np.concatenate(classes), np.concatenate(lines), np.concatenate(files), total, crs


def sample_viewport(paths, center, yaw, pitch, bounds, limit=150000, cancel=None, progress=lambda s:None, stereo_depth=0.):
    import laspy
    from pyargus.job_manifest import identity
    from pyargus.viewport_cache import mask
    signatures=[identity(p) for p in paths]
    rng=np.random.default_rng(0); keys=np.empty(0); points=np.empty((0,3))
    classes=np.empty(0,dtype=np.uint8); lines=np.empty(0,dtype=np.uint16); files=np.empty(0,dtype=np.int32)
    matched=0; crs=None
    for file_id,path in enumerate(paths):
        progress(f'Refining visible area: {Path(path).name}')
        with laspy.open(path) as source:
            current=source.header.parse_crs()
            if current is None or not current.is_projected or (crs is not None and crs!=current):
                raise ValueError('Refinement requires a common projected CRS.')
            crs=current
            for chunk in source.chunk_iterator(250000):
                if cancel is not None and cancel.is_set(): raise InterruptedError('Refinement stopped')
                xyz=np.column_stack([chunk.x,chunk.y,chunk.z]); q=project_points(xyz,center,yaw,pitch)
                keep=np.isfinite(xyz).all(axis=1)&mask(q,bounds,stereo_depth)
                n=int(keep.sum()); matched+=n
                keys=np.r_[keys,rng.random(n)]; points=np.concatenate([points,xyz[keep]])
                classes=np.r_[classes,np.asarray(chunk.classification)[keep]]
                lines=np.r_[lines,np.asarray(chunk.point_source_id)[keep]]; files=np.r_[files,np.full(n,file_id,dtype=np.int32)]
                if len(keys)>limit:
                    chosen=np.argpartition(keys,limit-1)[:limit]
                    keys,points,classes,lines,files=(v[chosen] for v in (keys,points,classes,lines,files))
    if signatures!=[identity(p) for p in paths]: raise ValueError('Cloud changed during refinement')
    return points,classes,lines,files,matched,crs


def project_points(points, center, yaw, pitch):
    """Orthographic camera, right/up/depth; subtract origin before rotation."""
    a, b = np.deg2rad([yaw, pitch])
    right = np.array([np.cos(a), np.sin(a), 0.])
    up = np.array([-np.sin(a)*np.sin(b), np.cos(a)*np.sin(b), np.cos(b)])
    depth = np.cross(right, up)
    return (points - center) @ np.stack((right, up, depth)).T


def colors(points, classes, lines, mode):
    if not len(points):return np.empty((0,3),dtype=np.uint8)
    if mode == 'Elevation':
        z = points[:, 2]
        t = (z-z.min()) / max(float(np.ptp(z)), 1e-9)
        return np.column_stack((255*t, 210*(1-abs(2*t-1))+30, 255*(1-t))).astype('uint8')
    if mode == 'Classification':
        from pyargus.stage_preview import class_colors
        return class_colors(classes)
    ids = lines
    palette = np.array([[58,190,255],[255,171,65],[113,222,129],[221,115,250],
                        [255,105,125],[235,223,85],[90,221,204],[190,185,255]], dtype='uint8')
    return palette[np.asarray(ids, dtype=int) % len(palette)]


class Viewer:
    def __init__(self, root, paths=(), parent=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.window = ttk.Frame(parent) if parent is not None else tk.Toplevel(root)
        if parent is not None: self.window.pack(fill='both',expand=True)
        else:
            self.window.title('pyArgus â€” 3D point cloud')
            self.window.geometry('1100x760')
            self.window.protocol('WM_DELETE_WINDOW', self.close)
        from pyargus.section_cache_store import CacheStore
        self.view_cache=CacheStore();self.overview_scene=None;self.auto_observed=None;self.auto_attempted=None;self.auto_moved=0.;self.detail_job=False
        self.on_import_tracks=None; self.track_paths=[]
        self.linework_geometry=None;self.on_linework=None;self.view_history=[];self.last_wheel=0.;self.choose_pivot=False
        self.on_feature_draw=None; self.feature_geometry=None
        self.on_note_draw=None;self.note_geometry=None;self.on_note_click=None;self.on_issue_pick=None;self.issue_armed=lambda:False
        self.review_only_paths=set()
        self.paths=(); self.on_point=None; self.on_section=None; self.corridor=None; self.corridor_editor=None
        self.class_filter=None; self.line_filter=None; self.extra_layers=[]; self.extra_points=[]
        self.cancel = threading.Event()
        self.messages = queue.Queue()
        self.busy = False
        self.scene = None
        self.gpu=None;self.gpu_failed=False;self.pick_dirty=False;self.color_key=None
        self.tracks = []
        self.pending = None
        self.orbit_anchor = None
        self.yaw, self.pitch, self.zoom = 25., 45., 1.
        self.pan = np.zeros(2)
        bar = ttk.Frame(self.window); bar.pack(fill='x')
        self.buttons = []
        for label, action in [('Open LAS/LAZâ€¦',self.choose),('Add tracksâ€¦',self.track),('Fit',self.fit),
                              ('Top',lambda:self.view(0,90)),('Front',lambda:self.view(0,0)),
                              ('Side',lambda:self.view(90,0)),('Oblique',lambda:self.view(25,45)),
                              ('Fit selected',self.fit_selected),('Refine view',self.refine),('Whole project',lambda:self.load(self.paths))]:
            button = ttk.Button(bar,text=label,command=action); button.pack(side='left')
            self.buttons.append(button)
        display_bar=ttk.Frame(self.window);display_bar.pack(fill='x')
        self.mode = tk.StringVar(value='Flight line')
        combo = ttk.Combobox(display_bar,textvariable=self.mode,values=('Flight line','Elevation','Classification'),state='readonly',width=14)
        combo.pack(side='left'); combo.bind('<<ComboboxSelected>>',lambda e:self.draw())
        ttk.Button(display_bar,text='Stop loading',command=self.stop_loading).pack(side='left')
        self.stereo=tk.BooleanVar(value=False);self.stereo_depth=tk.DoubleVar(value=2.0);self.stereo_swap=tk.BooleanVar(value=False)
        ttk.Checkbutton(display_bar,text='Anaglyph',variable=self.stereo,command=self.draw).pack(side='left',padx=4)
        ttk.Label(display_bar,text='Depth').pack(side='left')
        ttk.Scale(display_bar,from_=0,to=6,variable=self.stereo_depth,command=lambda value:self.schedule(),length=100).pack(side='left')
        ttk.Checkbutton(display_bar,text='Swap eyes',variable=self.stereo_swap,command=self.draw).pack(side='left')
        ttk.Button(display_bar,text='Previous view',command=self.previous_view).pack(side='left')
        ttk.Button(display_bar,text='Set orbit center',command=self.arm_pivot).pack(side='left')
        self.renderer=tk.StringVar(value='Auto')
        renderer=ttk.Combobox(display_bar,textvariable=self.renderer,values=('Auto','GPU','CPU'),state='readonly',width=5)
        renderer.pack(side='left',padx=4);renderer.bind('<<ComboboxSelected>>',self.change_renderer)
        self.render_note=tk.StringVar(value='Renderer: waiting for a cloud')
        ttk.Label(display_bar,textvariable=self.render_note,width=1).pack(side='left',fill='x',expand=True)

        detailbar=ttk.Frame(self.window);detailbar.pack(fill='x')
        self.auto_detail=tk.BooleanVar(value=False)
        ttk.Checkbutton(detailbar,text='Auto detail (local cache)',variable=self.auto_detail,command=self.reset_auto).pack(side='left')
        ttk.Button(detailbar,text='Build view cache',command=self.build_view_cache).pack(side='left')
        self.detail_note=tk.StringVar(value='Auto detail needs a local cache; manual Refine can scan source files.')
        ttk.Label(detailbar,textvariable=self.detail_note,width=1,anchor='w').pack(side='left',fill='x',expand=True)


        ttk.Label(self.window,text='Left drag: orbit  â€¢  Right drag: pan  â€¢  Wheel: zoom  â€¢  Double click: fit  |  Orthographic 3D; Z scale 1:1').pack(anchor='w')
        body = ttk.Frame(self.window); body.pack(fill='both',expand=True)
        self.layers = ttk.Frame(body,width=180); self.layers.pack(side='right',fill='y')
        self.canvas = tk.Canvas(body,bg='#101925',highlightthickness=0)
        self.canvas.pack(side='left',fill='both',expand=True)
        self.visible = []
        self.canvas.bind('<Configure>',lambda e:self.schedule())
        self.canvas.bind('<Shift-Button-1>',self.pick_point)
        self.canvas.bind('<Control-Button-1>',self.pick_section)
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<ButtonPress-3>',self.press)
        self.canvas.bind('<B1-Motion>',self.orbit)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Escape>',lambda e:setattr(self,'choose_pivot',False))
        self.canvas.bind('<Shift-Double-Button-1>',self.pick_point)
        self.canvas.bind('<Control-Double-Button-1>',self.pick_section)
        self.canvas.bind('<B3-Motion>',self.move)
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Double-Button-1>',self.double_click)
        self.status = tk.StringVar(value='Choose LAS/LAZ files to inspect')
        ttk.Label(self.window,textvariable=self.status,width=1,anchor='w').pack(fill='x')
        self.window.bind('<Destroy>',self.destroy_renderer,add='+')
        self.poll_id = self.window.after(100,self.poll)
        if paths: self.load(paths)

    def choose(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(parent=self.window,filetypes=(('Point clouds','*.las *.laz'),))
        if paths: self.load(paths)

    def launch(self, work):
        # Finalize abandoned Tk objects on their owning UI thread.
        import gc
        gc.collect()
        if self.busy: return
        self.busy = True; self.cancel.clear(); self.started = time.monotonic()
        for b in self.buttons[:2]: b.configure(state='disabled')
        def run():
            try: self.messages.put(('done',work()))
            except Exception as exc: self.messages.put(('error',str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def load(self, paths):
        self.cancel_corridor_drag()
        paths = tuple(dict.fromkeys(paths))
        self.launch(lambda: ('cloud',paths,sample_clouds(paths,cancel=self.cancel,
                    progress=lambda s:self.messages.put(('progress',s)))))

    def track(self, paths=None):
        from tkinter import filedialog, messagebox, simpledialog
        if self.scene is None: return
        if paths is None: paths = filedialog.askopenfilenames(parent=self.window,filetypes=(('Trajectories','*.trj *.out'),))
        if not paths: return
        if self.busy: return
        paths=tuple(str(Path(p).resolve()) for p in paths)
        if self.on_import_tracks: self.on_import_tracks(paths)
        paths=tuple(p for p in paths if p not in self.track_paths)
        if not paths: return
        native = any(Path(p).suffix.lower()=='.trj' for p in paths)
        sbet = any(Path(p).suffix.lower()=='.out' for p in paths)
        if native and not messagebox.askyesno('Trajectory coordinates',
            'Do these TRJ files use the same easting, northing, elevation units and vertical datum as the displayed LAS? The TRJ format does not declare a CRS.',parent=self.window): return
        vertical = None
        if sbet:
            vertical = simpledialog.askstring('SBET height reference',
                'SBET input must be NAD83(2011), ellipsoidal meters.\nEnter the LAS vertical CRS (e.g. EPSG:6360), or geoid N in meters.\nThe cached geoid grid is required for a vertical CRS.',parent=self.window)
            if not vertical: return
            try: vertical=float(vertical)
            except ValueError: pass
        crs = self.scene[5]
        def work():
            from pyargus.formats.trj import read_trj
            result = []
            for path in paths:
                if self.cancel.is_set(): raise InterruptedError('Loading stopped')
                if Path(path).suffix.lower()=='.trj':
                    d = read_trj(path).records
                    positions = np.column_stack([d[n] for n in ('x','y','z')])
                else:
                    from pyargus.formats.sbet import read_sbet
                    from pyargus.formats.crs import sbet_to_map
                    from pyproj import CRS
                    if isinstance(vertical,str):
                        vcrs = CRS.from_user_input(vertical)
                        if not vcrs.is_vertical or not np.isclose(vcrs.axis_info[0].unit_conversion_factor,crs.axis_info[0].unit_conversion_factor,rtol=1e-12,atol=0):
                            raise ValueError('SBET vertical CRS units must match LAS XYZ units.')
                    elif not np.isfinite(vertical):
                        raise ValueError('Geoid N must be finite.')
                    d = read_sbet(path)
                    positions = np.column_stack(sbet_to_map(d,crs,vertical=vertical))
                # Keep separate segments across outages; never connect different files.
                split = np.split(np.arange(len(d)),np.flatnonzero(np.diff(d['time']) > 1.)+1)
                segments = [positions[i[np.unique(np.r_[np.arange(0,len(i),max(1,math.ceil(len(i)/3000))),len(i)-1])]] for i in split if len(i)>1]
                result.append((str(Path(path).resolve()),segments))
            return ('tracks',result)
        self.launch(work)

    def poll(self):
        from tkinter import ttk
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'progress': self.status.set(value); continue
                self.busy = False
                self.detail_job=False
                for b in self.buttons[:2]: b.configure(state='normal')
                if kind == 'error': self.status.set('Stopped' if self.cancel.is_set() else 'Failed: '+value); continue
                if self.cancel.is_set(): self.status.set('Stopped'); continue
                if value[0]=='view-cache':
                    self.detail_note.set(value[1]);self.status.set(value[1]);self.auto_attempted=None;continue
                if value[0]=='linework':
                    try:self.on_linework(value[1],value[2]);self.status.set('DXF imported; see Linework for layers and skipped entities.')
                    except Exception as exc:self.status.set('DXF import failed: '+str(exc))
                    continue
                if value[0] in ('cloud','review-cloud'):
                    _,paths,scene,*camera = value
                    # Review loads preserve the latest camera even if the operator navigated while loading.
                    keep_camera=self.camera_state() if value[0]=='review-cloud' and self.scene is not None else camera[0] if camera else None
                    if value[0]=='review-cloud':self.review_only_paths.update(paths)
                    self.adopt_cloud(paths,scene,keep_camera)
                elif value[0]=='refined':
                    if len(value)>2 and value[2]!=self.view_key():
                        self.detail_note.set('View moved; older detail result discarded.');continue
                    self.scene=value[1]
                    self.detail_note.set(value[3] if len(value)>3 else 'Local detail')
                    self.draw()
                else:
                    for path,segments in value[1]:
                        name=Path(path).name
                        self.track_paths.append(path)
                        var = self.tk.BooleanVar(value=True)
                        self.tracks.append((segments,var))
                        ttk.Checkbutton(self.layers,text=name,variable=var,command=self.draw).pack(anchor='w')
                    self.draw()
                self.status.set(f'Finished in {time.monotonic()-self.started:.1f}s | Displaying {len(self.scene[0]):,} of {self.scene[4]:,} points (display sample; Refine view scans local detail; source unchanged)')
        except queue.Empty: pass
        if self.busy: self.status.set(f'Loading â€” elapsed {time.monotonic()-self.started:.0f}s')
        self.auto_tick()
        self.poll_id = self.window.after(100,self.poll)

    def camera_state(self):
        scale=min(max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height()))*.85/self.span*self.zoom
        return dict(center=self.center.tolist(),pan_units=(self.pan/scale).tolist(),yaw=self.yaw,pitch=self.pitch,zoom=self.zoom,span=self.span)

    def adopt_cloud(self,paths,scene,camera=None):
        """Install a bounded display sample; review callers may retain its camera."""
        from tkinter import ttk
        if camera is None:self.view_history.clear()
        self.choose_pivot=False;self.paths=tuple(paths);self.scene=scene;self.overview_scene=scene;self.auto_attempted=None
        self.track_paths=[];self.tracks=[];self.visible=[];self.extra_layers=[];self.extra_points=[]
        for child in self.layers.winfo_children():child.destroy()
        ttk.Label(self.layers,text='Visible files').pack(anchor='w')
        for path in paths:
            var=self.tk.BooleanVar(value=True);self.visible.append(var)
            ttk.Checkbutton(self.layers,text=Path(path).name,variable=var,command=self.draw).pack(anchor='w')
        if camera is None:
            points=scene[0];self.center=(points.min(axis=0)+points.max(axis=0))/2
            self.span=max(float(np.linalg.norm(np.ptp(points,axis=0))),1.);self.fit()
        else:
            self.center=np.array(camera['center'],dtype=float)
            for key in ('yaw','pitch','zoom','span'):setattr(self,key,camera[key])
            scale=min(max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height()))*.85/self.span*self.zoom
            self.pan=np.array(camera['pan_units'])*scale;self.draw()

    def cancel_corridor_drag(self):
        if self.corridor_editor:self.corridor_editor.cancel()

    def press(self,e):
        if getattr(e,'num',1)==1 and (self.choose_pivot or self.issue_armed()):return self.pick_point(e)
        if getattr(e,'num',1)==1 and self.corridor_editor and self.corridor_editor.press(e):return 'break'
        if getattr(e,'num',1)==1 and self.on_note_click and self.on_note_click(e):return 'break'
        self.cancel_corridor_drag()
        if not (getattr(e,'state',0)&5):self.remember_view()
        self.last=(e.x,e.y)
        self.orbit_anchor=(e.x,e.y) if getattr(e,'num',1)==1 and not (getattr(e,'state',0)&5) else None

    def release(self,e):
        if self.corridor_editor and self.corridor_editor.release(e):
            self.orbit_anchor=None;return 'break'
        self.orbit_anchor=None

    def double_click(self,e):
        self.orbit_anchor=None
        if self.corridor_editor and self.corridor_editor.hit(e):return 'break'
        if self.issue_armed():return 'break'
        if self.on_note_click and self.on_note_click(e):return 'break'
        if not (getattr(e,'state',0)&5):self.fit()
        return 'break'

    def orbit(self,e):
        if self.corridor_editor and self.corridor_editor.motion(e):return 'break'
        if getattr(e,'state',0)&5:
            self.orbit_anchor=None;return 'break'
        if self.orbit_anchor is None:return 'break'
        x,y=self.orbit_anchor
        self.yaw+=(e.x-x)*.4;self.pitch=np.clip(self.pitch+(e.y-y)*.4,-90,90)
        self.orbit_anchor=(e.x,e.y);self.schedule()

    def move(self,e):
        self.cancel_corridor_drag()
        self.pan += np.array([e.x-self.last[0],e.y-self.last[1]])
        self.last=(e.x,e.y); self.schedule()
    def remember_view(self):
        if self.scene is None or not hasattr(self,'center'):return
        state=(self.yaw,self.pitch,self.zoom,tuple(self.pan),tuple(self.center),self.span)
        if not self.view_history or self.view_history[-1]!=state:self.view_history.append(state)
        self.view_history=self.view_history[-40:]

    def previous_view(self):
        self.cancel_corridor_drag()
        if not self.view_history:return
        self.yaw,self.pitch,self.zoom,pan,center,self.span=self.view_history.pop()
        self.pan=np.array(pan);self.center=np.array(center);self.draw()

    def arm_pivot(self):
        self.cancel_corridor_drag()
        if self.stereo.get():self.status.set('Turn off Anaglyph, then set the orbit center.');return
        self.choose_pivot=True;self.status.set('Click a displayed cloud point to set the orbit center (Esc cancels).')
        self.canvas.focus_set()

    def wheel(self,e):
        self.cancel_corridor_drag()
        if time.monotonic()-self.last_wheel>.4:self.remember_view()
        self.last_wheel=time.monotonic()
        old=self.zoom;self.zoom=float(np.clip(old*1.15**(e.delta/120),.05,100))
        anchor=np.array([e.x-self.canvas.winfo_width()/2,e.y-self.canvas.winfo_height()/2])
        self.pan=anchor-(anchor-self.pan)*(self.zoom/old)
        self.schedule()

    def fit(self):
        self.cancel_corridor_drag()
        self.remember_view();self.zoom=1.;self.pan[:]=0;self.draw()
    def view(self,yaw,pitch):
        self.cancel_corridor_drag()
        self.remember_view();self.yaw=yaw;self.pitch=pitch;self.draw()
    def schedule(self):
        if self.pending is None: self.pending=self.window.after(30,self.draw)
    @property
    def pick_xy(self):
        # Existing review callers may inspect picking coordinates directly.
        # Build them only when requested rather than on every GPU redraw.
        if self.scene is not None and self.pick_dirty:
            pts,cls,lines,files,*_=self.scene
            keep=np.array([v.get() for v in self.visible],dtype=bool)[files]
            if self.class_filter is not None:keep &= np.isin(cls,self.class_filter)
            if self.line_filter is not None:keep &= lines==self.line_filter
            w,h=max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height())
            self.update_picks(pts,keep,min(w,h)*.85/self.span*self.zoom,w,h)
        return getattr(self,'_pick_xy',np.empty((0,2)))

    @pick_xy.setter
    def pick_xy(self,value):
        self._pick_xy=value
        self.pick_dirty=False

    def destroy_renderer(self,event):
        if event.widget is self.window and self.gpu is not None:
            self.gpu.close();self.gpu=None

    def change_renderer(self,event=None):
        self.gpu_failed=False
        self.draw()

    def point_colors(self,pts,cls,lines,files):
        key=(id(self.scene),self.mode.get())
        if key!=self.color_key or getattr(self,'color_scene',None) is not self.scene:
            self.color_scene=self.scene
            self.color_values=colors(pts,cls,files if self.mode.get()=='Dataset' else
                                     lines.astype(np.int64)+files.astype(np.int64)*65537,self.mode.get())
            self.color_key=key
        return self.color_values

    def gpu_pixels(self,pts,cls,lines,files,keep,scale,w,h,stereo=False):
        if self.renderer.get()=='CPU':
            self.render_note.set('CPU renderer');return None
        if self.gpu_failed:
            return None
        try:
            if self.gpu is None:
                from pyargus.gpu_renderer import Renderer
                self.gpu=Renderer()
            key=(id(self.scene),id(pts),self.mode.get(),tuple(v.get() for v in self.visible),
                 None if self.class_filter is None else tuple(self.class_filter),self.line_filter)
            pixels=self.gpu.render(pts,self.point_colors(pts,cls,lines,files),
                self.center,self.yaw,self.pitch,scale,w,h,self.pan,keep=keep,key=key,
                stereo_depth=float(self.stereo_depth.get()) if stereo else None,
                swap=self.stereo_swap.get(),linework=self.linework_geometry() if self.linework_geometry else ())
            self.render_note.set('GPU: '+self.gpu.device)
            return pixels
        except Exception as exc:
            if self.gpu is not None:
                try:self.gpu.close()
                except Exception:pass
                self.gpu=None
            self.gpu_failed=True
            self.render_note.set('CPU fallback: '+str(exc))
            return None

    def update_picks(self,pts,keep,scale,w,h):
        q=project_points(pts[keep],self.center,self.yaw,self.pitch)
        xy=np.rint(q[:,:2]*[scale,-scale]+[w/2,h/2]+self.pan).astype(int)
        inside=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
        self.pick_ids=np.flatnonzero(keep)[inside]
        self.pick_xy=xy[inside];self.pick_depth=q[inside,2]
        self.pick_dirty=False
        return q,xy,inside

    def draw(self):
        from PIL import Image, ImageTk
        if self.pending is not None: self.window.after_cancel(self.pending); self.pending=None
        if self.scene is None: return
        editor=self.corridor_editor
        if editor and editor.drag is not None and (not editor.ready() or editor.context()!=editor.drag['context']):
            editor.cancel();return
        w,h = max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height())
        scale = min(w,h)*.85/self.span*self.zoom
        pts,cls,lines,files,*_ = self.scene
        keep = np.array([v.get() for v in self.visible],dtype=bool)[files]
        if self.class_filter is not None: keep &= np.isin(cls,self.class_filter)
        if self.line_filter is not None: keep &= lines==self.line_filter
        if self.stereo.get():
            self.draw_stereo(pts,cls,lines,files,keep,scale,w,h)
            return
        pixels=self.gpu_pixels(pts,cls,lines,files,keep,scale,w,h)
        self.pick_dirty=pixels is not None
        if pixels is None:
            q,xy,inside=self.update_picks(pts,keep,scale,w,h)
            rgb=self.point_colors(pts,cls,lines,files)[keep][inside]
            xy,q=xy[inside],q[inside]
            order=np.argsort(q[:,2],kind='stable')
            xy,rgb=xy[order],rgb[order]
            key=xy[:,1]*w+xy[:,0]
            _,rev=np.unique(key[::-1],return_index=True)
            take=len(key)-1-rev
            pixels=np.empty((h,w,3),dtype='uint8');pixels[:]=[16,25,37]
            pixels[xy[take,1],xy[take,0]]=rgb[take]
        for points,var in self.extra_points:
            if not var.get():continue
            q=project_points(points,self.center,self.yaw,self.pitch)
            xy=np.rint(q[:,:2]*[scale,-scale]+[w/2,h/2]+self.pan).astype(int)
            inside=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
            xy=xy[inside];pixels[xy[:,1],xy[:,0]]=[120,230,140]
        if self.linework_geometry and not self.pick_dirty:
            from pyargus.linework import paint
            geometry=[(project_points(points,self.center,self.yaw,self.pitch),color,width,top) for points,color,width,top in self.linework_geometry()]
            if geometry:paint(pixels,project_points(pts[keep],self.center,self.yaw,self.pitch),geometry,scale,self.pan)
        self.photo=ImageTk.PhotoImage(Image.fromarray(pixels),master=self.window)
        self.canvas.delete('all'); self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        for segments,var in self.tracks:
            if not var.get(): continue
            for segment in segments:
                t=project_points(segment,self.center,self.yaw,self.pitch)
                coords=t[:,:2]*[scale,-scale]+[w/2,h/2]+self.pan
                if len(coords)>1: self.canvas.create_line(*coords.ravel().tolist(),fill='#ffffff',width=2)
        for name,segments,var in self.extra_layers:
            if not var.get(): continue
            for segment in segments:
                t=project_points(segment,self.center,self.yaw,self.pitch)
                coords=t[:,:2]*[scale,-scale]+[w/2,h/2]+self.pan
                if len(coords)>1: self.canvas.create_line(*coords.ravel(),fill='#ffd15b',width=2)
                elif len(coords):
                    x,y=coords[0]; self.canvas.create_oval(x-4,y-4,x+4,y+4,outline='#ffd15b')
        if self.corridor is not None:
            a,b,width=self.corridor; delta=b-a; length=np.linalg.norm(delta)
            if length:
                side=np.array([-delta[1],delta[0]])/length*width/2
                xy=np.array([a+side,b+side,b-side,a-side,a+side])
                xyz=np.column_stack([xy,np.full(5,self.center[2])])
                t=project_points(xyz,self.center,self.yaw,self.pitch)
                coords=t[:,:2]*[scale,-scale]+[w/2,h/2]+self.pan
                self.canvas.create_line(*coords.ravel(),fill='#ffd15b',width=2)
        if self.on_feature_draw:self.on_feature_draw(scale,w,h)
        if self.corridor_editor:self.corridor_editor.draw()
        if self.on_note_draw:self.on_note_draw(scale,w,h)
        self.canvas.create_text(12,12,anchor='nw',fill='white',text=f'Yaw {self.yaw%360:.0f}Â°  Tilt {self.pitch:.0f}Â°  Zoom {self.zoom:.1f}Ã—\nTracks shown on top; '+('dataset colors repeat every 8 files' if self.mode.get()=='Dataset' else 'line colors repeat every 8 IDs'))

    def draw_stereo(self,pts,cls,lines,files,keep,scale,w,h):
        from PIL import Image, ImageTk
        from pyargus.anaglyph import render
        project=lambda points:project_points(np.asarray(points),self.center,self.yaw,self.pitch)
        overlays=[]
        for points,var in self.extra_points:
            if var.get():overlays.append((project(points),0,True))
        for segments,var in self.tracks:
            if var.get():
                overlays.extend((project(segment),2,False) for segment in segments)
        for name,segments,var in self.extra_layers:
            if var.get():overlays.extend((project(segment),2,False) for segment in segments)
        if self.feature_geometry:
            overlays.extend((project(points),width,vertices) for points,width,vertices in self.feature_geometry())
        if self.note_geometry:overlays.extend((project(points),0,True) for points in self.note_geometry())
        if self.corridor is not None:
            a,b,width=self.corridor;delta=b-a;length=np.linalg.norm(delta)
            if length:
                side=np.array([-delta[1],delta[0]])/length*width/2
                xy=np.array([a+side,b+side,b-side,a-side,a+side])
                overlays.append((project(np.column_stack([xy,np.full(5,self.center[2])])),2,False))
        rgb=self.point_colors(pts,cls,lines,files)[keep]
        pixels=self.gpu_pixels(pts,cls,lines,files,keep,scale,w,h,stereo=True)
        if pixels is None:
            linework=[(project(points),color,width,top) for points,color,width,top in self.linework_geometry()] if self.linework_geometry else []
            pixels=render(project(pts[keep]),rgb,scale,w,h,self.pan,float(self.stereo_depth.get()),self.stereo_swap.get(),overlays,linework=linework)
        else:
            from PIL import ImageDraw
            from pyargus.anaglyph import eye_pixels
            channels=[]
            for channel,eye in ((0,1),(1,-1)):
                if self.stereo_swap.get():eye=-eye
                image=Image.fromarray(pixels[:,:,channel]);draw=ImageDraw.Draw(image)
                for points,line_width,vertices in overlays:
                    coords=eye_pixels(points,scale,w,h,self.pan,float(self.stereo_depth.get()),eye)
                    if len(coords)>1 and line_width>0:draw.line([tuple(p) for p in coords],fill=240,width=line_width)
                    if vertices or len(coords)==1:
                        for x,y in coords:draw.ellipse((x-2,y-2,x+2,y+2),fill=240)
                channels.append(np.array(image))
            pixels=np.stack((channels[0],channels[1],channels[1]),axis=2)
        self.pick_ids=np.empty(0,dtype=int);self.pick_xy=np.empty((0,2));self.pick_depth=np.empty(0)
        self.photo=ImageTk.PhotoImage(Image.fromarray(pixels),master=self.window)
        self.canvas.delete('all');self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        self.canvas.create_text(12,12,anchor='nw',fill='white',text='Anaglyph | '+('cyan left / red right' if self.stereo_swap.get() else 'red left / cyan right')+
            f' | depth {self.stereo_depth.get():.1f}Â°\nGrayscale; overlays on top. Turn off Anaglyph to pick/edit points.')

    def view_key(self):
        if self.scene is None or not self.paths:return None
        return (tuple(self.paths),tuple(self.center),self.yaw,self.pitch,self.zoom,tuple(self.pan),self.span,
                max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height()),
                float(self.stereo_depth.get()) if self.stereo.get() else 0.)

    def reset_auto(self):
        self.auto_attempted=None;self.auto_observed=None
        if not self.auto_detail.get() and self.detail_job:self.cancel.set()

    def stop_loading(self):
        self.auto_detail.set(False);self.cancel.set()
        self.detail_note.set('Stopped; Auto detail is off. Re-enable to resume.')

    def build_view_cache(self):
        if self.busy or not self.paths:return
        paths=tuple(self.paths)
        self.launch(lambda:('view-cache',self.view_cache.build(paths,cancel=self.cancel,
            progress=lambda text:self.messages.put(('progress',text)))))

    def auto_tick(self):
        if not self.auto_detail.get():return
        key=self.view_key()
        if key is None:return
        now=time.monotonic()
        if key!=self.auto_observed:
            self.auto_observed=key;self.auto_moved=now
            if self.detail_job:self.cancel.set()
            if self.overview_scene is not None and self.scene is not self.overview_scene:
                self.scene=self.overview_scene;self.draw()
            self.detail_note.set('Navigating â€” overview; local detail follows after a pause.')
        if not self.busy and key!=self.auto_attempted and now-self.auto_moved>=.8:
            self.auto_attempted=key;self.refine(automatic=True)

    def refine(self,automatic=False):
        if self.busy or self.scene is None or not self.paths:return
        key=self.view_key();self.auto_attempted=key;w,h=key[7:9]
        scale=min(w,h)*.85/self.span*self.zoom
        bounds=((-w/2-self.pan[0])/scale,(w/2-self.pan[0])/scale,
                (-h/2+self.pan[1])/scale,(h/2+self.pan[1])/scale)
        center=self.center.copy();yaw,pitch=self.yaw,self.pitch;paths=tuple(self.paths);strength=key[9]
        def work():
            from pyargus.viewport_cache import extract
            progress=lambda text:self.messages.put(('progress',text))
            try:
                scene=extract(self.view_cache,paths,center,yaw,pitch,bounds,cancel=self.cancel,progress=progress,stereo_depth=strength)
                method='Local cache detail'
            except (OSError,ValueError,KeyError,TypeError) as exc:
                if isinstance(exc,InterruptedError):raise
                if automatic:
                    raise ValueError('Auto detail needs valid available caches. Click Build view cache, or use manual Refine. '+str(exc)) from exc
                progress('Cache unavailable; scanning source files for manual refinement.')
                scene=sample_viewport(paths,center,yaw,pitch,bounds,cancel=self.cancel,progress=progress,stereo_depth=strength)
                method='Full-scan detail (manual Refine)'
            return ('refined',scene,key,f'{method}: {len(scene[0]):,} displayed / {scene[4]:,} local points')
        self.launch(work);self.detail_job=True

    def pick_point(self,e):
        self.orbit_anchor=None
        if self.stereo.get():
            self.status.set('Turn off Anaglyph for unambiguous point picking and feature tracing.'); return 'break'
        if self.scene is not None and self.pick_dirty:
            pts,cls,lines,files,*_=self.scene
            keep=np.array([v.get() for v in self.visible],dtype=bool)[files]
            if self.class_filter is not None:keep &= np.isin(cls,self.class_filter)
            if self.line_filter is not None:keep &= lines==self.line_filter
            w,h=max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height())
            self.update_picks(pts,keep,min(w,h)*.85/self.span*self.zoom,w,h)
        if self.scene is None or not len(getattr(self,'pick_xy',[])): return 'break'
        distance=np.sum((self.pick_xy-[e.x,e.y])**2,axis=1)
        candidates=np.flatnonzero(distance<=64)
        if len(candidates):
            nearest=candidates[np.lexsort((-self.pick_depth[candidates],distance[candidates]))[0]]
            i=self.pick_ids[nearest]; p=self.scene[0][i]
            if self.choose_pivot:
                self.remember_view();self.choose_pivot=False
                w,h=self.canvas.winfo_width(),self.canvas.winfo_height()
                scale=min(w,h)*.85/self.span*self.zoom
                offset=project_points(np.array([p]),self.center,self.yaw,self.pitch)[0,:2]*[scale,-scale]
                self.pan+=offset;self.center=p.copy();self.draw()
                self.status.set('Orbit center set. Drag to rotate around that point.');return 'break'
            value=dict(x=float(p[0]),y=float(p[1]),z=float(p[2]),classification=int(self.scene[1][i]),
                       line=int(self.scene[2][i]),file=self.paths[int(self.scene[3][i])] if self.paths else '')
            self.status.set(f"Picked X {value['x']:.3f}  Y {value['y']:.3f}  Z {value['z']:.3f} | class {value['classification']} | line {value['line']} | {Path(value['file']).name}")
            if self.on_issue_pick and self.on_issue_pick(value):return 'break'
            if self.on_point: self.on_point(value)
        return 'break'

    def pick_section(self,e):
        self.cancel_corridor_drag()
        self.orbit_anchor=None
        if self.stereo.get():
            self.status.set('Turn off Anaglyph before picking section endpoints.'); return 'break'
        if self.scene is None: return 'break'
        if abs(self.pitch-90)>1e-6 or abs(self.yaw%360)>1e-6:
            self.status.set('Use Top view before Ctrl-clicking section endpoints.'); return 'break'
        w,h=max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height())
        scale=min(w,h)*.85/self.span*self.zoom
        xy=(np.array([e.x,e.y])-[w/2,h/2]-self.pan)/[scale,-scale]+self.center[:2]
        if self.on_section: self.on_section(xy)
        return 'break'

    def fit_selected(self):
        self.cancel_corridor_drag()
        if self.scene is None: return
        keep=np.array([v.get() for v in self.visible],dtype=bool)[self.scene[3]]
        if self.class_filter is not None: keep &= np.isin(self.scene[1],self.class_filter)
        if self.line_filter is not None: keep &= self.scene[2]==self.line_filter
        pts=self.scene[0][keep]
        if len(pts):
            self.remember_view()
            self.center=(pts.min(axis=0)+pts.max(axis=0))/2
            self.span=max(float(np.linalg.norm(np.ptp(pts,axis=0))),1.)
            self.zoom=1.;self.pan[:]=0;self.draw()

    def close(self):
        self.cancel.set()
        self.window.after_cancel(self.poll_id)
        if self.pending is not None: self.window.after_cancel(self.pending)
        if self.gpu is not None:self.gpu.close();self.gpu=None
        self.window.destroy()


def open_viewer(app):
    if hasattr(app,'workspace'):
        viewer=app.workspace.viewer
        if app.cloud_path.get() and not viewer.busy:viewer.load([app.cloud_path.get()])
        return viewer
    return Viewer(app.root,[app.cloud_path.get()] if app.cloud_path.get() else [])
