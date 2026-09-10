"""Project window. All lidar reads and analysis use the main job runner."""
from dataclasses import replace
from pathlib import Path
import copy
import datetime
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pyargus import project


class ProjectWindow:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title('pyArgus — Multi-file project')
        self.window.geometry('1040x720')
        self.window.minsize(800,600)
        self.clouds, self.tracks, self.bindings = [], [], {}
        self.inventory = None
        self.actions = []
        body = ttk.Frame(self.window,padding=10); body.pack(fill='both',expand=True)
        ttk.Label(body,text='Import multiple LAS/LAZ clouds and TRJ/SBET trajectories for project QA and alignment.').pack(anchor='w')
        self.tabs = ttk.Notebook(body); self.tabs.pack(fill='both',expand=True,pady=6)
        inputs = ttk.Frame(self.tabs,padding=8); self.tabs.add(inputs,text='Files')
        settings = ttk.Frame(self.tabs,padding=8); self.tabs.add(settings,text='Settings')
        results = ttk.Frame(self.tabs,padding=8); self.tabs.add(results,text='Matching results')
        lists = ttk.Panedwindow(inputs,orient='horizontal'); lists.pack(fill='both',expand=True)
        self.cloud_box = self._files_panel(lists,'Point clouds',False)
        self.track_box = self._files_panel(lists,'Trajectories',True)
        editor = ttk.LabelFrame(inputs,text='Settings for selected trajectories',padding=5)
        editor.pack(fill='x',pady=5)
        self.track_time = tk.StringVar(value='Choose time base')
        self.track_week = tk.StringVar()
        self.track_confirm = tk.BooleanVar(value=False)
        ttk.Label(editor,text='Time base').grid(row=0,column=0)
        ttk.Combobox(editor,textvariable=self.track_time,values=('same','week'),state='readonly',width=8).grid(row=0,column=1)
        ttk.Label(editor,text='GPS week (optional)').grid(row=0,column=2,padx=(10,0))
        ttk.Entry(editor,textvariable=self.track_week,width=8).grid(row=0,column=3)
        ttk.Button(editor,text='Apply to selected',command=self.apply_track_settings).grid(row=0,column=4,padx=10)
        ttk.Checkbutton(editor,text='TRJ: verified LAS XYZ frame/units/datum and attitude conventions',variable=self.track_confirm).grid(row=1,column=0,columnspan=5,sticky='w')
        ttk.Label(editor,text='same = stored LAS clock; week = GPS seconds of week. SBET always uses week.').grid(row=2,column=0,columnspan=5,sticky='w')
        ttk.Button(editor,text='Apply time base to ALL trajectories',command=self.apply_all_time).grid(row=3,column=0,columnspan=5,sticky='w',pady=4)
        binding = ttk.Frame(inputs); binding.pack(fill='x')
        ttk.Button(binding,text='Bind selected clouds to selected trajectory',command=self.bind_selected).pack(side='left')
        ttk.Button(binding,text='Restore automatic matching',command=self.unbind_selected).pack(side='left',padx=4)
        ttk.Label(inputs,text='Automatic matching uses timestamp coverage and TRJ line numbers. Use a binding for overlapping SBET files.').pack(anchor='w',pady=3)
        file_actions = ttk.Frame(inputs); file_actions.pack(fill='x')
        ttk.Button(file_actions,text='Load project…',command=self.load_project).pack(side='left')
        ttk.Button(file_actions,text='Save project…',command=self.save_project).pack(side='left',padx=4)
        from pyargus.viewer3d import Viewer
        ttk.Button(file_actions,text="3D viewer…",command=lambda: Viewer(app.root,list(self.clouds))).pack(side="left",padx=4)
        self.counts = tk.StringVar(); ttk.Label(file_actions,textvariable=self.counts).pack(side='right')
        self.crs = tk.StringVar()
        self.vertical = tk.StringVar(value='EPSG:6360')
        self.week = tk.StringVar()
        self.gap = tk.StringVar(value='1.0')
        self.limit = tk.StringVar(value='25000000')
        self.same_vertical = tk.BooleanVar(value=False)
        self.shared_ids = tk.BooleanVar(value=False)
        self.network = tk.BooleanVar(value=False)
        self.boresight = tk.BooleanVar(value=False)
        self.cell = tk.StringVar(value='6.0')
        self.min_points = tk.StringVar(value='6')
        for row,(label,var) in enumerate((('CRS declaration for untagged LAS (optional)',self.crs),
                ('SBET vertical CRS or geoid N in meters',self.vertical),
                ('Project GPS week (required for LAS week time)',self.week),
                ('Maximum interpolated trajectory gap (seconds)',self.gap),
                ('In-memory point limit (larger QA uses disk; alignment stays limited)',self.limit),
                ('Alignment cell size (map units)',self.cell),('Minimum points per alignment cell',self.min_points))):
            ttk.Label(settings,text=label).grid(row=row,column=0,sticky='w',pady=4)
            ttk.Entry(settings,textvariable=var,width=24).grid(row=row,column=1,sticky='w',padx=8)
        ttk.Checkbutton(settings,text='All clouds share their vertical datum and XYZ linear units',variable=self.same_vertical).grid(row=7,column=0,columnspan=2,sticky='w',pady=6)
        ttk.Checkbutton(settings,text='Allow PROJ to download SBET geoid grids',variable=self.network).grid(row=8,column=0,columnspan=2,sticky='w')
        ttk.Checkbutton(settings,text='Solve boresight as well as per-line vertical offsets',variable=self.boresight).grid(row=9,column=0,columnspan=2,sticky='w')
        ttk.Label(settings,wraplength=850,text='TRJ alignment requires clockwise heading from grid north, right-wing-down roll and nose-up pitch. Confirm these against the export convention before checking the TRJ box. Use one sensor/calibration per alignment project.').grid(row=10,column=0,columnspan=2,sticky='w',pady=12)
        ttk.Label(settings,wraplength=850,text='CRS mismatches are refused; this importer does not reproject LAS files. Original flight-line IDs remain unchanged in exports. QA above the point limit uses disk-backed exact statistics. Allow roughly 160 bytes of scratch space per source point on the output drive, plus system temporary space. Alignment still uses arrays and the point limit.').grid(row=11,column=0,columnspan=2,sticky='w')
        ttk.Checkbutton(settings,text='Without trajectories: repeated line IDs across tiles identify the same flights',variable=self.shared_ids).grid(row=12,column=0,columnspan=2,sticky='w',pady=6)
        self.result_tree = ttk.Treeview(results,columns=('points','matched','unmatched','ambiguous'),show='tree headings')
        self.result_tree.heading('#0',text='Cloud / analysis strip → source line → trajectory')
        self.result_tree.column('#0',width=560)
        for col in ('points','matched','unmatched','ambiguous'):
            self.result_tree.heading(col,text=col.title()); self.result_tree.column(col,width=90,anchor='e')
        scroll = ttk.Scrollbar(results,orient='vertical',command=self.result_tree.yview)
        scroll.pack(side='right',fill='y'); self.result_tree.configure(yscrollcommand=scroll.set)
        self.result_tree.pack(fill='both',expand=True)
        ttk.Button(results,text='Save inventory…',command=self.save_inventory).pack(anchor='w',pady=4)
        output = ttk.Frame(body); output.pack(fill='x')
        self.out = tk.StringVar()
        ttk.Label(output,text='New output folder').pack(side='left')
        ttk.Entry(output,textvariable=self.out).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(output,text='Choose parent…',command=self.choose_output).pack(side='left')
        actions = ttk.Frame(body); actions.pack(fill='x',pady=5)
        for label,mode in (('Inspect / match','inspect'),('Project QA','qa'),('Align project','align')):
            button = ttk.Button(actions,text=label,command=lambda m=mode:self.start(m))
            button.pack(side='left',padx=3); self.actions.append(button)
        ttk.Button(actions,text='Stop',command=app.runner.cancel).pack(side='left',padx=3)
        ttk.Label(body,textvariable=app.job_status).pack(anchor='w')
        ttk.Label(body,text='Progress and output paths appear in the main window job log. Classification and surface tabs remain single-cloud tools.').pack(anchor='w')
        self.refresh()

    def _files_panel(self,parent,title,is_track):
        frame = ttk.LabelFrame(parent,text=title,padding=5); parent.add(frame,weight=1)
        box = tk.Listbox(frame,selectmode='extended',exportselection=False,height=7)
        box.pack(fill='both',expand=True)
        box.bind('<Control-a>',lambda e:(box.select_set(0,'end'),'break')[-1])
        tools = ttk.Frame(frame); tools.pack(fill='x')
        for label,action in (('Add files…',lambda:self.add_files(is_track)),
                             ('Add folder…',lambda:self.add_folder(is_track)),
                             ('Remove',lambda:self.remove(is_track))):
            ttk.Button(tools,text=label,command=action).pack(side='left')
        return box

    def refresh(self):
        cloud_selection = self.cloud_box.curselection()
        track_selection = self.track_box.curselection()
        self.cloud_box.delete(0,'end'); self.track_box.delete(0,'end')
        for p in self.clouds:
            bound = self.bindings.get(p)
            self.cloud_box.insert('end',p + (f' → {Path(bound).name}' if bound else ''))
        for t in self.tracks:
            self.track_box.insert('end',f'{t.path} [{t.time_mode or "set time"}; week {t.gps_week if t.gps_week is not None else "auto"}]')
        for i in cloud_selection: self.cloud_box.select_set(i)
        for i in track_selection: self.track_box.select_set(i)
        unset = sum(t.time_mode not in ('same','week') for t in self.tracks)
        self.counts.set(f'{len(self.clouds)} clouds; {len(self.tracks)} trajectories' + (f' — {unset} NEED TIME BASE' if unset else ''))

    def add_paths(self,paths,is_track):
        existing = {t.path for t in self.tracks} if is_track else set(self.clouds)
        for raw in paths:
            p = str(Path(raw).resolve())
            if p in existing: continue
            existing.add(p)
            if is_track:
                self.tracks.append(project.TrajectoryInput(p,time_mode='' if Path(p).suffix.lower()=='.trj' else 'week'))
            else: self.clouds.append(p)
        self.refresh()

    def add_files(self,is_track):
        types = (('TerraScan TRJ','*.trj'),('SBET','*.out')) if is_track else (('LAS','*.las'),('LAZ','*.laz'))
        paths = filedialog.askopenfilenames(parent=self.window,filetypes=types)
        if paths: self.add_paths(paths,is_track)

    def add_folder(self,is_track):
        folder = filedialog.askdirectory(parent=self.window)
        if not folder: return
        suffixes = ('.trj','.out') if is_track else ('.las','.laz')
        self.add_paths(sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in suffixes),is_track)

    def remove(self,is_track):
        box,values = (self.track_box,self.tracks) if is_track else (self.cloud_box,self.clouds)
        for index in reversed(box.curselection()): del values[index]
        self.bindings = {c:t for c,t in self.bindings.items() if c in self.clouds and t in {v.path for v in self.tracks}}
        self.refresh()

    def apply_track_settings(self):
        try:
            if self.track_time.get() not in ('same','week'):
                raise ValueError('Choose same or week before applying trajectory settings.')
            week = int(self.track_week.get()) if self.track_week.get().strip() else None
            project._week(week)
            selected = self.track_box.curselection()
            if not selected: raise ValueError('select one or more trajectories first')
            for i in selected:
                t = self.tracks[i]
                mode = self.track_time.get() if Path(t.path).suffix.lower()=='.trj' else 'week'
                self.tracks[i] = replace(t,time_mode=mode,gps_week=week,confirmed=self.track_confirm.get())
            self.refresh()
        except ValueError as exc: messagebox.showerror('Project',str(exc),parent=self.window)

    def apply_all_time(self):
        mode = self.track_time.get()
        if mode not in ('same','week'):
            messagebox.showerror('Project','Choose same or week first.',parent=self.window)
            return
        # Only the time base changes; do not spread attitude approval or GPS weeks.
        self.tracks = [replace(t,time_mode=mode if Path(t.path).suffix.lower()=='.trj' else 'week') for t in self.tracks]
        self.refresh()

    def check_time_settings(self):
        missing = [i for i,t in enumerate(self.tracks) if t.time_mode not in ('same','week')]
        if not missing: return
        self.tabs.select(0)
        self.track_box.selection_clear(0,'end')
        for i in missing: self.track_box.selection_set(i)
        self.track_box.see(missing[0])
        raise ValueError(f'{len(missing)} trajectories need a time base. They are now selected. '
                         'Choose same or week, then click Apply to selected, or Apply time base to ALL trajectories. '
                         'Each file must show [same; ...] or [week; ...] instead of [set time; ...].')

    def bind_selected(self):
        clouds,tracks = self.cloud_box.curselection(),self.track_box.curselection()
        if not clouds or len(tracks)!=1:
            messagebox.showerror('Project','Select one trajectory and one or more clouds.',parent=self.window); return
        for i in clouds: self.bindings[self.clouds[i]]=self.tracks[tracks[0]].path
        self.refresh()

    def unbind_selected(self):
        for i in self.cloud_box.curselection(): self.bindings.pop(self.clouds[i],None)
        self.refresh()

    def snapshot(self):
        vertical = self.vertical.get().strip() or None
        if vertical is not None:
            try: vertical=float(vertical)
            except ValueError: pass
        return project.Project(list(self.clouds),copy.deepcopy(self.tracks),self.crs.get().strip() or None,
            self.same_vertical.get(),int(self.week.get()) if self.week.get().strip() else None,
            vertical,self.network.get(),dict(self.bindings),float(self.gap.get()),int(self.limit.get()),self.shared_ids.get())

    def save_project(self):
        try:
            spec = self.snapshot()
            path = filedialog.asksaveasfilename(parent=self.window,filetypes=(('pyArgus project','*.json'),),defaultextension='.json')
            if path: spec.save(path)
        except (ValueError,OSError) as exc: messagebox.showerror('Project',str(exc),parent=self.window)

    def load_project(self):
        path = filedialog.askopenfilename(parent=self.window,filetypes=(('pyArgus project','*.json'),))
        if not path: return
        try:
            p = project.Project.load(path)
            self.clouds,self.tracks,self.bindings = p.clouds,p.trajectories,p.bindings
            for var,value in ((self.crs,p.map_crs),(self.vertical,p.vertical),(self.week,p.gps_week),
                              (self.gap,p.max_gap),(self.limit,p.max_points)):
                var.set('' if value is None else str(value))
            self.same_vertical.set(p.same_vertical); self.network.set(p.allow_network)
            self.shared_ids.set(p.shared_strip_ids)
            self.refresh()
        except (ValueError,OSError,KeyError,TypeError) as exc: messagebox.showerror('Project',str(exc),parent=self.window)

    def choose_output(self):
        parent = filedialog.askdirectory(parent=self.window)
        if parent:
            stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            self.out.set(str(Path(parent)/f'pyargus_project_{stamp}'))

    def save_inventory(self):
        if self.inventory is None: return
        path = filedialog.asksaveasfilename(parent=self.window,filetypes=(('Project inventory','*.json'),),defaultextension='.json')
        if path:
            try:
                with Path(path).open('x',encoding='utf-8') as f: json.dump(self.inventory,f,indent=2)
            except OSError as exc: messagebox.showerror('Project',str(exc),parent=self.window)

    def start(self,mode):
        if self.app.runner.running: return
        try:
            self.check_time_settings()
            spec = self.snapshot()
            out = self.out.get().strip()
            if mode!='inspect' and not out: raise ValueError('choose a new output folder')
            cell,min_points = float(self.cell.get()),int(self.min_points.get())
            if cell<=0 or min_points<1: raise ValueError('alignment cell and minimum points must be positive')
            boresight = self.boresight.get()
        except ValueError as exc:
            messagebox.showerror('Project',str(exc),parent=self.window); return
        completed = {}
        def work(runner):
            try:
                kw = dict(log=runner.log,cancel=runner.cancelled)
                if mode=='inspect': completed['inventory']=project.load(spec,**kw).inventory
                elif mode=='qa':
                    project.qa(spec,out,**kw)
                    completed['inventory']=json.loads((Path(out)/'inventory.json').read_text(encoding='utf-8'))
                else: completed['inventory']=project.align(spec,out,cell=cell,min_points=min_points,solve_boresight=boresight,**kw)['inventory']
                if mode!='inspect':
                    try:
                        from PIL import Image
                        import numpy as np
                        path=Path(out)/('after/density.png' if mode=='align' else 'density.png')
                        with Image.open(path) as preview:
                            runner.report=np.array(preview.convert('RGBA'))
                    except (ImportError,OSError) as exc:
                        runner.log(f'Outputs are complete; preview unavailable: {exc}')
            except project.Cancelled: return
        runner = self.app.runner
        runner.stage_name = f'Project {mode}'
        self.app.run_button.configure(state='disabled'); self.app.stop_button.configure(state='normal')
        for b in self.actions: b.configure(state='disabled')
        runner.start(work); self.app._stage_open=True; self.app._update_job_status()
        def finish():
            if not self.window.winfo_exists(): return
            if runner.running:
                self.app.root.after(150,finish); return
            for b in self.actions: b.configure(state='normal')
            if runner.error is None and not runner.cancelled() and 'inventory' in completed:
                self.inventory=completed['inventory']; self.show_inventory()
        self.app.root.after(150,finish)

    def show_inventory(self):
        self.result_tree.delete(*self.result_tree.get_children())
        for c in self.inventory['clouds']:
            parent = self.result_tree.insert('','end',text=c['path'],values=[f'{c[k]:,}' for k in ('points','matched','unmatched','ambiguous')],open=True)
            for s in self.inventory['strips']:
                if c['path'] in s['clouds']:
                    track = Path(s['trajectory_path']).name if s['trajectory_path'] else ('ambiguous' if s['trajectory']==-2 else 'unmatched / no trajectory')
                    self.result_tree.insert(parent,'end',text=f"{s['id']} → LAS line {s['source_id']} → {track}")
        unused=[t for t in self.inventory['trajectories'] if not t['matched_points']]
        if unused:
            parent=self.result_tree.insert('','end',text='Unused trajectories',open=True)
            for t in unused: self.result_tree.insert(parent,'end',text=t['path'])
        self.tabs.select(2)


def open_project(app):
    previous = getattr(app,'project_window',None)
    if previous is not None and previous.window.winfo_exists():
        previous.window.lift(); return previous
    app.project_window = ProjectWindow(app)
    return app.project_window
