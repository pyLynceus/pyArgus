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
        # each stage's fields as constructed: a workspace saved before a field
        # existed restores that field to this, not to what the last workspace left
        self.stage_defaults={type(s).__name__:self.stage_settings(s) for s in app.stages}
        self.path=Path(os.environ.get('PYARGUS_WORKSPACE_AUTOSAVE',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'pyArgus-Codex'/'last-workspace.json')))
        self.resume_path=self.path.with_suffix('.last.json')
        self.refresh_key=None; self.last_scene=None; self.last_record=None; self.pending_view=None; self.closed=False; self.last_save=time.monotonic()
        shell=ttk.Panedwindow(parent,orient='horizontal');shell.pack(fill='both',expand=True)
        self.sidebar=ttk.Frame(shell,width=250,padding=(0,0,8)); shell.add(self.sidebar,weight=0)
        center=ttk.Frame(shell);shell.add(center,weight=1)
        parent=center
        bar=ttk.Frame(parent); bar.pack(fill='x')
        for label,cmd in [('Open workspace',self.open),('Save workspace as',self.save_as),('Resume last',self.resume)]:
            ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=2)
        self.here=tk.StringVar(value='You are here: add project files, then Inspect / match.')
        ttk.Label(parent,textvariable=self.here,wraplength=1050,font=('Segoe UI',10,'bold')).pack(fill='x',pady=3)
        panes=ttk.Panedwindow(parent,orient='vertical'); panes.pack(fill='both',expand=True)
        top=ttk.Frame(panes,height=570); bottom=ttk.Frame(panes,height=280)
        panes.add(top,weight=3); panes.add(bottom,weight=1)
        self.viewer=Viewer(self.root,parent=top)
        self.viewer.on_import_tracks=self.register_tracks
        self.viewer.layers.pack_forget()
        for button in self.viewer.buttons[:2]+self.viewer.buttons[3:8]:button.pack_forget()
        preset=tk.StringVar(value='Oblique')
        views={'Top':(0,90),'Front':(0,0),'Side':(90,0),'Oblique':(25,45)}
        choice=ttk.Combobox(self.viewer.buttons[2].master,textvariable=preset,values=tuple(views),state='readonly',width=10)
        choice.pack(side='left',before=self.viewer.buttons[2])
        choice.bind('<<ComboboxSelected>>',lambda e:self.viewer.view(*views[preset.get()]))
        self.viewer.buttons[-1].configure(text='Reset detail')
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
        for frame,title in [(self.progress_tab,'Progress / history'),(self.project_tab,'Project settings'),
                            (self.review_tab,'QA / cross-sections')]: self.tabs.add(frame,text=title)
        self.log_tab=ttk.Frame(self.tabs);self.tabs.add(self.log_tab,text='Log')
        app.log.pack(in_=self.log_tab,fill='both',expand=True)
        # Project settings remain fully accessible even when the dock is short.
        canvas=tk.Canvas(self.project_tab,highlightthickness=0)
        scroll=ttk.Scrollbar(self.project_tab,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        content=ttk.Frame(canvas); item=canvas.create_window(0,0,window=content,anchor='nw')
        content.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        self.project_panel=ProjectWindow(app,parent=content)
        self.single_trajectory=ttk.Frame(app.task_panel)
        ttk.Label(self.single_trajectory,text='Optional trajectory for this cloud').pack(anchor='w')
        self.trajectory_choice=ttk.Combobox(self.single_trajectory,textvariable=app.sbet_path,state='readonly',values=('',))
        self.trajectory_choice.pack(fill='x')
        self.trajectory_choice.bind('<<ComboboxSelected>>',lambda e:self.sync_single_trajectory())
        ttk.Button(self.single_trajectory,text='Trajectory clock / frame settings',command=lambda:self.tabs.select(self.project_tab)).pack(anchor='w',pady=4)
        self.project_task=ttk.Frame(app.task_panel)
        ttk.Label(self.project_task,text='Project settings apply to all input clouds.',wraplength=340).pack(anchor='w',pady=6)
        ttk.Button(self.project_task,text='Review project settings / matching',command=lambda:self.tabs.select(self.project_tab)).pack(fill='x')
        ttk.Label(self.project_task,text='New output folder (QA / alignment)').pack(anchor='w',pady=(10,0))
        ttk.Entry(self.project_task,textvariable=self.project_panel.out).pack(fill='x')
        ttk.Button(self.project_task,text='Choose output parent…',command=self.project_panel.choose_output).pack(anchor='w',pady=4)
        self.task_hint=tk.StringVar()
        ttk.Label(self.project_task,textvariable=self.task_hint,wraplength=340).pack(fill='x',pady=8)
        self.review=ReviewWorkspace(self.root,parent=self.review_tab,viewer=self.viewer)
        self._build_progress(); self._build_layers()
        self.overlay_vars={}
        self.poll_id=self.root.after(500,self.poll)

    def _build_progress(self):
        bar=ttk.Frame(self.progress_tab);bar.pack(fill='x')
        self.qa_phase=tk.StringVar(value='Initial QA')
        ttk.Label(bar,text='Next QA run:').pack(side='left')
        ttk.Combobox(bar,textvariable=self.qa_phase,values=('Initial QA','Final QA'),state='readonly',width=12).pack(side='left')
        for label,cmd in [('Accept',lambda:self.decide('Accepted')),('Needs review',lambda:self.decide('Needs review')),
                          ('Skip stage',lambda:self.decide('Skipped')),('Load selected result',self.load_result),
                          ('Import job record',self.import_record)]: ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=2)
        stage_frame=ttk.Frame(self.progress_tab);stage_frame.pack(fill='x')
        self.stage_tree=ttk.Treeview(stage_frame,columns=('status','next'),show='tree headings',height=6)
        self.stage_tree.heading('#0',text='Stage');self.stage_tree.column('#0',width=145)
        self.stage_tree.heading('status',text='Status');self.stage_tree.column('status',width=125)
        self.stage_tree.heading('next',text='Next action / prerequisites');self.stage_tree.column('next',width=520)
        stage_scroll=ttk.Scrollbar(stage_frame,orient='vertical',command=self.stage_tree.yview);stage_scroll.pack(side='right',fill='y')
        self.stage_tree.configure(yscrollcommand=stage_scroll.set)
        self.stage_tree.pack(fill='x');self.stage_tree.bind('<<TreeviewSelect>>',lambda e:self.history())
        self.history_tree=ttk.Treeview(self.progress_tab,columns=('when','status','elapsed'),show='tree headings',height=3)
        self.history_tree.heading('#0',text='Attempt / stage');self.history_tree.column('#0',width=240)
        for c in ('when','status','elapsed'):self.history_tree.heading(c,text=c.title())
        self.history_tree.pack(fill='x');self.history_tree.bind('<<TreeviewSelect>>',lambda e:self.details())
        self.detail=tk.Text(self.progress_tab,height=6,wrap='word');self.detail.pack(fill='both',expand=True)
        self.refresh()

    def _build_layers(self):
        panel=self.sidebar
        ttk.Label(panel,text='Project files',font=('Segoe UI',12,'bold')).pack(anchor='w')
        tools=ttk.Frame(panel);tools.pack(fill='x',pady=5)
        ttk.Button(tools,text='Add files…',command=self.add_files).pack(side='left')
        ttk.Button(tools,text='Settings',command=lambda:self.tabs.select(self.project_tab)).pack(side='left')
        self.file_summary=tk.StringVar()
        ttk.Label(panel,textvariable=self.file_summary,wraplength=260).pack(fill='x')
        self.layer_tree=ttk.Treeview(panel,columns=('kind',),show='tree headings',selectmode='extended',height=16)
        self.layer_tree.heading('#0',text='File / visibility');self.layer_tree.column('#0',width=185,minwidth=120)
        self.layer_tree.heading('kind',text='State');self.layer_tree.column('kind',width=105,minwidth=80)
        self.layer_tree.pack(fill='both',expand=True)
        self.layer_tree.bind('<<TreeviewSelect>>',self.select_layer)
        self.layer_tree.bind('<Double-1>',lambda e:self.toggle_layer())
        self.layer_tree.bind('<Button-3>',self.layer_menu)
        ttk.Label(panel,text='Select a cloud to set task input.\nDouble-click to show / hide.\nRight-click for layer actions.',wraplength=270).pack(fill='x',pady=6)
        self.layer_note=tk.StringVar()
        ttk.Label(panel,textvariable=self.layer_note,wraplength=270).pack(fill='x')
        self.sync_project_layers()

    def add_files(self,paths=None):
        if self.app.runner.running or self.viewer.busy:return
        if paths is None:
            paths=filedialog.askopenfilenames(parent=self.root,title='Add project files',filetypes=(
                ('Project files','*.las *.laz *.trj *.out *.csv *.dxf *.geojson *.asc'),('All files','*.*')))
        clouds=[];tracks=[]
        for raw in paths:
            path=str(Path(raw).resolve());suffix=Path(path).suffix.lower()
            if suffix in ('.las','.laz'):clouds.append(path)
            elif suffix in ('.trj','.out'):tracks.append(path)
            elif suffix=='.csv':
                order=simpledialog.askstring('Control columns','Column order: pnez or penz',initialvalue='pnez',parent=self.root)
                if order not in ('pnez','penz'):continue
                self.add_layer(path,'control','Project input',order=order)
                self.app.stages[0].control.set(path);self.app.stages[0].order.set(order)
            elif suffix in ('.dxf','.geojson'):
                self.add_layer(path,'breaklines','Project input');self.app.stages[3].breaklines.set(path)
            elif suffix=='.asc':self.add_layer(path,'surface','Unverified import')
            else:messagebox.showinfo('Unsupported file',f'Cannot import {Path(path).name}',parent=self.root)
        active={self.tracker.cloud_root(p):p for p in self.project_panel.clouds}
        clouds=list(dict.fromkeys(active.get(self.tracker.cloud_root(p),p) for p in clouds))
        self.project_panel.add_paths(clouds,False)
        self.register_tracks(tracks)
        if clouds:
            if not self.app.cloud_path.get():self.set_active_cloud(clouds[0])
            self.load_project_clouds()
        self.refresh_layers();self.persist()

    def add_folder(self):
        folder=filedialog.askdirectory(parent=self.root,title='Add clouds and trajectories from a folder')
        if folder:self.add_files(sorted(str(p) for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in ('.las','.laz','.trj','.out')))

    def load_analysis_project(self):
        if self.app.runner.running or self.viewer.busy:return
        self.project_panel.load_project()
        active=set(self.project_panel.clouds)|{t.path for t in self.project_panel.tracks}
        self.layer_tree.selection_remove(*self.layer_tree.selection())
        self.tracker.data['layers']=[l for l in self.tracker.data['layers'] if l['kind'] not in ('cloud','trajectory') or l['path'] in active]
        self.sync_project_layers()
        self.set_active_cloud(self.project_panel.clouds[0] if self.project_panel.clouds else '')
        if self.project_panel.clouds:self.load_project_clouds()

    def register_tracks(self,paths):
        self.project_panel.add_paths(paths,True)
        self.sync_project_layers()

    def sync_project_layers(self):
        for path in self.project_panel.clouds:self.add_layer(path,'cloud','Project input')
        for track in self.project_panel.tracks:self.add_layer(track.path,'trajectory','Project input')
        if hasattr(self,'trajectory_choice'):
            self.trajectory_choice.configure(values=('',*[t.path for t in self.project_panel.tracks]))
            self.sync_single_trajectory()
        if hasattr(self,'layer_tree'):self.refresh_layers()
        if hasattr(self.app,'scope_summary'):self.update_scope()

    def sync_single_trajectory(self):
        path=self.app.sbet_path.get()
        track=next((t for t in self.project_panel.tracks if t.path==path),None)
        self.app.trj_time.set(track.time_mode if track and track.time_mode else 'Select TRJ time')

    def set_active_cloud(self,path):
        self.app.cloud_path.set(path)
        for stage in self.app.stages:
            if hasattr(stage,'cloud_override'):stage.cloud_override.set(path)
        self.update_scope()

    def select_layer(self,event=None):
        layers=self.selected_layers();p=self.project_panel
        p.cloud_box.selection_clear(0,'end');p.track_box.selection_clear(0,'end')
        selected={l['path'] for l in layers}
        for i,path in enumerate(p.clouds):
            if path in selected:p.cloud_box.selection_set(i)
        for i,track in enumerate(p.tracks):
            if track.path in selected:p.track_box.selection_set(i)
        if len(layers)==1:
            layer=layers[0];self.layer_note.set(layer['path'])
            if Path(layer['path']).suffix.lower() in ('.las','.laz'):self.set_active_cloud(layer['path'])
            if layer['kind']=='trajectory':
                track=next((t for t in p.tracks if t.path==layer['path']),None)
                if track:
                    p.track_time.set(track.time_mode or 'Choose time base');p.track_week.set('' if track.gps_week is None else str(track.gps_week));p.track_confirm.set(track.confirmed)

    def layer_menu(self,event):
        row=self.layer_tree.identify_row(event.y)
        if row and row not in self.layer_tree.selection():self.layer_tree.selection_set(row)
        menu=tk.Menu(self.root,tearoff=False)
        for label,cmd in [('Show / hide',self.toggle_layer),('Fit visible clouds',self.viewer.fit_selected),
                ('Use this version for processing',self.activate_selected_version),
                ('Trajectory settings',lambda:self.tabs.select(self.project_tab)),
                ('Add folder…',self.add_folder),('Load analysis project…',self.load_analysis_project),('Save analysis project…',self.project_panel.save_project),('Import existing output…',self.import_output),('Select as deliverables',self.delivery),('Remove from project',self.remove_layers)]:
            menu.add_command(label=label,command=cmd)
        menu.tk_popup(event.x_root,event.y_root)

    def activate_selected_version(self):
        if self.app.runner.running or self.viewer.busy or self.review.busy:return
        selected=self.selected_layers()
        if len(selected)!=1 or Path(selected[0]['path']).suffix.lower() not in ('.las','.laz'):
            messagebox.showinfo('Processing version','Select one cloud version.',parent=self.root);return
        try:self.activate_cloud_version(selected[0]['path'])
        except (OSError,ValueError) as exc:messagebox.showerror('Processing version',str(exc),parent=self.root)

    def activate_cloud_version(self,path):
        path=str(Path(path).resolve())
        if not Path(path).is_file():raise ValueError('Cloud version is missing: '+path)
        panel=self.project_panel;root=self.tracker.cloud_root(path)
        previous=[p for p in panel.clouds if self.tracker.cloud_root(p)==root]
        bindings={panel.bindings[p] for p in previous if p in panel.bindings}
        if len(bindings)>1:raise ValueError('Conflicting trajectory bindings for this flight')
        updated=[]
        for old in panel.clouds:
            candidate=path if old in previous else old
            if candidate not in updated:updated.append(candidate)
        if path not in updated:updated.append(path)
        panel.clouds=updated
        for old in previous:panel.bindings.pop(old,None)
        if bindings:panel.bindings[path]=next(iter(bindings))
        self.add_layer(path,'cloud','Selected processing version')
        self.set_active_cloud(path)
        panel.refresh()
        if self.viewer.busy:
            self.pending_version_view=True
        else:
            self.viewer.load(list(panel.clouds))
        self.persist();self.refresh();self.refresh_layers()

    def toggle_layer(self):
        if self.viewer.busy:return
        selected=self.selected_layers()
        to_load=[];tracks=[]
        for layer in selected:
            path=layer['path'];var=self.visible_var(path)
            if var is not None:var.set(not var.get());layer['visible']=var.get()
            elif layer['kind']=='trajectory':tracks.append(path)
            elif Path(path).suffix.lower() in ('.las','.laz'):to_load.append(path)
            else:self.overlay(layer)
        if to_load:
            self.viewer.load(list(dict.fromkeys([*self.viewer.paths,*to_load])))
            if tracks:self.viewer.status.set('Loading clouds first. Show the selected trajectories after loading finishes.')
        elif tracks:self.viewer.track(tracks)
        self.viewer.draw();self.refresh_layers()

    def visible_var(self,path):
        v=self.viewer
        if path in v.paths:return v.visible[v.paths.index(path)]
        if path in v.track_paths:return v.tracks[v.track_paths.index(path)][1]
        return getattr(self,'overlay_vars',{}).get(path)

    def remove_layers(self):
        if self.app.runner.running or self.viewer.busy:return
        paths={l['path'] for l in self.selected_layers()};p=self.project_panel
        if not paths:return
        p.clouds=[c for c in p.clouds if c not in paths];p.tracks=[t for t in p.tracks if t.path not in paths]
        p.bindings={c:t for c,t in p.bindings.items() if c not in paths and t not in paths}
        for path in paths:
            var=self.visible_var(path)
            if var is not None:var.set(False)
        # Unload removed clouds so a later scene refresh cannot re-import them.
        remaining=[c for c in self.viewer.paths if c not in paths]
        if len(remaining)!=len(self.viewer.paths):
            if remaining:self.viewer.load(remaining)
            else:
                self.viewer.scene=None;self.viewer.paths=();self.viewer.visible=[];self.viewer.track_paths=[];self.viewer.tracks=[];self.viewer.extra_layers=[];self.viewer.extra_points=[];self.overlay_vars={};self.viewer.canvas.delete('all')
        self.layer_tree.selection_remove(*self.layer_tree.selection())
        self.tracker.data['layers']=[l for l in self.tracker.data['layers'] if l['path'] not in paths]
        for stage in self.app.stages:
            for key in ('control','breaklines','cloud_override'):
                var=getattr(stage,key,None)
                if isinstance(var,tk.Variable) and var.get() in paths:var.set('')
        if self.app.sbet_path.get() in paths:self.app.sbet_path.set('')
        self.review.scene=None;self.review.loaded_paths=();self.review.loaded_identities=[];self.review.loaded_layers=[];self.review.section=None
        self.last_scene=None
        if self.app.cloud_path.get() in paths:self.set_active_cloud(p.clouds[0] if p.clouds else '')
        p.refresh();self.viewer.draw();self.persist()

    def update_scope(self):
        app=self.app
        if app.task_scope.get()=='Entire project':
            app.scope_summary.set(f'{len(self.project_panel.clouds)} clouds · {len(self.project_panel.tracks)} trajectories')
        else:app.scope_summary.set('Input: '+(Path(app.cloud_path.get()).name if app.cloud_path.get() else 'Select one cloud in Project files'))
        if hasattr(self,'task_hint'):
            missing=sum(t.time_mode not in ('same','week') for t in self.project_panel.tracks)
            hint=f'{missing} trajectories need a time base. Select them in the sidebar, then open Settings.' if missing else 'Inspect checks inventory and trajectory matches. Review the results before QA or alignment.'
            self.task_hint.set(hint)

    def select_task(self,reset_scope=True):
        app=self.app;name=app.task_name.get()
        project_capable=name in ('Inspect / match','Strip QA','Align','Classify')
        app.scope_choice.configure(values=('Entire project','Selected cloud') if name!='Inspect / match' and project_capable else ('Entire project',) if project_capable else ('Selected cloud',))
        if reset_scope:app.task_scope.set('Entire project' if project_capable and name!='Classify' else 'Selected cloud')
        for i,stage in enumerate(app.stages):
            if stage.title==name:app.notebook.select(i)
        self.single_trajectory.pack_forget()
        if name=='Inspect / match' or (app.task_scope.get()=='Entire project' and name!='Classify'):
            app.notebook.pack_forget()
            self.project_task.pack(fill='x',before=app.run_button.master)
        else:
            self.project_task.pack_forget()
            app.notebook.pack(fill='x',before=app.run_button.master,pady=(8,0))
            if name in ('Strip QA','Align'):self.single_trajectory.pack(fill='x',before=app.notebook)
        app.run_button.configure(text='Run '+name)
        self.update_scope()

    def run_task(self):
        app=self.app;name=app.task_name.get()
        if app.task_scope.get()=='Entire project':
            if name=='Classify':
                self.start_classify_batch();return
            mode={'Inspect / match':'inspect','Strip QA':'qa','Align':'align'}.get(name)
            if mode:self.project_panel.start(mode)
            return
        if not app.cloud_path.get():
            messagebox.showinfo('Select input','Select one cloud in the Project files sidebar.',parent=self.root);return
        app.run()

    def save_classify_batch(self):
        batch=self.classify_batch
        path=Path(batch['manifest']);temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(batch,indent=2),encoding='utf-8')
        os.replace(temporary,path)

    def start_classify_batch(self):
        if self.app.runner.running:return
        stage=next(s for s in self.app.stages if type(s).__name__=='ClassifyStage')
        try:
            import uuid
            paths=list(dict.fromkeys(self.project_panel.clouds))
            if not paths:raise ValueError('Add project clouds before batch classification')
            if any(not Path(p).is_file() for p in paths):raise ValueError('A project input is missing')
            parent=Path(stage.batch_dir.get().strip())
            if not stage.batch_dir.get().strip() or not parent.is_dir():raise ValueError('Choose an existing Batch output parent')
            from pyargus.classify.job import validate_noise_bounds
            try:fraction=float(stage.noise_max_fraction.get())
            except ValueError:raise ValueError('Noise max fraction must be a number') from None
            validate_noise_bounds(float(stage.noise_min.get()) if stage.noise_min.get().strip() else None,
                                  float(stage.noise_max.get()) if stage.noise_max.get().strip() else None,
                                  fraction)
            folder=parent/('classification_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
            folder.mkdir()
            items=[dict(source=p,output=str(folder/f'{i+1:03d}_{Path(p).stem}_ground.las'),status='Waiting') for i,p in enumerate(paths)]
            self.classify_batch=dict(manifest=str(folder/'batch.json'),status='Running',settings=self.stage_settings(stage),items=items)
            self.tracker.data['last_classification_batch']=self.classify_batch['manifest']
            self.save_classify_batch();self.start_next_classify()
        except (OSError,ValueError) as exc:messagebox.showerror('Batch classification',str(exc),parent=self.root)

    def start_next_classify(self):
        if self.closed:return
        batch=getattr(self,'classify_batch',None)
        if not batch or batch['status']!='Running':return
        item=next((i for i in batch['items'] if i['status']=='Waiting'),None)
        if item is None:
            batch['status']='Completed';self.save_classify_batch()
            self.app.runner.log('Batch classification complete; review each flight. '+batch['manifest']);return
        stage=next(s for s in self.app.stages if type(s).__name__=='ClassifyStage')
        for key,value in batch['settings'].items():
            if key!='out_path':getattr(stage,key).set(value)
        self.set_active_cloud(item['source']);stage.out_path.set(item['output'])
        self.app.notebook.select(self.app.stages.index(stage))
        item['status']='Running';self.save_classify_batch()
        index=batch['items'].index(item)+1
        self.app.runner.log(f'Batch {index}/{len(batch["items"])}: {Path(item["source"]).name}')
        self.app.run()
        if self.active is None:
            item['status']='Failed validation';batch['status']='Stopped';self.save_classify_batch()

    def complete_classify_batch(self,job,status):
        batch=getattr(self,'classify_batch',None)
        if not batch or batch['status']!='Running' or job.get('stage_class')!='ClassifyStage':return
        item=next((i for i in batch['items'] if i['status']=='Running' and i['source']==job['settings'].get('cloud')),None)
        if item is None:return
        item.update(status=status,job=job['id'],records=job.get('records',[]))
        if status!='Needs review':batch['status']='Stopped'
        self.save_classify_batch()
        if batch['status']=='Running':self.root.after(0,self.start_next_classify)
        else:self.app.runner.log('Batch stopped; completed outputs retained; remaining files were not run. '+batch['manifest'])

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
        completed=self.active
        self.active=None
        if status=='Needs review' and completed.get('stage_class')=='ClassifyStage':
            results=[str(p) for kind,p in runner.products if kind=='classified' and Path(p).is_file()]
            source=completed.get('settings',{}).get('cloud')
            if source and len(results)==1:
                self.tracker.register_cloud_result(source,results[0],completed['id'])
                try:
                    self.activate_cloud_version(results[0])
                    self.viewer.mode.set('Classification')
                    self.app.runner.log('Active processing version: '+results[0])
                except (OSError,ValueError) as exc:
                    self.app.runner.log('Result saved; automatic activation failed: '+str(exc))
        self.persist();self.refresh();self.refresh_layers();self.history()
        self.complete_classify_batch(completed,status)

    def refresh(self):
        from pyargus.workspace_state import DEPENDENCIES
        current=[]
        for stage in STAGES:
            job=self.tracker.latest(stage)
            current.append((stage,job['id'] if job else None,self.tracker.status(stage,self.current_settings),tuple((j['id'],self.tracker.job_status(j,self.current_settings(j))) for j in self.tracker.current_jobs(stage))))
        key=repr(current)
        if key==self.refresh_key:return
        self.refresh_key=key
        selected=self.stage_tree.selection();self.stage_tree.delete(*self.stage_tree.get_children())
        first=None
        for stage in STAGES:
            job=self.tracker.latest(stage);status=self.tracker.status(stage,self.current_settings)
            deps=[s for s in DEPENDENCIES.get(stage,[]) if self.tracker.status(s) not in ('Accepted','Skipped')]
            action='Reviewed; continue to next stage' if status in ('Accepted','Skipped') else 'Review results / add note' if status=='Needs review' else 'Rerun with current inputs/settings' if status=='Outdated' else 'Run or explicitly skip'
            if status=='Outdated':
                reasons={self.tracker.stale_reason(j,self.current_settings(j)) for j in self.tracker.current_jobs(stage)}
                action+=': '+', '.join(sorted(r for r in reasons if r))
            if stage=='Classification':
                jobs=self.tracker.current_jobs(stage)
                if jobs:action+=f'; {sum(self.tracker.job_status(j,self.current_settings(j))=="Accepted" for j in jobs)}/{len(jobs)} recorded inputs accepted'
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
        previous=self.history_tree.selection()
        selection=self.stage_tree.selection()
        self.history_tree.delete(*self.history_tree.get_children())
        if not selection:return
        name={'Inspect':'Inspect / match','Initial QA':'Strip QA','Final QA':'Strip QA','Classification':'Classify','Alignment':'Align','Surface':'DTM / DSM','Contours':'Contours','Colorization':'Colorize'}.get(selection[0])
        if name and name!=self.app.task_name.get():
            self.app.task_name.set(name);self.select_task()
        if selection[0] in ('Initial QA','Final QA'):self.qa_phase.set(selection[0])
        for j in reversed(self.tracker.data['jobs']):
            if j['stage']==selection[0]:self.history_tree.insert('','end',iid=j['id'],text=j['stage']+(' — '+Path(j['settings']['cloud']).name if j.get('settings',{}).get('cloud') else ''),values=(j['started'],self.tracker.job_status(j,self.current_settings(j)),f"{j.get('elapsed',0):.1f}s"))
        children=self.history_tree.get_children()
        if children:self.history_tree.selection_set(previous[0] if previous and previous[0] in children else children[0]);self.details()

    def details(self):
        job=self.selected_job();self.detail.delete('1.0','end')
        if job:
            lines=[f"{job['stage']} — {job['status']}",f"Started: {job['started']}",f"Elapsed: {job.get('elapsed',0):.1f} seconds"]
            if job.get('error'):lines.append('Error: '+str(job['error']))
            lines.extend('Input: '+str(item[0]) for item in job.get('inputs',[]))
            reason=self.tracker.stale_reason(job,self.current_settings(job))
            if reason:lines.append('Outdated: '+reason)
            lines.extend('Output: '+str(item[0]) for item in job.get('outputs',[]))
            lines.extend('Job record: '+p for p in job.get('records',[]))
            lines.extend('Note: '+str(n) for n in job.get('notes',[]))
            self.detail.insert('end','\n'.join(lines))

    def decide(self,decision):
        selected=self.stage_tree.selection()
        if not selected:return
        note=simpledialog.askstring('Review note','Why are you accepting, revisiting or skipping this stage?',parent=self.root)
        if note is None:return
        try:
            job=self.selected_job()
            self.tracker.decide(selected[0],decision,note,self.current_settings(job) if job else None,job_id=job['id'] if job else None)
            self.persist();self.refresh();self.history()
        except ValueError as exc:messagebox.showerror('Progress',str(exc),parent=self.root)

    def add_layer(self,path,kind,origin='Unverified import',**extra):
        path=str(Path(path).resolve())
        if not any(l['path']==path for l in self.tracker.data['layers']):self.tracker.data['layers'].append(dict(path=path,kind=kind,origin=origin,visible=True,**extra))

    def refresh_layers(self):
        selected={l['path'] for l in self.selected_layers()}
        self.layer_tree.delete(*self.layer_tree.get_children())
        tracks={t.path:t for t in self.project_panel.tracks}
        for i,layer in enumerate(self.tracker.data['layers']):
            var=self.visible_var(layer['path']);mark='●' if var is not None and var.get() else '○'
            state=layer['kind']
            if layer['path'] in self.project_panel.clouds:state='Active input'
            elif layer['path'] in self.tracker.data.get('cloud_versions',{}):state='Retained version'
            if layer['path'] in tracks:
                t=tracks[layer['path']];state='Set time base' if t.time_mode not in ('same','week') else 'Time: '+t.time_mode
            self.layer_tree.insert('','end',iid=str(i),text=mark+' '+Path(layer['path']).name,values=(state,))
            if layer['path'] in selected:self.layer_tree.selection_add(str(i))
        self.file_summary.set(self.project_panel.counts.get())

    def selected_layers(self):return [self.tracker.data['layers'][int(i)] for i in self.layer_tree.selection() if int(i)<len(self.tracker.data['layers'])]

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
                var=tk.BooleanVar(value=True);self.overlay_vars[layer['path']]=var;self.viewer.extra_points.append((points,var))
                ttk.Checkbutton(self.viewer.layers,text=Path(layer['path']).name,variable=var,command=self.viewer.draw).pack(anchor='w')
                self.viewer.draw();return
            else:
                from pyargus.formats.breaklines import read_breaklines
                segments=read_breaklines(layer['path'])
            var=tk.BooleanVar(value=True);self.overlay_vars[layer['path']]=var;self.viewer.extra_layers.append((layer['path'],segments,var))
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
        self.tracker.data['task_selection']={'name':self.app.task_name.get(),'scope':self.app.task_scope.get()}
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
                saved=data['settings'].get(type(stage).__name__,{})
                defaults={k:v for k,v in self.stage_defaults.get(type(stage).__name__,{}).items() if k not in saved}
                for key,value in {**defaults,**saved}.items():
                    var=getattr(stage,key,None)
                    if isinstance(var,tk.Variable):var.set(value)
            self.app.cloud_path.set(data.get('active_cloud',''));self.app.sbet_path.set(data.get('trajectory',''));self.app.trj_time.set(data.get('trj_time','Select TRJ time'))
            self.qa_phase.set(data.get('qa_phase','Initial QA'));self.sync_project_layers();self.refresh()
            task=data.get('task_selection',{})
            if task.get('name') in ('Inspect / match',*[s.title for s in self.app.stages]):
                self.app.task_name.set(task['name']);self.select_task()
                if task.get('scope') in self.app.scope_choice.cget('values'):
                    self.app.task_scope.set(task['scope']);self.select_task(reset_scope=False)
            self.pending_view=data.get('view') or None
            if self.pending_view and all(Path(p).exists() for p in self.pending_view['paths']):self.viewer.load(self.pending_view['paths'])
            if data['sections']:
                cut=data['sections'][-1]
                for var,value in zip(self.review.coords,cut['start']+cut['end']):var.set(str(value))
                self.review.width.set(str(cut['width']));self.review.set_corridor()
        except Exception as exc:messagebox.showerror('Workspace',str(exc),parent=self.root)

    def poll(self):
        if self.closed:return
        if getattr(self,'pending_version_view',False) and not self.viewer.busy:
            self.pending_version_view=False
            self.viewer.load(list(self.project_panel.clouds))
        v=self.viewer
        if not v.busy and v.scene is not None and (v.scene is not self.last_scene or self.review.record is not self.last_record):
            live={str(var) for _,var in v.extra_points}|{str(var) for _,_,var in v.extra_layers}
            self.overlay_vars={p:var for p,var in self.overlay_vars.items() if str(var) in live}
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
                if p not in self.project_panel.clouds and p not in self.tracker.data.get('cloud_versions',{}) and not any(layer['path']==p and layer['kind']=='output' for layer in self.tracker.data['layers']):self.project_panel.clouds.append(p)
            self.project_panel.refresh()
            self.refresh_layers()
        key=tuple((p,var.get()) for p,var in zip(v.paths,v.visible))+tuple((p,item[1].get()) for p,item in zip(v.track_paths,v.tracks))
        if key!=getattr(self,'visibility_key',None):
            self.visibility_key=key;self.refresh_layers()
        self.refresh()
        if time.monotonic()-self.last_save>15:
            self.persist();self.last_save=time.monotonic()
        self.poll_id=self.root.after(1500,self.poll)

    def close(self):
        self.persist();self.closed=True;self.root.after_cancel(self.poll_id)
        self.review.close();self.viewer.close()
