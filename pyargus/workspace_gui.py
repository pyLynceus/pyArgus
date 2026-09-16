"""Unified project workspace, 3D inspection, and persistent workflow history."""
from dataclasses import asdict
import json
import os
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import numpy as np

from pyargus.workspace_state import Tracker, STAGES

NAMES={'Strip QA':'Initial QA','Classify':'Classification','Above ground':'Classification',
       'Align':'Alignment','DTM':'Surface','DTM / DSM':'Surface','Contours':'Contours','Colorize':'Colorization'}


class Workspace:
    def __init__(self, app, parent):
        from pyargus.viewer3d import Viewer
        from pyargus.project_gui import ProjectWindow
        from pyargus.review_gui import ReviewWorkspace
        self.app=app; self.root=app.root; self.tracker=Tracker(); self.active=None
        self.path=Path(os.environ.get('PYARGUS_WORKSPACE_AUTOSAVE',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'pyArgus-Codex'/'last-workspace.json')))
        self.resume_path=self.path.with_suffix('.last.json')
        self.refresh_key=None; self.last_scene=None; self.last_record=None; self.pending_view=None; self.closed=False; self.last_save=time.monotonic()
        bar=ttk.Frame(parent); bar.pack(fill='x')
        for label,cmd in [('Open workspace',self.open),('Save workspace as',self.save_as),('Resume last',self.resume),
                          ('Load project clouds',self.load_project_clouds),('Overlay project tracks',self.project_tracks)]:
            ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=2)
        self.here=tk.StringVar(value='You are here: add project files, then Inspect / match.')
        ttk.Label(parent,textvariable=self.here,wraplength=1050,font=('Segoe UI',10,'bold')).pack(fill='x',pady=3)
        panes=ttk.Panedwindow(parent,orient='vertical'); panes.pack(fill='both',expand=True)
        top=ttk.Frame(panes,height=380); bottom=ttk.Frame(panes,height=470)
        panes.add(top,weight=1); panes.add(bottom,weight=1)
        self.viewer=Viewer(self.root,parent=top)
        self.viewer.on_point=lambda value:self.here.set('Picked sample: '+str(value))
        filters=ttk.Frame(top); filters.pack(fill='x',before=self.viewer.window)
        self.class_filter=tk.StringVar(value='All'); self.line_filter=tk.StringVar(value='All')
        for name,var in [('Class',self.class_filter),('LAS line',self.line_filter)]:
            ttk.Label(filters,text=name).pack(side='left'); ttk.Entry(filters,textvariable=var,width=7).pack(side='left')
        ttk.Button(filters,text='Apply filters',command=self.filter).pack(side='left')
        ttk.Label(filters,text='Shift-click: point details | Top + Ctrl-click A/B: section | Refine view: more local detail').pack(side='left')
        self.tabs=ttk.Notebook(bottom); self.tabs.pack(fill='both',expand=True)
        self.progress_tab=ttk.Frame(self.tabs); self.project_tab=ttk.Frame(self.tabs)
        self.review_tab=ttk.Frame(self.tabs); self.layers_tab=ttk.Frame(self.tabs)
        for frame,title in [(self.progress_tab,'Progress / history'),(self.project_tab,'Project inputs / matching'),
                            (self.review_tab,'QA / cross-sections'),(self.layers_tab,'Layers / deliverables')]: self.tabs.add(frame,text=title)
        # Project settings remain fully accessible even when the dock is short.
        canvas=tk.Canvas(self.project_tab,highlightthickness=0)
        scroll=ttk.Scrollbar(self.project_tab,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        content=ttk.Frame(canvas); item=canvas.create_window(0,0,window=content,anchor='nw')
        content.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        self.project_panel=ProjectWindow(app,parent=content)
        self.review=ReviewWorkspace(self.root,parent=self.review_tab,viewer=self.viewer)
        self._build_progress(); self._build_layers()
        self.poll_id=self.root.after(500,self.poll)

    def _build_progress(self):
        bar=ttk.Frame(self.progress_tab);bar.pack(fill='x')
        self.qa_phase=tk.StringVar(value='Initial QA')
        ttk.Label(bar,text='Next QA run:').pack(side='left')
        ttk.Combobox(bar,textvariable=self.qa_phase,values=('Initial QA','Final QA'),state='readonly',width=12).pack(side='left')
        for label,cmd in [('Accept',lambda:self.decide('Accepted')),('Needs review',lambda:self.decide('Needs review')),
                          ('Skip stage',lambda:self.decide('Skipped')),('Load selected result',self.load_result),
                          ('Import job record',self.import_record)]: ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=2)
        self.stage_tree=ttk.Treeview(self.progress_tab,columns=('status','next'),show='tree headings',height=6)
        self.stage_tree.heading('#0',text='Stage');self.stage_tree.column('#0',width=145)
        self.stage_tree.heading('status',text='Status');self.stage_tree.column('status',width=125)
        self.stage_tree.heading('next',text='Next action / prerequisites');self.stage_tree.column('next',width=520)
        self.stage_tree.pack(fill='x');self.stage_tree.bind('<<TreeviewSelect>>',lambda e:self.history())
        self.history_tree=ttk.Treeview(self.progress_tab,columns=('when','status','elapsed'),show='tree headings',height=3)
        self.history_tree.heading('#0',text='Attempt / stage');self.history_tree.column('#0',width=240)
        for c in ('when','status','elapsed'):self.history_tree.heading(c,text=c.title())
        self.history_tree.pack(fill='x');self.history_tree.bind('<<TreeviewSelect>>',lambda e:self.details())
        self.detail=tk.Text(self.progress_tab,height=6,wrap='word');self.detail.pack(fill='both',expand=True)
        self.refresh()

    def _build_layers(self):
        bar=ttk.Frame(self.layers_tab);bar.pack(fill='x')
        for label,cmd in [('Import output',self.import_output),('Add control',self.add_control),('Add breaklines',self.add_breaklines),
                          ('Show selected',self.show_layers),('Use cloud for processing',self.use_cloud),
                          ('Select deliverables',self.delivery)]:ttk.Button(bar,text=label,command=cmd).pack(side='left')
        self.layer_tree=ttk.Treeview(self.layers_tab,columns=('kind','origin'),show='tree headings',selectmode='extended')
        self.layer_tree.heading('#0',text='File');self.layer_tree.column('#0',width=600)
        self.layer_tree.heading('kind',text='Kind');self.layer_tree.heading('origin',text='Origin');self.layer_tree.pack(fill='both',expand=True)

    def stage_settings(self,stage):
        return {k:v.get() for k,v in vars(stage).items() if isinstance(v,tk.Variable)}

    def current_settings(self,job):
        if job.get('source')=='stage':
            stage=next((s for s in self.app.stages if type(s).__name__==job.get('stage_class')),None)
            if stage:
                return dict(stage=self.stage_settings(stage),cloud=self.app.cloud_path.get(),trajectory=self.app.sbet_path.get(),trj_time=self.app.trj_time.get())
        if job.get('source')=='project':
            try:return self.project_settings(job['mode'])
            except ValueError:return {}
        return None

    def project_settings(self,mode):
        p=self.project_panel
        return dict(project=asdict(p.snapshot()),mode=mode,cell=p.cell.get(),min_points=p.min_points.get(),boresight=p.boresight.get())

    def begin_stage(self,stage):
        if self.active is not None and not self.app.runner.running:self.complete(self.app.runner)
        title=NAMES.get(stage.title,stage.title)
        if title=='Initial QA':title=self.qa_phase.get()
        settings=dict(stage=self.stage_settings(stage),cloud=self.app.cloud_path.get(),trajectory=self.app.sbet_path.get(),trj_time=self.app.trj_time.get())
        values=settings['stage'];inputs=[settings['cloud'],settings['trajectory']]
        inputs += [v for k,v in values.items() if k in ('cloud_override','control','breaklines','model_path','eo_path','cal_path') and v]
        self.active=self.tracker.begin(title,settings,inputs);self.active.update(source='stage',stage_class=type(stage).__name__)
        self.expected=[v for k,v in values.items() if k in ('out_path','out_dir','write_path') and v]
        self.persist();self.refresh()

    def begin_project(self,mode,spec,out):
        if self.active is not None and not self.app.runner.running:self.complete(self.app.runner)
        title={'inspect':'Inspect','qa':self.qa_phase.get(),'align':'Alignment'}[mode]
        self.active=self.tracker.begin(title,self.project_settings(mode),list(spec.clouds)+[t.path for t in spec.trajectories])
        self.active.update(source='project',mode=mode);self.expected=[out] if mode!='inspect' else []
        self.persist();self.refresh()

    def observe_log(self,line):
        if self.active is not None and line.startswith('job record: '):
            path=line.split('job record: ',1)[1].strip()
            if path not in self.active['records']:self.active['records'].append(path)

    def complete(self,runner):
        if self.active is None:return
        paths=[str(p) for _,p in runner.products]+[p for p in self.expected if Path(p).exists()]
        for record in self.active['records']:
            try:
                data=json.loads(Path(record).read_text(encoding='utf-8'))
                paths += [o['path'] for o in data.get('outputs',[]) if Path(o['path']).exists()]
                self.active['job_summaries']=self.active.get('job_summaries',[])+[data.get('results',{})]
            except (OSError,ValueError,KeyError):pass
        status='Failed' if runner.error else 'Cancelled' if runner.cancelled() else 'Needs review'
        self.tracker.finish(self.active,status,paths,str(runner.error) if runner.error else None,runner.elapsed)
        for p in dict.fromkeys(paths):self.add_layer(p,'output',self.active['id'])
        self.active=None;self.persist();self.refresh();self.refresh_layers();self.history()

    def refresh(self):
        from pyargus.workspace_state import DEPENDENCIES
        current=[]
        for stage in STAGES:
            job=self.tracker.latest(stage)
            current.append((stage,job['id'] if job else None,self.tracker.status(stage,self.current_settings(job) if job else None)))
        key=repr(current)
        if key==self.refresh_key:return
        self.refresh_key=key
        selected=self.stage_tree.selection();self.stage_tree.delete(*self.stage_tree.get_children())
        first=None
        for stage in STAGES:
            job=self.tracker.latest(stage);status=self.tracker.status(stage,self.current_settings(job) if job else None)
            deps=[s for s in DEPENDENCIES.get(stage,[]) if self.tracker.status(s) not in ('Accepted','Skipped')]
            action='Review results / add note' if status=='Needs review' else 'Rerun with current inputs/settings' if status=='Outdated' else 'Run or explicitly skip'
            if deps:action+='; review upstream: '+', '.join(deps)
            self.stage_tree.insert('','end',iid=stage,text=stage,values=(status,action))
            if first is None and status not in ('Accepted','Skipped'):first=(stage,status)
        for item in selected:
            if self.stage_tree.exists(item):self.stage_tree.selection_set(item)
        if self.active:self.here.set(f"You are here: {self.active['stage']} is running. Results will require review.")
        elif first:
            last=next((j for j in reversed(self.tracker.data['jobs']) if j['status'] in ('Needs review','Accepted')),None)
            self.here.set(f'You are here: {first[0]} — {first[1]}. Last completed: '+(last['stage'] if last else 'none')+'. Select a stage for history and next actions.')
        else:self.here.set('All listed stages accepted or explicitly skipped. Review selected deliverables before delivery.')

    def selected_job(self):
        chosen=self.history_tree.selection()
        if chosen:return next((j for j in self.tracker.data['jobs'] if j['id']==chosen[0]),None)
        stage=self.stage_tree.selection()
        return self.tracker.latest(stage[0]) if stage else None

    def history(self):
        selection=self.stage_tree.selection()
        self.history_tree.delete(*self.history_tree.get_children())
        if not selection:return
        for j in reversed(self.tracker.data['jobs']):
            if j['stage']==selection[0]:self.history_tree.insert('','end',iid=j['id'],text=j['stage'],values=(j['started'],j['status'],f"{j.get('elapsed',0):.1f}s"))
        children=self.history_tree.get_children()
        if children:self.history_tree.selection_set(children[0]);self.details()

    def details(self):
        job=self.selected_job();self.detail.delete('1.0','end')
        if job:self.detail.insert('end',json.dumps(job,indent=2))

    def decide(self,decision):
        selected=self.stage_tree.selection()
        if not selected:return
        note=simpledialog.askstring('Review note','Why are you accepting, revisiting or skipping this stage?',parent=self.root)
        if note is None:return
        try:
            job=self.tracker.latest(selected[0])
            self.tracker.decide(selected[0],decision,note,self.current_settings(job) if job else None)
            self.persist();self.refresh();self.history()
        except ValueError as exc:messagebox.showerror('Progress',str(exc),parent=self.root)

    def add_layer(self,path,kind,origin='Unverified import',**extra):
        path=str(Path(path).resolve())
        if not any(l['path']==path for l in self.tracker.data['layers']):self.tracker.data['layers'].append(dict(path=path,kind=kind,origin=origin,visible=True,**extra))

    def refresh_layers(self):
        self.layer_tree.delete(*self.layer_tree.get_children())
        for i,layer in enumerate(self.tracker.data['layers']):self.layer_tree.insert('','end',iid=str(i),text=layer['path'],values=(layer['kind'],layer['origin']))

    def selected_layers(self):return [self.tracker.data['layers'][int(i)] for i in self.layer_tree.selection()]

    def import_output(self):
        path=filedialog.askopenfilename(parent=self.root,title='Import an existing output (unverified)')
        if path:
            job=self.tracker.import_output(path);self.add_layer(path,'output',job['id']);self.persist();self.refresh();self.refresh_layers()

    def import_record(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=(('Job record','*.json'),))
        if not path:return
        try:
            self.review.open_record(path);data=self.review.record
            stage={'qa':'Initial QA','project-qa':'Initial QA','align':'Alignment','project-align':'Alignment'}[data['operation']]
            j=self.tracker.begin(stage,data.get('settings',{}),[])
            j.update(source='imported',status={'completed':'Needs review','failed':'Failed','cancelled':'Cancelled'}.get(data['status'],'Unverified import'),records=[path],
                     inputs=[[i['path'],i['size_bytes'],i['mtime_ns']] for i in data.get('inputs',[])],
                     outputs=[[i['path'],i['size_bytes'],i['mtime_ns']] for i in data.get('outputs',[])])
            for layer in self.review.layers:self.add_layer(layer['path'],layer['role'],j['id'])
            self.persist();self.refresh();self.refresh_layers();self.tabs.select(self.review_tab)
        except Exception as exc:messagebox.showerror('Import job',str(exc),parent=self.root)

    def load_result(self):
        j=self.selected_job()
        if not j:return
        paths=[p[0] for p in j.get('outputs',[]) if Path(p[0]).suffix.lower() in ('.las','.laz') and Path(p[0]).exists()]
        if paths:self.viewer.load(paths)
        if j.get('records'):
            try:self.review.open_record(j['records'][-1]);self.tabs.select(self.review_tab)
            except Exception as exc:messagebox.showerror('Review',str(exc),parent=self.root)

    def load_project_clouds(self):
        p=self.project_panel
        if p.clouds:
            for path in p.clouds:self.add_layer(path,'cloud','Project input')
            for t in p.tracks:self.add_layer(t.path,'trajectory','Project input')
            self.viewer.load(p.clouds);self.persist();self.refresh_layers()
        else:messagebox.showinfo('Project','Add LAS/LAZ files in Project inputs / matching first.',parent=self.root)

    def show_layers(self):
        selected=self.selected_layers();paths=[l['path'] for l in selected if Path(l['path']).suffix.lower() in ('.las','.laz')]
        if paths:self.viewer.load(paths)
        for layer in selected:
            if layer['kind'] in ('control','breaklines'):self.overlay(layer)
            elif Path(layer['path']).suffix.lower() in ('.dxf','.geojson'):self.overlay(dict(layer,kind='breaklines'))
            elif Path(layer['path']).suffix.lower()=='.asc':self.overlay(dict(layer,kind='surface'))

    def use_cloud(self):
        layers=self.selected_layers()
        if len(layers)==1 and Path(layers[0]['path']).suffix.lower() in ('.las','.laz'):
            self.app.cloud_path.set(layers[0]['path'])
            for s in self.app.stages:
                if hasattr(s,'cloud_override'):s.cloud_override.set(layers[0]['path'])
            self.persist();self.refresh()

    def add_control(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=(('Control CSV','*.csv'),))
        if not path:return
        order=simpledialog.askstring('Control order','Enter pnez or penz. Coordinates must use the cloud frame.',parent=self.root)
        if order not in ('pnez','penz'):return
        self.add_layer(path,'control',order=order);self.app.stages[0].control.set(path);self.app.stages[0].order.set(order)
        self.persist();self.refresh_layers()

    def add_breaklines(self):
        path=filedialog.askopenfilename(parent=self.root,filetypes=(('Breaklines','*.dxf *.geojson *.json'),))
        if not path:return
        self.add_layer(path,'breaklines')
        for s in self.app.stages:
            if hasattr(s,'breaklines'):s.breaklines.set(path)
        self.persist();self.refresh_layers()

    def overlay(self,layer):
        if self.viewer.scene is None:return
        if not messagebox.askyesno('Overlay coordinates','Confirm this layer uses the cloud XYZ frame, units and vertical datum.',parent=self.root):return
        try:
            if layer['kind']=='control':
                from pyargus.formats.control import read_control_csv
                _,x,y,z=read_control_csv(layer['path'],layer['order']);segments=[np.array([[a,b,c]]) for a,b,c in zip(x,y,z)]
            elif layer['kind']=='surface':
                from pyargus.workspace_assets import surface_points
                points=surface_points(layer['path'])
                var=tk.BooleanVar(value=True);self.viewer.extra_points.append((points,var))
                ttk.Checkbutton(self.viewer.layers,text=Path(layer['path']).name,variable=var,command=self.viewer.draw).pack(anchor='w')
                self.viewer.draw();return
            else:
                from pyargus.formats.breaklines import read_breaklines
                segments=read_breaklines(layer['path'])
            var=tk.BooleanVar(value=True);self.viewer.extra_layers.append((layer['path'],segments,var))
            ttk.Checkbutton(self.viewer.layers,text=Path(layer['path']).name,variable=var,command=self.viewer.draw).pack(anchor='w')
            self.viewer.draw()
        except Exception as exc:messagebox.showerror('Overlay',str(exc),parent=self.root)

    def project_tracks(self):
        self.viewer.track([t.path for t in self.project_panel.tracks])

    def delivery(self):
        layers=self.selected_layers()
        if not layers:return
        j=self.tracker.begin('Delivery',dict(selected=[l['path'] for l in layers]),[l['path'] for l in layers])
        self.tracker.finish(j,'Needs review',[l['path'] for l in layers]);self.persist();self.refresh()

    def filter(self):
        try:
            self.viewer.class_filter=None if self.class_filter.get().lower()=='all' else int(self.class_filter.get())
            self.viewer.line_filter=None if self.line_filter.get().lower()=='all' else int(self.line_filter.get())
            self.viewer.draw()
        except ValueError:messagebox.showerror('Filter','Enter All or a numeric class/line ID.',parent=self.root)

    def capture(self):
        p=self.project_panel
        try:self.tracker.data['project']=asdict(p.snapshot())
        except ValueError:pass
        self.tracker.data['settings']={type(s).__name__:self.stage_settings(s) for s in self.app.stages}
        self.tracker.data['active_cloud']=self.app.cloud_path.get();self.tracker.data['trajectory']=self.app.sbet_path.get()
        self.tracker.data['trj_time']=self.app.trj_time.get();self.tracker.data['qa_phase']=self.qa_phase.get()
        self.tracker.data['overlay_layers']=[name for name,_,var in self.viewer.extra_layers if var.get()]
        self.tracker.data['project_options']=dict(cell=p.cell.get(),min_points=p.min_points.get(),boresight=p.boresight.get(),out=p.out.get())
        if self.viewer.scene is not None:
            v=self.viewer
            self.tracker.data['view']=dict(paths=list(v.paths),visible=[b.get() for b in v.visible],yaw=v.yaw,pitch=v.pitch,zoom=v.zoom,
                pan=v.pan.tolist(),center=v.center.tolist(),span=v.span,mode=v.mode.get(),class_filter=self.class_filter.get(),line_filter=self.line_filter.get())
        if self.review.plan.corridor is not None:
            a,b,width=self.review.plan.corridor;definition=dict(start=a.tolist(),end=b.tolist(),width=width)
            if not self.tracker.data['sections'] or self.tracker.data['sections'][-1]!=definition:self.tracker.data['sections'].append(definition)

    def persist(self):
        self.capture()
        try:
            self.tracker.save(self.path)
            self.resume_path.parent.mkdir(parents=True,exist_ok=True)
            self.resume_path.write_text(json.dumps({'workspace':str(self.path.resolve())}),encoding='utf-8')
        except OSError as exc:self.app.runner.log(f'Workspace could not be saved: {exc}')

    def save_as(self):
        path=filedialog.asksaveasfilename(parent=self.root,filetypes=(('Workspace','*.argus.json'),),defaultextension='.argus.json')
        if path:self.path=Path(path);self.persist()

    def open(self):
        if self.app.runner.running or self.viewer.busy or self.review.busy:return
        path=filedialog.askopenfilename(parent=self.root,filetypes=(('Workspace','*.json'),))
        if path:self.restore(path)

    def resume(self):
        if self.app.runner.running or self.viewer.busy or self.review.busy:return
        target=self.path
        if self.resume_path.exists():
            try:target=Path(json.loads(self.resume_path.read_text(encoding='utf-8'))['workspace'])
            except (OSError,ValueError,KeyError):pass
        if target.exists():self.restore(target)

    def restore(self,path):
        from pyargus.project import TrajectoryInput
        try:
            tracker=Tracker.load(path);self.tracker=tracker;self.refresh_key=None;self.path=Path(path);data=tracker.data;p=self.project_panel
            proj=data['project'];p.clouds=proj.get('clouds',[]);p.tracks=[TrajectoryInput(**t) for t in proj.get('trajectories',[])];p.bindings=proj.get('bindings',{})
            for key,var in [('map_crs',p.crs),('vertical',p.vertical),('gps_week',p.week),('max_gap',p.gap),('max_points',p.limit)]:
                value=proj.get(key);var.set('' if value is None else str(value))
            for key,var in [('same_vertical',p.same_vertical),('allow_network',p.network),('shared_strip_ids',p.shared_ids)]:var.set(proj.get(key,False))
            for key,value in data.get('project_options',{}).items():getattr(p,key).set(value)
            p.refresh()
            for stage in self.app.stages:
                for key,value in data['settings'].get(type(stage).__name__,{}).items():
                    var=getattr(stage,key,None)
                    if isinstance(var,tk.Variable):var.set(value)
            self.app.cloud_path.set(data.get('active_cloud',''));self.app.sbet_path.set(data.get('trajectory',''));self.app.trj_time.set(data.get('trj_time','Select TRJ time'))
            self.qa_phase.set(data.get('qa_phase','Initial QA'));self.refresh_layers();self.refresh()
            self.pending_view=data.get('view') or None
            if self.pending_view and all(Path(p).exists() for p in self.pending_view['paths']):self.viewer.load(self.pending_view['paths'])
            if data['sections']:
                cut=data['sections'][-1]
                for var,value in zip(self.review.coords,cut['start']+cut['end']):var.set(str(value))
                self.review.width.set(str(cut['width']));self.review.set_corridor()
        except Exception as exc:messagebox.showerror('Workspace',str(exc),parent=self.root)

    def poll(self):
        if self.closed:return
        v=self.viewer
        if v.scene is not None and (v.scene is not self.last_scene or self.review.record is not self.last_record):
            self.last_scene=v.scene;self.last_record=self.review.record
            from pyargus.job_manifest import identity
            self.review.scene=v.scene;self.review.loaded_paths=v.paths
            self.review.loaded_identities=[identity(p) for p in v.paths]
            known={layer['path']:layer for layer in self.tracker.data['layers']}
            self.review.loaded_layers=[dict(path=p,role='Corrected' if known.get(p,{}).get('kind') in ('output','Corrected') else 'Original',state='available') for p in v.paths]
            self.review.layers=self.review.loaded_layers;self.review.refresh_files();self.review.section=None
            if self.pending_view:
                saved=self.pending_view;self.pending_view=None
                for key in ('yaw','pitch','zoom','span'):setattr(v,key,saved[key])
                v.pan=np.array(saved['pan']);v.center=np.array(saved['center']);v.mode.set(saved['mode'])
                for var,value in zip(v.visible,saved['visible']):var.set(value)
                self.class_filter.set(saved.get('class_filter','All'));self.line_filter.set(saved.get('line_filter','All'));self.filter()
            self.review.redraw();v.draw()
            for p in v.paths:
                self.add_layer(p,'cloud')
                if p not in self.project_panel.clouds and not any(layer['path']==p and layer['kind']=='output' for layer in self.tracker.data['layers']):self.project_panel.clouds.append(p)
            self.project_panel.refresh()
            self.refresh_layers()
        self.refresh()
        if time.monotonic()-self.last_save>15:
            self.persist();self.last_save=time.monotonic()
        self.poll_id=self.root.after(1500,self.poll)

    def close(self):
        self.persist();self.closed=True;self.root.after_cancel(self.poll_id)
        self.review.close();self.viewer.close()
