"""Read-only QA review and cross-section workspace for the desktop."""
import queue
import threading
import time
from pathlib import Path
import numpy as np


class Plot:
    """Orthographic 2D plot with world-coordinate picking, pan and zoom."""
    def __init__(self, parent, xlabel, ylabel, picked=None):
        import tkinter as tk
        self.canvas = tk.Canvas(parent, background="#101925", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.xlabel, self.ylabel, self.picked = xlabel, ylabel, picked
        self.xy = np.empty((0, 2)); self.rgb = np.empty((0, 3), dtype=np.uint8)
        self.center = np.zeros(2); self.span = np.ones(2)
        self.zoom = 1.; self.pan = np.zeros(2); self.exaggeration = 1.
        self.corridor = None
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<ButtonPress-3>", self.press)
        self.canvas.bind("<B3-Motion>", self.drag)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Double-Button-3>", lambda e: self.fit())

    def set(self, xy, rgb, exaggeration=1.):
        self.xy, self.rgb, self.exaggeration = np.asarray(xy), np.asarray(rgb), exaggeration
        if len(self.xy):
            self.center = (self.xy.min(axis=0)+self.xy.max(axis=0))/2
            self.span = np.maximum(np.ptp(self.xy, axis=0), 1e-6)
        self.fit()

    def fit(self):
        self.zoom = 1.; self.pan[:] = 0.; self.draw()

    def transform(self):
        w, h = max(200, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        ex = np.array([1., self.exaggeration])
        scale = min((w-100)/(self.span[0]*ex[0]), (h-65)/(self.span[1]*ex[1]))*.9*self.zoom
        return w, h, np.array([scale, -scale*self.exaggeration]), np.array([w/2, h/2])+self.pan

    def screen(self, xy):
        _, _, scale, origin = self.transform()
        return (np.asarray(xy)-self.center)*scale+origin

    def world(self, x, y):
        _, _, scale, origin = self.transform()
        return (np.array([x,y])-origin)/scale+self.center

    def click(self, e):
        if self.picked and len(self.xy): self.picked(self.world(e.x, e.y))

    def wheel(self, e):
        self.zoom = float(np.clip(self.zoom*1.2**(e.delta/120), .1, 200)); self.draw()

    def press(self, e): self.last = np.array([e.x,e.y])

    def drag(self, e):
        now = np.array([e.x,e.y]); self.pan += now-self.last; self.last=now; self.draw()

    def draw(self):
        from PIL import Image, ImageTk
        w,h,_,_ = self.transform()
        pixels = np.full((h,w,3), [16,25,37], dtype=np.uint8)
        if len(self.xy):
            p = np.rint(self.screen(self.xy)).astype(np.int64)
            mask = (p[:,0]>=0)&(p[:,0]<w)&(p[:,1]>=0)&(p[:,1]<h)
            p=p[mask]; pixels[p[:,1],p[:,0]] = self.rgb[mask]
        self.photo = ImageTk.PhotoImage(Image.fromarray(pixels), master=self.canvas)
        self.canvas.delete("all"); self.canvas.create_image(0,0,anchor="nw",image=self.photo)
        for i in range(5):
            x=50+(w-100)*i/4; y=25+(h-65)*i/4
            self.canvas.create_text(x,h-26,text=f"{self.world(x,h-26)[0]:.2f}",fill="#c5d0dd",font=("Segoe UI",8))
            self.canvas.create_text(4,y,text=f"{self.world(4,y)[1]:.2f}",anchor="w",fill="#c5d0dd",font=("Segoe UI",8))
        self.canvas.create_text(w/2,h-10,text=self.xlabel,fill="white")
        self.canvas.create_text(5,10,text=self.ylabel,anchor="w",fill="white")
        if self.corridor is not None:
            a,b,width = self.corridor
            delta = b-a; length = np.linalg.norm(delta)
            if length:
                side = np.array([-delta[1],delta[0]])/length*width/2
                corners = self.screen([a+side,b+side,b-side,a-side])
                self.canvas.create_polygon(*corners.ravel(),outline="#ffd15b",fill="",width=2)
                self.canvas.create_line(*self.screen([a,b]).ravel(),fill="#ffd15b",arrow="last")
                self.canvas.create_text(*self.screen(a),text="A",anchor="se",fill="white")
                self.canvas.create_text(*self.screen(b),text="B",anchor="sw",fill="white")


class ReviewWorkspace:
    def __init__(self, root, parent=None, viewer=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.external_viewer=viewer
        self.window=ttk.Frame(parent) if parent is not None else tk.Toplevel(root)
        if parent is not None: self.window.pack(fill='both',expand=True)
        else:
            self.window.title("pyArgus — QA review and sections")
            self.window.geometry("1250x860"); self.window.protocol("WM_DELETE_WINDOW",self.close)
        self.messages=queue.Queue(); self.cancel=threading.Event(); self.busy=False
        self.record=None; self.layers=[]; self.scene=None; self.section=None; self.loaded_paths=(); self.loaded_identities=[]
        self.endpoint=None; self.closed=False
        bar=ttk.Frame(self.window); bar.pack(fill="x",padx=8,pady=5)
        self.buttons=[]
        for label,command in (("Open QA/alignment job…",self.choose_record),("Add LAS/LAZ…",self.add_clouds),
                              ("Load selected clouds",self.load_clouds),("Fit views",self.fit)):
            b=ttk.Button(bar,text=label,command=command); b.pack(side="left",padx=2); self.buttons.append(b)
        ttk.Button(bar,text="Stop",command=self.cancel.set).pack(side="left")
        self.status=tk.StringVar(value="Open a QA/alignment job record, or add clouds for standalone sections.")
        ttk.Label(self.window,textvariable=self.status,wraplength=1200).pack(fill="x",padx=8)
        self.tabs=ttk.Notebook(self.window); self.tabs.pack(fill="both",expand=True,padx=8,pady=5)
        review=ttk.Frame(self.tabs); inspect=ttk.Frame(self.tabs)
        self.tabs.add(review,text="QA results"); self.tabs.add(inspect,text="Clouds and cross-sections")
        self.inspect_tab=inspect
        opts=ttk.Frame(review); opts.pack(fill="x")
        ttk.Label(opts,text="Investigate |dZ| / RMS above (map units):").pack(side="left")
        self.threshold=tk.StringVar(value="0.25")
        ttk.Entry(opts,textvariable=self.threshold,width=8).pack(side="left")
        ttk.Button(opts,text="Refresh flags",command=self.refresh).pack(side="left")
        ttk.Label(review,text="Flags guide investigation. A completed job or low solver residual is not accuracy acceptance.").pack(anchor="w")
        self.tree=ttk.Treeview(review,columns=("before","after","note"),show="tree headings")
        self.tree.heading("#0",text="Measure"); self.tree.column("#0",width=230)
        for key,width in (("before",130),("after",170),("note",450)):
            self.tree.heading(key,text=key.title()); self.tree.column(key,width=width)
        self.tree.tag_configure("flag",background="#fff0c7",foreground="#582f00")
        scroll=ttk.Scrollbar(review,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set); scroll.pack(side="right",fill="y"); self.tree.pack(fill="both",expand=True)
        files=ttk.Frame(inspect); files.pack(fill="x")
        ttk.Label(files,text="Select layers (Ctrl/Shift). After loading, selection toggles visibility. File/line identities stay separate.").pack(anchor="w")
        self.filelist=tk.Listbox(files,selectmode="extended",height=4,exportselection=False)
        self.filelist.pack(fill="x")
        self.filelist.bind("<<ListboxSelect>>", lambda e: self.redraw() if not self.busy else None)
        self.confirm=tk.BooleanVar(value=False)
        ttk.Checkbutton(files,text="I confirm selected clouds share XYZ units and vertical datum (CRS alone may not establish heights)",variable=self.confirm).pack(anchor="w")
        sourcebar=ttk.Frame(inspect); sourcebar.pack(fill="x",pady=3)
        ttk.Label(sourcebar,text="Section source:").pack(side="left")
        self.section_source=tk.StringVar()
        self.source_choice=ttk.Combobox(sourcebar,textvariable=self.section_source,state="readonly",width=85)
        self.source_choice.pack(side="left",fill="x",expand=True)
        self.source_choice.bind("<<ComboboxSelected>>",lambda e:self.clear_section())
        self.source_paths=()
        ttk.Label(inspect,text="Choose one cloud or an explicit comparison. Viewer visibility does not select section inputs.").pack(anchor="w")
        controls=ttk.Frame(inspect); controls.pack(fill="x",pady=3)
        self.coords=[tk.StringVar() for _ in range(4)]
        for label,var in zip(("A east","A north","B east","B north"),self.coords):
            ttk.Label(controls,text=label).pack(side="left"); ttk.Entry(controls,textvariable=var,width=12).pack(side="left")
        self.width=tk.StringVar(value="3.0")
        ttk.Label(controls,text="Full width").pack(side="left"); ttk.Entry(controls,textvariable=self.width,width=7).pack(side="left")
        button=ttk.Button(controls,text="Extract section",command=self.extract); button.pack(side="left"); self.buttons.append(button)
        button=ttk.Button(controls,text="Export sample CSV…",command=self.export); button.pack(side="left"); self.buttons.append(button)
        stepbar=ttk.Frame(inspect); stepbar.pack(fill="x",pady=3)
        self.step_distance=tk.StringVar(value="10.0")
        ttk.Label(stepbar,text="Step distance (map units):").pack(side="left")
        ttk.Entry(stepbar,textvariable=self.step_distance,width=8).pack(side="left")
        for label,direction in (("Step left",1),("Step right",-1)):
            button=ttk.Button(stepbar,text=label,command=lambda d=direction:self.step_section(d))
            button.pack(side="left",padx=2); self.buttons.append(button)
        ttk.Label(stepbar,text="Looking A to B; shifts sideways and extracts automatically.").pack(side="left",padx=6)
        from pyargus.section_cache_store import CacheStore
        self.cache_store=CacheStore()
        cachebar=ttk.Frame(inspect);cachebar.pack(fill='x',pady=3)
        self.use_cache=tk.BooleanVar(value=True)
        ttk.Checkbutton(cachebar,text='Use cache when available',variable=self.use_cache).pack(side='left')
        for text,command in (('Build section cache',self.build_section_cache),('Clear all section caches',self.clear_section_caches)):
            button=ttk.Button(cachebar,text=text,command=command);button.pack(side='left',padx=3);self.buttons.append(button)
        self.cache_status=tk.StringVar(value='Optional local cache; missing/stale caches use a full scan. Build uses Section source; Clear removes all local section caches.')
        ttk.Label(inspect,textvariable=self.cache_status,wraplength=1100).pack(anchor='w')
        editbar=ttk.Frame(inspect); editbar.pack(fill='x',pady=3)
        button=ttk.Button(editbar,text='Edit classifications…',command=self.edit_section); button.pack(side='left'); self.buttons.append(button)
        ttk.Label(editbar,text='Complete single-cloud sections only; source remains unchanged.').pack(side='left',padx=6)
        controls=ttk.Frame(inspect); controls.pack(fill="x")
        self.mode=tk.StringVar(value="Dataset")
        ttk.Label(controls,text="Color:").pack(side="left")
        combo=ttk.Combobox(controls,textvariable=self.mode,values=("Dataset","Flight line","Classification"),state="readonly",width=15)
        combo.pack(side="left"); combo.bind("<<ComboboxSelected>>",lambda e:self.redraw())
        self.line=tk.StringVar(value="All")
        ttk.Label(controls,text="LAS line ID (All or number):").pack(side="left")
        ttk.Entry(controls,textvariable=self.line,width=8).pack(side="left")
        self.exaggeration=tk.StringVar(value="5")
        ttk.Label(controls,text="Section vertical exaggeration:").pack(side="left")
        ttk.Entry(controls,textvariable=self.exaggeration,width=5).pack(side="left")
        ttk.Button(controls,text="Apply display",command=self.redraw).pack(side="left")
        self.legend=tk.StringVar(value="Dataset colors: original cyan; corrected orange. Manual layers alternate.")
        ttk.Label(inspect,textvariable=self.legend,wraplength=1180).pack(anchor="w")
        ttk.Label(inspect,text="Section: in the main 3D Top view Ctrl-click A then B (standalone: click plan). Units follow LAS CRS.").pack(anchor="w")
        panes=ttk.Panedwindow(inspect,orient="vertical"); panes.pack(fill="both",expand=True)
        top=ttk.Frame(panes); bottom=ttk.Frame(panes); panes.add(top,weight=1); panes.add(bottom,weight=1)
        if viewer is None:
            self.plan=Plot(top,"Easting","Northing",self.pick)
        else:
            panes.forget(top)
            self.plan=ViewerPlan(viewer)
            viewer.on_section=self.pick
        self.profile=Plot(bottom,"Station from A (map units)","Elevation (map units)")
        if viewer is not None:
            files.pack_forget()
            self.buttons[1].pack_forget(); self.buttons[2].pack_forget()
        self.poll_id=self.window.after(100,self.poll)

    def error(self, exc):
        from tkinter import messagebox
        messagebox.showerror("QA review",str(exc),parent=self.window)

    def choose_record(self):
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.window,filetypes=(("Job records","*.json"),))
        if path:
            try: self.open_record(path)
            except Exception as exc: self.error(exc)

    def open_record(self,path):
        from pyargus.review import load_review, cloud_layers
        record=load_review(path)
        self.record=record; self.layers=cloud_layers(record)
        self.clear_scene(); self.refresh_files(); self.refresh()
        self.status.set(f"{record['operation']} | {record.get('status')} | {record.get('elapsed_seconds',0):.1f} seconds | {path}")

    def refresh(self):
        if self.record is None: return
        from pyargus.review import review_rows
        try: rows=review_rows(self.record,float(self.threshold.get()))
        except Exception as exc: self.error(exc); return
        self.tree.delete(*self.tree.get_children())
        def text(value):
            if value is None: return "—"
            return f"{value:.4f}" if isinstance(value,float) else str(value)
        for row in rows:
            self.tree.insert("","end",text=row["label"],values=(text(row["before"]),text(row["after"]),row["note"]),tags=("flag",) if row["flag"] else ())

    def clear_scene(self):
        self.scene=None; self.section=None; self.loaded_paths=(); self.endpoint=None
        self.plan.corridor=None; self.plan.set(np.empty((0,2)),np.empty((0,3)))
        self.profile.set(np.empty((0,2)),np.empty((0,3)))
        self.confirm.set(False)

    def clear_section(self):
        self.section=None
        self.profile.set(np.empty((0,2)),np.empty((0,3)))

    def refresh_section_sources(self):
        paths=tuple(self.loaded_paths)
        if paths == self.source_paths: return
        self.source_paths=paths
        self.source_choice.configure(values=[*paths, "Compare all loaded clouds"] if paths else [])
        self.section_source.set(paths[0] if len(paths)==1 else "")
        self.clear_section()

    def section_paths(self):
        self.refresh_section_sources()
        selected=self.section_source.get()
        if selected == "Compare all loaded clouds" and self.loaded_paths:
            return list(self.loaded_paths)
        if selected in self.loaded_paths:
            return [selected]
        raise ValueError("Choose a Section source: one cloud or Compare all loaded clouds.")

    def refresh_files(self):
        self.refresh_section_sources()
        self.filelist.delete(0,"end")
        for layer in self.layers:
            self.filelist.insert("end",f"{layer['role']} | {layer['state']} | {layer['path']}")
        for i,layer in enumerate(self.layers):
            if layer['state']=='available': self.filelist.selection_set(i)

    def add_clouds(self):
        from tkinter import filedialog
        paths=filedialog.askopenfilenames(parent=self.window,filetypes=(("Point clouds","*.las *.laz"),))
        for path in paths:
            if path not in [layer['path'] for layer in self.layers]:
                self.layers.append(dict(path=path,role="Manual",state="available"))
        if paths: self.clear_scene(); self.refresh_files(); self.tabs.select(self.inspect_tab)

    def launch(self, work):
        # Finalize abandoned Tk objects on their owning UI thread.
        import gc
        gc.collect()
        if self.busy: return
        self.busy=True; self.cancel.clear(); self.started=time.monotonic(); self.progress="Working"
        self.source_choice.configure(state="disabled")
        for button in self.buttons: button.configure(state="disabled")
        def run():
            try: self.messages.put(("done",work()))
            except Exception as exc: self.messages.put(("error",str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def load_clouds(self):
        from pyargus.viewer3d import sample_clouds
        try:
            selected=[self.layers[i] for i in self.filelist.curselection()]
            if not selected: raise ValueError("Select at least one available cloud.")
            if any(v['state']!='available' for v in selected):
                raise ValueError("A selected file is missing or changed since the job; review the source before loading it.")
            if not self.confirm.get(): raise ValueError("Confirm common XYZ units and vertical datum before comparing clouds.")
            paths=tuple(v['path'] for v in selected)
            from pyargus.job_manifest import identity
            if self.record is not None:
                from pyargus.review import cloud_layers
                current={v['path']:v['state'] for v in cloud_layers(self.record)}
                if any(current.get(p,'available')!='available' for p in paths):
                    raise ValueError("A source has changed since the job. Reload and review the file references.")
            def work():
                signatures=[identity(p) for p in paths]
                scene=sample_clouds(paths,limit=100000,cancel=self.cancel,
                    progress=lambda s:self.messages.put(("progress",s)))
                if signatures != [identity(p) for p in paths]:
                    raise ValueError("A cloud changed while loading the plan view.")
                return ("cloud",paths,selected,scene,signatures)
            self.launch(work)
            self.tabs.select(self.inspect_tab)
        except Exception as exc: self.error(exc)

    def pick(self,xy):
        if self.busy: return
        self.tabs.select(self.inspect_tab)
        if self.endpoint is None:
            self.endpoint=xy
            self.coords[0].set(f"{xy[0]:.6f}"); self.coords[1].set(f"{xy[1]:.6f}")
            self.status.set("A set. Click B, then Extract section.")
        else:
            self.coords[2].set(f"{xy[0]:.6f}"); self.coords[3].set(f"{xy[1]:.6f}")
            self.endpoint=None
            try: self.set_corridor()
            except Exception as exc: self.error(exc)

    def set_corridor(self):
        from pyargus.sections import section_coordinates
        values=[float(v.get()) for v in self.coords]; width=float(self.width.get())
        a,b=np.array(values[:2]),np.array(values[2:])
        section_coordinates([],[],a,b,width)
        if self.section is not None and (self.section.start != a.tolist() or self.section.end != b.tolist() or self.section.width != width):
            self.section=None; self.profile.set(np.empty((0,2)),np.empty((0,3)))
        self.plan.corridor=(a,b,width); self.plan.draw()
        return a,b,width

    def step_section(self, direction):
        """Translate the corridor left/right of A->B, then use normal extraction."""
        if self.busy: return
        try:
            from pyargus.section_navigation import stepped_corridor
            if not self.loaded_paths:
                raise ValueError("Load clouds and choose a Section source before stepping.")
            self.section_paths()  # Refuse an ambiguous source before changing the corridor.
            values=[float(v.get()) for v in self.coords]
            a,b=stepped_corridor(values[:2],values[2:],float(self.width.get()),
                                float(self.step_distance.get()),direction)
            for var,value in zip(self.coords,[*a,*b]): var.set(repr(float(value)))
            self.endpoint=None
            self.extract()
        except Exception as exc: self.error(exc)

    def build_section_cache(self):
        try:
            if self.busy:return
            if not self.loaded_paths:raise ValueError('Load clouds and choose a Section source before building its cache.')
            paths=self.section_paths()
            signatures=[self.loaded_identities[list(self.loaded_paths).index(p)] for p in paths]
            def work():
                from pyargus.job_manifest import identity
                if [identity(p) for p in paths]!=signatures:raise ValueError('Cloud changed since loading; reload before building its cache.')
                text=self.cache_store.build(paths,cancel=self.cancel,progress=lambda s:self.messages.put(('progress',s)))
                return ('cache',text)
            self.launch(work)
        except Exception as exc:self.error(exc)

    def clear_section_caches(self):
        if self.busy:return
        self.launch(lambda:('cache',self.cache_store.clear(cancel=self.cancel,progress=lambda s:self.messages.put(('progress',s)))))

    def extract(self):
        if self.busy: return
        from pyargus.sections import extract_section
        try:
            if not self.loaded_paths: raise ValueError("Load selected clouds before extracting a section.")
            a,b,width=self.set_corridor(); paths=self.section_paths(); use_cache=self.use_cache.get()
            signatures=[self.loaded_identities[list(self.loaded_paths).index(p)] for p in paths]
            self.section=None; self.profile.set(np.empty((0,2)),np.empty((0,3)))
            def work():
                from pyargus.job_manifest import identity
                if [identity(p) for p in paths] != signatures:
                    raise ValueError("A cloud changed since loading the plan; reload before extracting.")
                progress=lambda s:self.messages.put(('progress',s))
                if use_cache:
                    section,method=self.cache_store.extract(paths,a,b,width,limit=max(1,100000//len(paths)),cancel=self.cancel,progress=progress)
                else:
                    section=extract_section(paths,a,b,width,limit=max(1,100000//len(paths)),cancel=self.cancel,progress=progress)
                    method='Full scan — cache disabled'
                if [identity(p) for p in paths]!=signatures:raise ValueError('Cloud changed during section extraction; reload before extracting.')
                return ("section",section,method)
            self.launch(work)
        except Exception as exc: self.error(exc)

    def color(self,xyz,classes,lines,files):
        from pyargus.viewer3d import colors
        mode=self.mode.get()
        if mode=="Dataset":
            palette=np.array([[58,190,255],[255,171,65]],dtype=np.uint8)
            ids=np.array([0 if layer['role']=="Original" else 1 if layer['role']=="Corrected" else i%2 for i,layer in enumerate(self.loaded_layers)])
            self.legend.set("Original cyan; corrected orange. Manual files alternate. Loaded: "+"; ".join(Path(p).name for p in self.loaded_paths))
            return palette[ids[files]]
        if mode=="Flight line":
            # Distinct file/line keys, including reused line IDs from different flights.
            keys=np.column_stack([files,lines]); unique=np.unique(keys,axis=0)
            inverse=files.astype(np.int64)*65537+lines.astype(np.int64)
            self.legend.set("Flight line colors repeat after 8 groups. Groups: "+"; ".join(f"file {int(f)+1}/line {int(l)}" for f,l in unique[:30]))
            return colors(xyz,classes,inverse,mode)
        self.legend.set("ASPRS classification colors; use LAS line ID filter to isolate a strip.")
        return colors(xyz,classes,lines,mode)

    def redraw(self):
        self.refresh_section_sources()
        if self.scene is None: return
        try:
            requested=self.line.get().strip()
            line_id=None if requested.lower()=="all" else int(requested)
            ex=float(self.exaggeration.get())
            if not np.isfinite(ex) or ex<=0 or ex>1000: raise ValueError("Vertical exaggeration must be in (0, 1000].")
            selected={self.layers[i]["path"] for i in self.filelist.curselection()}
            visible=np.array([p in selected for p in self.loaded_paths])
            pts,cls,lines,files,*_=self.scene
            mask=np.ones(len(pts),dtype=bool) if line_id is None else lines==line_id
            mask &= visible[files]
            self.plan.set(pts[mask,:2],self.color(pts,cls,lines,files)[mask])
            if self.section is not None:
                sec=self.section; mask=np.ones(len(sec.points),dtype=bool) if line_id is None else sec.lines==line_id
                # Section file IDs belong to the selected subset, not the plan's file order.
                mapping=np.array([list(self.loaded_paths).index(item['path']) for item in sec.inputs])
                global_files=mapping[sec.files]
                mask &= visible[global_files]
                rgb=self.color(sec.points[:,:3],sec.classes,sec.lines,global_files)
                self.profile.set(sec.points[mask][:,[3,2]],rgb[mask],ex)
                self.profile.ylabel=f"Elevation; vertical exaggeration {ex:g}×"
                self.profile.draw()
        except Exception as exc: self.error(exc)

    def fit(self): self.plan.fit(); self.profile.fit()

    def export(self):
        from tkinter import filedialog
        from pyargus.sections import export_section
        if self.section is None: self.error("Extract a section first."); return
        path=filedialog.asksaveasfilename(parent=self.window,filetypes=(("Section sample CSV","*.csv"),),defaultextension=".csv")
        if path:
            try:
                export_section(self.section,path)
                self.status.set(f"Exported section sample and definition: {path} (all sampled lines, regardless of display filter)")
            except Exception as exc: self.error(exc)

    def edit_section(self):
        if self.busy: return
        try:
            if self.section is None: raise ValueError('Extract a complete single-cloud section first.')
            if getattr(self,'editor',None) is not None and self.editor.window.winfo_exists():
                self.editor.window.lift(); return
            from pyargus.editing_gui import SectionEditor
            self.editor=SectionEditor(self.window,self.section)
        except Exception as exc: self.error(exc)

    def poll(self):
        try:
            while True:
                kind,value=self.messages.get_nowait()
                if kind=="progress": self.progress=value; continue
                self.busy=False
                self.source_choice.configure(state="readonly")
                for button in self.buttons: button.configure(state="normal")
                if kind=="error": self.status.set("Stopped" if self.cancel.is_set() else "Failed: "+value); continue
                if self.cancel.is_set(): self.status.set("Stopped"); continue
                if value[0]=="cache":
                    self.cache_status.set(value[1]);self.status.set(value[1]);continue
                if value[0]=="cloud":
                    _,self.loaded_paths,self.loaded_layers,self.scene,self.loaded_identities=value
                    if self.external_viewer is not None:
                        self.external_viewer.load(self.loaded_paths)
                    self.section=None; self.plan.corridor=None; self.endpoint=None
                    self.profile.set(np.empty((0,2)),np.empty((0,3)))
                    self.redraw()
                    self.status.set(f"Loaded {len(self.scene[0]):,} preview points of {self.scene[4]:,}. Pick A and B on plan. Units: {self.scene[5].axis_info[0].unit_name}.")
                else:
                    self.section=value[1]; self.redraw()
                    if len(value)>2:self.cache_status.set(value[2])
                    counts=", ".join(f"{Path(self.section.inputs[i]['path']).name}: {n:,}" for i,n in enumerate(self.section.matched_by_file))
                    self.status.set(f"Section finished in {time.monotonic()-self.started:.1f}s: {self.section.matched:,} corridor returns; {len(self.section.points):,} sampled for display/export ({counts}); counts precede display filters.")
        except queue.Empty: pass
        if self.busy: self.status.set(f"{self.progress} — elapsed {time.monotonic()-self.started:.0f}s")
        if not self.closed: self.poll_id=self.window.after(100,self.poll)

    def close(self):
        editor=getattr(self,'editor',None)
        if editor is not None and editor.window.winfo_exists():
            if not editor.close(): return False
        self.closed=True; self.cancel.set(); self.window.after_cancel(self.poll_id); self.window.destroy()


def open_review(app):
    if hasattr(app,"workspace"):
        app.workspace.tabs.select(app.workspace.review_tab)
        return app.workspace.review
    return ReviewWorkspace(app.root)


class ViewerPlan:
    """Section plan operations delegated to the single embedded 3D camera."""
    def __init__(self,viewer): self.viewer=viewer
    @property
    def corridor(self): return self.viewer.corridor
    @corridor.setter
    def corridor(self,value): self.viewer.corridor=value
    def set(self,*args): self.viewer.draw()
    def draw(self): self.viewer.draw()
    def fit(self): self.viewer.fit()
