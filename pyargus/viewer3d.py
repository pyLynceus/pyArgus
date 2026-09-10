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


def project_points(points, center, yaw, pitch):
    """Orthographic camera, right/up/depth; subtract origin before rotation."""
    a, b = np.deg2rad([yaw, pitch])
    right = np.array([np.cos(a), np.sin(a), 0.])
    up = np.array([-np.sin(a)*np.sin(b), np.cos(a)*np.sin(b), np.cos(b)])
    depth = np.cross(right, up)
    return (points - center) @ np.stack((right, up, depth)).T


def colors(points, classes, lines, mode):
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
    def __init__(self, root, paths=()):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.window = tk.Toplevel(root)
        self.window.title('pyArgus — 3D point cloud')
        self.window.geometry('1100x760')
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.cancel = threading.Event()
        self.messages = queue.Queue()
        self.busy = False
        self.scene = None
        self.tracks = []
        self.pending = None
        self.yaw, self.pitch, self.zoom = 25., 45., 1.
        self.pan = np.zeros(2)
        bar = ttk.Frame(self.window); bar.pack(fill='x')
        self.buttons = []
        for label, action in [('Open LAS/LAZ…',self.choose),('Add tracks…',self.track),('Fit',self.fit),
                              ('Top',lambda:self.view(0,90)),('Front',lambda:self.view(0,0)),
                              ('Side',lambda:self.view(90,0)),('Oblique',lambda:self.view(25,45))]:
            button = ttk.Button(bar,text=label,command=action); button.pack(side='left')
            self.buttons.append(button)
        self.mode = tk.StringVar(value='Flight line')
        combo = ttk.Combobox(bar,textvariable=self.mode,values=('Flight line','Elevation','Classification'),state='readonly',width=14)
        combo.pack(side='left'); combo.bind('<<ComboboxSelected>>',lambda e:self.draw())
        ttk.Button(bar,text='Stop loading',command=self.cancel.set).pack(side='left')
        ttk.Label(self.window,text='Left drag: orbit  •  Right drag: pan  •  Wheel: zoom  •  Double click: fit  |  Orthographic 3D; Z scale 1:1').pack(anchor='w')
        body = ttk.Frame(self.window); body.pack(fill='both',expand=True)
        self.layers = ttk.Frame(body,width=180); self.layers.pack(side='right',fill='y')
        self.canvas = tk.Canvas(body,bg='#101925',highlightthickness=0)
        self.canvas.pack(side='left',fill='both',expand=True)
        self.visible = []
        self.canvas.bind('<Configure>',lambda e:self.schedule())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<ButtonPress-3>',self.press)
        self.canvas.bind('<B1-Motion>',self.orbit)
        self.canvas.bind('<B3-Motion>',self.move)
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Double-Button-1>',lambda e:self.fit())
        self.status = tk.StringVar(value='Choose LAS/LAZ files to inspect')
        ttk.Label(self.window,textvariable=self.status).pack(fill='x')
        self.poll_id = self.window.after(100,self.poll)
        if paths: self.load(paths)

    def choose(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(parent=self.window,filetypes=(('Point clouds','*.las *.laz'),))
        if paths: self.load(paths)

    def launch(self, work):
        if self.busy: return
        self.busy = True; self.cancel.clear(); self.started = time.monotonic()
        for b in self.buttons[:2]: b.configure(state='disabled')
        def run():
            try: self.messages.put(('done',work()))
            except Exception as exc: self.messages.put(('error',str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def load(self, paths):
        paths = tuple(dict.fromkeys(paths))
        self.launch(lambda: ('cloud',paths,sample_clouds(paths,cancel=self.cancel,
                    progress=lambda s:self.messages.put(('progress',s)))))

    def track(self):
        from tkinter import filedialog, messagebox, simpledialog
        if self.scene is None: return
        paths = filedialog.askopenfilenames(parent=self.window,filetypes=(('Trajectories','*.trj *.out'),))
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
                result.append((Path(path).name,segments))
            return ('tracks',result)
        self.launch(work)

    def poll(self):
        from tkinter import ttk
        try:
            while True:
                kind, value = self.messages.get_nowait()
                if kind == 'progress': self.status.set(value); continue
                self.busy = False
                for b in self.buttons[:2]: b.configure(state='normal')
                if kind == 'error': self.status.set('Stopped' if self.cancel.is_set() else 'Failed: '+value); continue
                if self.cancel.is_set(): self.status.set('Stopped'); continue
                if value[0] == 'cloud':
                    _,paths,self.scene = value
                    self.tracks = []; self.visible = []
                    for child in self.layers.winfo_children(): child.destroy()
                    ttk.Label(self.layers,text='Visible files').pack(anchor='w')
                    for path in paths:
                        var = self.tk.BooleanVar(value=True); self.visible.append(var)
                        ttk.Checkbutton(self.layers,text=Path(path).name,variable=var,command=self.draw).pack(anchor='w')
                    p = self.scene[0]; self.center = (p.min(axis=0)+p.max(axis=0))/2
                    self.span = max(float(np.linalg.norm(np.ptp(p,axis=0))),1.)
                    self.fit()
                else:
                    for name,segments in value[1]:
                        var = self.tk.BooleanVar(value=True)
                        self.tracks.append((segments,var))
                        ttk.Checkbutton(self.layers,text=name,variable=var,command=self.draw).pack(anchor='w')
                    self.draw()
                self.status.set(f'Finished in {time.monotonic()-self.started:.1f}s | Displaying {len(self.scene[0]):,} of {self.scene[4]:,} points (fixed sample; source unchanged)')
        except queue.Empty: pass
        if self.busy: self.status.set(f'Loading — elapsed {time.monotonic()-self.started:.0f}s')
        self.poll_id = self.window.after(100,self.poll)

    def press(self,e): self.last = (e.x,e.y)
    def orbit(self,e):
        x,y=self.last; self.yaw += (e.x-x)*.4; self.pitch = np.clip(self.pitch+(e.y-y)*.4,-90,90)
        self.press(e); self.schedule()
    def move(self,e):
        self.pan += np.array([e.x-self.last[0],e.y-self.last[1]])
        self.press(e); self.schedule()
    def wheel(self,e):
        self.zoom = float(np.clip(self.zoom*1.15**(e.delta/120),.05,100))
        self.schedule()
    def fit(self): self.zoom=1.; self.pan[:]=0; self.draw()
    def view(self,yaw,pitch): self.yaw=yaw; self.pitch=pitch; self.draw()
    def schedule(self):
        if self.pending is None: self.pending=self.window.after(30,self.draw)
    def draw(self):
        from PIL import Image, ImageTk
        if self.pending is not None: self.window.after_cancel(self.pending); self.pending=None
        if self.scene is None: return
        w,h = max(2,self.canvas.winfo_width()),max(2,self.canvas.winfo_height())
        scale = min(w,h)*.85/self.span*self.zoom
        pts,cls,lines,files,*_ = self.scene
        keep = np.array([v.get() for v in self.visible])[files]
        q = project_points(pts[keep],self.center,self.yaw,self.pitch)
        rgb = colors(pts,cls,lines,self.mode.get())[keep]
        xy = np.rint(q[:,:2]*[scale,-scale]+[w/2,h/2]+self.pan).astype(int)
        inside = (xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
        xy,q,rgb=xy[inside],q[inside],rgb[inside]
        order=np.argsort(q[:,2],kind='stable')
        # Unique last pixel wins: nearest point occludes farther points.
        xy,rgb=xy[order],rgb[order]
        key=xy[:,1]*w+xy[:,0]
        _,rev=np.unique(key[::-1],return_index=True)
        take=len(key)-1-rev
        pixels=np.empty((h,w,3),dtype='uint8'); pixels[:]=[16,25,37]
        pixels[xy[take,1],xy[take,0]]=rgb[take]
        self.photo=ImageTk.PhotoImage(Image.fromarray(pixels),master=self.window)
        self.canvas.delete('all'); self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        for segments,var in self.tracks:
            if not var.get(): continue
            for segment in segments:
                t=project_points(segment,self.center,self.yaw,self.pitch)
                coords=t[:,:2]*[scale,-scale]+[w/2,h/2]+self.pan
                if len(coords)>1: self.canvas.create_line(*coords.ravel().tolist(),fill='#ffffff',width=2)
        self.canvas.create_text(12,12,anchor='nw',fill='white',text=f'Yaw {self.yaw%360:.0f}°  Tilt {self.pitch:.0f}°  Zoom {self.zoom:.1f}×\nTracks shown on top; line colors repeat every 8 IDs')

    def close(self):
        self.cancel.set()
        self.window.after_cancel(self.poll_id)
        if self.pending is not None: self.window.after_cancel(self.pending)
        self.window.destroy()


def open_viewer(app):
    return Viewer(app.root,[app.cloud_path.get()] if app.cloud_path.get() else [])
