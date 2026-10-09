"""Header-only project map and evidence-based status, independent of processing."""
from pathlib import Path
import queue
from datetime import datetime
import threading
import tkinter as tk
from tkinter import ttk
import numpy as np

from pyargus.project_overview import (read_extents,coordinate_groups,combined_bounds,
    map_transform,map_pixels,map_world,camera_plane,workflow_summary)


class ProjectOverview:
    def __init__(self,layout):
        self.layout=layout;self.w=layout.w;self.v=layout.v;self.root=layout.root
        self.rows=[];self.cache={};self.groups=[];self.generation=0;self.worker=None
        self.messages=queue.Queue();self.closed=False;self.paths_key=None;self.status_key=None
        self.map_key=None;self.selection=None;self.transforms={};self.summary={}
        self.notice=tk.StringVar(value='LAS header extents; not a coverage or accuracy assessment.')
        self.headline=tk.StringVar();self.detail=tk.StringVar();self.metrics=tk.StringVar()
        self.inventory=tk.StringVar();self.inputs=tk.StringVar();self.viewing=tk.StringVar();self.ground=tk.StringVar();self.section=tk.StringVar()
        self.frame=ttk.Frame(self.w.tabs,padding=8)
        self.w.tabs.insert(0,self.frame,text='Project overview')
        heading=ttk.Frame(self.frame);heading.pack(fill='x')
        ttk.Label(heading,textvariable=self.headline,font=('Segoe UI',11,'bold')).pack(side='left',fill='x',expand=True)
        self.next_button=ttk.Button(heading,command=self.next_action);self.next_button.pack(side='right')
        ttk.Label(self.frame,textvariable=self.detail,wraplength=1100).pack(fill='x',pady=(3,5))
        ttk.Label(self.frame,textvariable=self.metrics).pack(fill='x')
        body=ttk.Panedwindow(self.frame,orient='horizontal');body.pack(fill='both',expand=True,pady=5)
        left=ttk.Frame(body);right=ttk.Frame(body);body.add(left,weight=3);body.add(right,weight=2)
        bar=ttk.Frame(left);bar.pack(fill='x')
        self.group=tk.StringVar();self.group_choice=ttk.Combobox(bar,textvariable=self.group,state='readonly',width=35)
        self.group_choice.pack(side='left',fill='x',expand=True);self.group_choice.bind('<<ComboboxSelected>>',lambda e:self.draw())
        ttk.Button(bar,text='Refresh headers',command=lambda:self.request(force=True)).pack(side='left')
        self.canvas=tk.Canvas(left,width=400,height=110,background='#101925',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,pady=4)
        self.bind_map(self.canvas)
        ttk.Label(left,textvariable=self.notice,wraplength=650).pack(fill='x')
        commands=ttk.Frame(left);commands.pack(fill='x',pady=3)
        for label,fn in [('Center selected',self.center_selected),('Fit selected extent',self.fit_selected),('Load selected cloud',self.load_selected)]:
            ttk.Button(commands,text=label,command=fn).pack(side='left',padx=2)
        file_frame=ttk.Frame(left);file_frame.pack(fill='x')
        self.files=ttk.Treeview(file_frame,columns=('points','role','status'),show='tree headings',height=2,selectmode='browse')
        for key,title,width in [('#0','Cloud',220),('points','Header points',100),('role','Role',120),('status','Header status',180)]:
            self.files.heading(key,text=title);self.files.column(key,width=width,minwidth=60)
        file_scroll=ttk.Scrollbar(file_frame,orient='vertical',command=self.files.yview);file_scroll.pack(side='right',fill='y')
        self.files.configure(yscrollcommand=file_scroll.set);self.files.pack(fill='x');self.files.bind('<<TreeviewSelect>>',self.select_file)
        for var in (self.inventory,self.inputs,self.viewing,self.section):
            ttk.Label(right,textvariable=var,wraplength=480,justify='left').pack(fill='x',pady=1)
        ttk.Label(right,text='Stage evidence — review decisions',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(6,3))
        stage_frame=ttk.Frame(right);stage_frame.pack(fill='both',expand=True)
        self.stages=ttk.Treeview(stage_frame,columns=('status',),show='tree headings',height=5,selectmode='browse')
        self.stages.heading('#0',text='Stage');self.stages.column('#0',width=130,minwidth=90)
        self.stages.heading('status',text='Current status');self.stages.column('status',width=150,minwidth=100)
        stage_scroll=ttk.Scrollbar(stage_frame,orient='vertical',command=self.stages.yview);stage_scroll.pack(side='right',fill='y')
        self.stages.configure(yscrollcommand=stage_scroll.set);self.stages.pack(fill='both',expand=True);self.stages.bind('<<TreeviewSelect>>',self.select_stage)
        # A small locator stays available when the review drawer is collapsed.
        mini=ttk.LabelFrame(self.w.sidebar,text='Overview',padding=4)
        mini.pack(fill='x',before=layout.progress.master,pady=4)
        tools=ttk.Frame(mini);tools.pack(fill='x')
        ttk.Button(tools,text='Project status',command=self.show).pack(side='left')
        self.locator_visible=tk.BooleanVar(value=True)
        ttk.Checkbutton(tools,text='Map',variable=self.locator_visible,command=self.toggle_locator).pack(side='right')
        self.locator=tk.Canvas(mini,width=220,height=110,background='#101925',highlightthickness=0)
        self.locator.pack(fill='x',pady=3);self.bind_map(self.locator)
        ttk.Label(mini,text='N ↑  Header extents · click to center',wraplength=250).pack(anchor='w')
        # Replace the redundant helper below the existing stage list with next-action guidance.
        layout.progress.pack_forget()
        layout.progress_help.configure(textvariable=self.headline,text='')
        self.sidebar_next=ttk.Button(layout.progress.master,command=self.next_action)
        self.sidebar_next.pack(fill='x',pady=3)
        layout.menus['View'].add_command(label='Project overview / status',command=self.show)
        layout.menus['View'].add_checkbutton(label='Overview locator',variable=self.locator_visible,command=self.toggle_locator)
        self.timer=self.root.after(250,self.poll)
        self.update_status()

    def bind_map(self,canvas):
        canvas.bind('<Configure>',lambda e:self.draw())
        canvas.bind('<Button-1>',lambda e:self.click(e,canvas))

    def show(self):self.layout.show_panel(self.frame)

    def toggle_locator(self):
        if self.locator_visible.get():self.locator.pack(fill='x',pady=3)
        else:self.locator.pack_forget()
        self.draw()

    def paths(self):return tuple(dict.fromkeys(str(Path(p).resolve()) for p in [*self.w.project_panel.clouds,*self.v.paths]))

    def request(self,force=False):
        paths=self.paths()
        if self.worker and self.worker.is_alive():
            if paths!=self.paths_key or force:self.again=True
            return
        if paths==self.paths_key and not force:return
        self.paths_key=paths;self.generation+=1;generation=self.generation;self.again=False
        self.rows=[];self.groups=[];self.transforms.clear();self.refresh_files();self.draw()
        if not paths:
            self.group.set('');self.group_choice.configure(values=());self.notice.set('Add clouds to show LAS header extents.');return
        cache=dict(self.cache);self.notice.set('Reading LAS headers only; no point-cloud scan…')
        def work():
            try:
                rows,cache_result=read_extents(paths,cache,cancel=lambda:self.closed)
                result=(rows,cache_result,None)
            except Exception as exc:result=([],{},str(exc))
            self.messages.put((generation,paths,result))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()

    def current_group(self):
        values=list(self.group_choice.cget('values'))
        try:return self.groups[values.index(self.group.get())]
        except (ValueError,IndexError):return None

    def accept_headers(self,rows,cache,error):
        self.rows=rows;self.cache=cache;self.groups=coordinate_groups(rows);self.read_time=datetime.now().strftime('%H:%M:%S')
        values=[f'{i+1}: {g["name"]}' for i,g in enumerate(self.groups)]
        old=self.group.get();self.group_choice.configure(values=values)
        index=0
        if self.v.scene is not None and self.v.scene[5] is not None:
            from pyproj import CRS
            index=next((i for i,g in enumerate(self.groups) if CRS(g['crs'])==self.v.scene[5]),0)
        self.group.set(old if old in values else values[index] if values else '')
        self.notice.set(error or f'Headers checked {self.read_time}. LAS rectangles, not coverage. {len(self.groups)} coordinate group(s); incompatible or undeclared CRS are not combined.')
        self.refresh_files();self.draw();self.update_status(force=True)

    def refresh_files(self):
        selected=self.selection;self.files.delete(*self.files.get_children())
        inputs=set(self.w.project_panel.clouds);loaded=set(self.v.paths)
        for i,row in enumerate(self.rows):
            roles=[]
            if row['path'] in inputs:roles.append('Processing')
            if row['path'] in loaded:roles.append('Viewing')
            self.files.insert('','end',iid=str(i),text=Path(row['path']).name,
                values=(f'{row["points"]:,}' if row['points'] is not None else 'Unknown',' + '.join(roles),row['error'] or 'Header read'))
            if row['path']==selected:self.files.selection_set(str(i))

    def select_file(self,event=None):
        chosen=self.files.selection()
        if not chosen:return
        row=self.rows[int(chosen[0])];self.selection=row['path']
        for i,g in enumerate(self.groups):
            if row in g['rows']:self.group.set(self.group_choice.cget('values')[i]);break
        self.draw()

    def selected_row(self):return next((r for r in self.rows if r['path']==self.selection),None)

    def scene_matches(self,g):
        if not g or self.v.scene is None or self.v.scene[5] is None:return False
        from pyproj import CRS
        return CRS(g['crs'])==self.v.scene[5]

    def draw(self):
        if not hasattr(self,'locator'):return
        g=self.current_group();bounds=combined_bounds(g['rows']) if g else None
        colors=('#3abeff','#ffab41','#71de81','#dd73fa','#ff697d','#ebdf55','#5addcc','#beb9ff')
        for canvas in (self.canvas,self.locator):
            canvas.delete('all')
            width=max(2,canvas.winfo_width());height=max(2,canvas.winfo_height())
            if bounds is None:
                canvas.create_text(width/2,height/2,text='No mapped cloud extents',fill='#b9c8d6',width=max(80,width-20));continue
            transform=map_transform(bounds,width,height);self.transforms[canvas]=transform
            for i,row in enumerate(g['rows']):
                b=row['bounds'];xy=map_pixels([[b[0],b[1]],[b[3],b[4]]],transform)
                loaded=row['path'] in self.v.paths
                visible=loaded and self.v.visible[self.v.paths.index(row['path'])].get()
                options=dict(outline=colors[i%8],width=3 if row['path']==self.selection else 1,dash=() if visible else (4,3))
                canvas.create_rectangle(*xy.ravel(),**options,tags='extent')
                if canvas is self.canvas:
                    canvas.create_text(xy[0,0]+4,xy[0,1]-4,text=Path(row['path']).name,fill=colors[i%8],anchor='sw',tags='extent-label')
            if self.scene_matches(g) and hasattr(self.v,'center'):
                plane=camera_plane(self.v.center,self.v.yaw,self.v.pitch,self.v.pan,self.v.span,self.v.zoom,
                    max(2,self.v.canvas.winfo_width()),max(2,self.v.canvas.winfo_height()))
                from pyargus.review_memory import view_center
                scale=min(max(2,self.v.canvas.winfo_width()),max(2,self.v.canvas.winfo_height()))*.85/self.v.span*self.v.zoom
                center=view_center(dict(center=self.v.center,pan_units=self.v.pan/scale,yaw=self.v.yaw,pitch=self.v.pitch))
                x,y=map_pixels(center[:2],transform)
                canvas.create_line(x-5,y,x+5,y,fill='white',width=2,tags='view-center')
                canvas.create_line(x,y-5,x,y+5,fill='white',width=2,tags='view-center')
                if plane is not None:
                    pixels=map_pixels(plane,transform);canvas.create_line(*np.vstack([pixels,pixels[0]]).ravel(),fill='white',dash=(3,2),tags='view-plane')
                if self.v.corridor is not None:
                    a,b,full_width=self.v.corridor;delta=np.asarray(b)-a;length=np.linalg.norm(delta)
                    if length:
                        side=np.array([-delta[1],delta[0]])/length*full_width/2
                        p=map_pixels([a+side,b+side,b-side,a-side,a+side],transform)
                        canvas.create_line(*p.ravel(),fill='#ffd15b',width=2,tags='section')
            if hasattr(self.w,'notes'):
                for issue in self.w.notes.model.data['issues']:
                    if issue['state']=='Resolved' or self.w.notes.availability.get(issue['id'])!='Available':continue
                    from pyproj import CRS
                    if not issue['view']['crs'] or CRS(issue['view']['crs'])!=CRS(g['crs']):continue
                    if not any(s['path'] in {r['path'] for r in g['rows']} for s in issue['view']['inputs']):continue
                    x,y=map_pixels(issue['anchor']['xyz'][:2],transform)
                    canvas.create_oval(x-3,y-3,x+3,y+3,outline='#ff7d72',width=2,tags='issue')
            canvas.create_text(width-10,10,text='N ↑',fill='white',anchor='ne')

    def busy(self):return self.v.busy or self.w.review.busy or self.w.app.runner.running or self.w.notes.pending is not None

    def navigation_ready(self,row=None):
        if self.busy():raise ValueError('Wait for loading or processing to finish before map navigation.')
        if row and row['error']:raise ValueError(row['error'])
        g=self.current_group()
        if not self.scene_matches(g):raise ValueError('Load a cloud in this coordinate group before navigating. The map does not reproject.')
        if row and row['path'] not in self.v.paths:raise ValueError('Load the selected cloud before centering or fitting its extent.')
        observed={s['path']:s for s in self.w.review.loaded_identities}
        candidates=[row] if row else [r for r in g['rows'] if r['path'] in self.v.paths]
        if not candidates or any(observed.get(r['path'])!=r['source'] for r in candidates):
            raise ValueError('Header and loaded cloud identities differ; reload clouds and refresh headers.')

    def run(self,fn):
        try:fn()
        except (ValueError,OSError) as exc:self.notice.set(str(exc))

    def click(self,event,canvas):
        if canvas not in self.transforms:return
        def navigate():
            xy=map_world([event.x,event.y],self.transforms[canvas]);g=self.current_group()
            hits=[r for r in g['rows'] if r['bounds'][0]<=xy[0]<=r['bounds'][3] and r['bounds'][1]<=xy[1]<=r['bounds'][4]]
            if not hits:raise ValueError('Click within a mapped cloud extent.')
            loaded=[r for r in hits if r['path'] in self.v.paths]
            row=loaded[0] if loaded else hits[0];self.selection=row['path'];self.refresh_files();self.draw()
            self.navigation_ready(row);self.move_camera(xy)
        self.run(navigate)

    def move_camera(self,xy,bounds=None):
        self.v.remember_view();self.v.cancel_corridor_drag();self.w.notes.disarm()
        self.v.choose_pivot=False;self.v.orbit_anchor=None;self.v.center[:2]=xy;self.v.pan[:]=0
        if bounds is not None:
            self.v.center[2]=(bounds[2]+bounds[5])/2
            self.v.span=max(float(np.linalg.norm(np.asarray(bounds)[3:]-np.asarray(bounds)[:3])),1.);self.v.zoom=1.
        self.v.draw();self.draw();self.notice.set('View moved. Processing inputs and section source are retained.')

    def center_selected(self):
        def navigate():
            row=self.selected_row()
            if row is None:raise ValueError('Select a cloud row first.')
            self.navigation_ready(row);b=row['bounds'];self.move_camera((np.array(b[:2])+b[3:5])/2)
        self.run(navigate)

    def fit_selected(self):
        def navigate():
            row=self.selected_row()
            if row is None:raise ValueError('Select a cloud row first.')
            self.navigation_ready(row);b=row['bounds'];self.move_camera((np.array(b[:2])+b[3:5])/2,b)
        self.run(navigate)

    def load_selected(self):
        def load():
            if self.busy():raise ValueError('Wait for loading or processing to finish.')
            row=self.selected_row()
            if row is None:raise ValueError('Select a cloud row first.')
            if row['error']:raise ValueError(row['error'])
            # Explicit loading uses the existing viewer and all its CRS validation.
            self.v.load([row['path']]);self.notice.set('Loading selected cloud for viewing; processing inputs are retained.')
        self.run(load)

    def update_status(self,force=False):
        stages=[(s,*self.w.stage_tree.item(s,'values')) for s in self.w.stage_tree.get_children()]
        issues=sum(i['state']!='Resolved' for i in self.w.notes.model.data['issues']) if hasattr(self.w,'notes') else 0
        tracks=self.w.project_panel.tracks;clocks=sum(t.time_mode not in ('same','week') for t in tracks)
        running=self.w.active['stage'] if self.w.active and self.w.app.runner.running else None
        visible=sum(var.get() for var in self.v.visible)
        source=self.w.review.section_source.get();section=self.w.review.section
        key=repr((stages,self.w.project_panel.clouds,clocks,issues,running,self.v.paths,visible,source,id(section),self.w.app.cloud_path.get(),self.layout.mode,self.busy()))
        if key==self.status_key and not force:return
        self.status_key=key
        self.summary=workflow_summary(self.w.tracker,stages,self.w.project_panel.clouds,self.w.current_settings,running,clocks,issues)
        s=self.summary;self.headline.set(s['headline']);self.detail.set(s['detail'])
        self.metrics.set(f'{s["reviewed"]}/{s["total"]} listed stages accepted or skipped · {issues} unresolved issue(s)')
        loading=self.busy();state='disabled' if loading or s['kind']=='busy' else 'normal'
        for button in (self.next_button,self.sidebar_next):button.configure(text=s['label'],state=state)
        active=set(self.w.project_panel.clouds);header_rows=[r for r in self.rows if r['path'] in active]
        known=[r for r in header_rows if r['points'] is not None];missing_headers=len(active)-len(known)
        self.inventory.set(f'Header inventory: {sum(r["points"] for r in known):,} recorded points across {len(known)} active cloud(s)'
            +(f'; {missing_headers} header(s) unavailable/pending' if missing_headers else '')
            +f'\n{clocks} trajectory clock(s) unset · '+str(sum(bool(r['error']) for r in self.rows))+' cloud header/map warning(s)')
        self.inputs.set(f'Processing: {len(self.w.project_panel.clouds)} active cloud(s), {len(tracks)} trajectories\nSelected task input: '+(Path(self.w.app.cloud_path.get()).name if self.w.app.cloud_path.get() else 'None'))
        self.viewing.set(f'Viewing: {visible}/{len(self.v.paths)} loaded cloud(s) visible · '+('Loading/extracting…' if loading else 'Display sample')+'\nGround runs: '+s['coverage'])
        self.ground.set('Ground classification: '+s['coverage'])
        profile='No extracted profile' if section is None else f'{section.matched:,} corridor returns; {len(section.points):,} displayed/sample returns'
        self.section.set('Section source: '+(Path(source).name if source and source!='Compare all loaded clouds' else source or 'Choose source')+'\n'+profile)
        for stage,status,detail in stages:
            label=status+(' (partial)' if stage=='Classification' and s['missing_ground'] and s['ground_recorded'] and status in ('Accepted','Needs review') else '')
            if self.stages.exists(stage):self.stages.item(stage,values=(label,))
            else:self.stages.insert('','end',iid=stage,text=stage,values=(label,))

    def select_stage(self,event=None):
        chosen=self.stages.selection()
        if not chosen:return
        stage=chosen[0]
        self.w.stage_tree.selection_set(stage);self.w.history();self.layout.show_panel(self.w.progress_tab)

    def next_action(self):
        if self.busy():return
        s=self.summary;kind=s.get('kind');stage=s.get('stage')
        if kind=='add':self.w.add_files()
        elif kind=='settings':self.layout.project_settings()
        elif kind=='delivery':self.layout.set_mode('Deliver')
        elif stage:
            self.w.stage_tree.selection_set(stage);self.w.history()
            if kind=='task':self.layout.set_mode('Process')
            else:self.layout.show_panel(self.w.progress_tab)

    def snapshot(self):return dict(locator=self.locator_visible.get(),coordinate_group=self.group.get())

    def restore(self,state):
        self.locator_visible.set(bool(state.get('locator',True)));self.group.set(str(state.get('coordinate_group','')))
        self.toggle_locator();self.paths_key=None;self.request();self.update_status(force=True)

    def poll(self):
        if self.closed or self.w.closed:return
        try:
            while True:
                generation,paths,result=self.messages.get_nowait()
                if generation==self.generation and paths==self.paths():self.accept_headers(*result)
        except queue.Empty:pass
        self.request(force=getattr(self,'again',False));self.update_status()
        key=repr((self.group.get(),self.selection,self.v.paths,[x.get() for x in self.v.visible],
            self.v.yaw,self.v.pitch,self.v.zoom,getattr(self.v,'span',None),getattr(self.v,'center',None),self.v.pan,self.v.corridor,
            self.v.canvas.winfo_width(),self.v.canvas.winfo_height(),self.w.notes.refresh_key))
        if key!=self.map_key:self.map_key=key;self.refresh_files();self.draw()
        self.timer=self.root.after(300,self.poll)

    def close(self):
        self.closed=True
        if self.timer:self.root.after_cancel(self.timer);self.timer=None
