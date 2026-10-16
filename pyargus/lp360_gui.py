"""One LP360 setup screen and one runner; missing inputs remain editable."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import queue
import uuid
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pyargus.lp360_jobs import discover,suggest,inspect_recipe


class LP360Shortcut:
    def __init__(self,layout):
        self.layout=layout;self.w=layout.w;self.app=layout.app;self.root=layout.root
        self.window=None;self.running=False;self.events=queue.Queue();self.result=None;self.discovery=None;self.recipe=None

    def busy(self):
        return self.app.runner.running or self.w.viewer.busy or self.w.review.busy or self.running

    def open(self,root=None):
        if self.window is not None and self.window.winfo_exists():self.window.lift();return
        if self.busy():messagebox.showinfo('LP360 job','Finish or stop the current operation first.',parent=self.root);return
        root=root or filedialog.askdirectory(parent=self.root,title='Choose the LP360 project root',initialdir=self.w.tracker.data.get('last_lp360_root',str(Path.home())))
        if not root:return
        win=self.window=tk.Toplevel(self.root);win.title('LP360 job — discover and run');win.geometry('1100x780');win.minsize(850,620);win.transient(self.root);win.protocol('WM_DELETE_WINDOW',self.close)
        self.path=tk.StringVar(value=str(root));self.group=tk.StringVar();self.output=tk.StringVar(value=str(Path(root)/'pyArgus_jobs'))
        self.status=tk.StringVar(value='Finding project files…');self.found=tk.StringVar()
        head=ttk.Frame(win,padding=10);head.pack(fill='x')
        ttk.Label(head,text='Project folder').grid(row=0,column=0,sticky='w');ttk.Entry(head,textvariable=self.path).grid(row=0,column=1,sticky='ew',padx=6)
        ttk.Button(head,text='Browse…',command=self.choose_root).grid(row=0,column=2);self.scan_button=ttk.Button(head,text='Scan folder',command=self.scan);self.scan_button.grid(row=0,column=3,padx=4);head.columnconfigure(1,weight=1)
        tabs=ttk.Notebook(win);tabs.pack(fill='both',expand=True,padx=10);files=ttk.Frame(tabs,padding=8);options=ttk.Frame(tabs,padding=8);tabs.add(files,text='Files and readiness');tabs.add(options,text='Processing settings')
        ttk.Label(files,text='Source LAS folder').grid(row=0,column=0,sticky='w')
        self.group_choice=ttk.Combobox(files,textvariable=self.group,state='readonly');self.group_choice.grid(row=0,column=1,columnspan=2,sticky='ew',padx=6);self.group_choice.bind('<<ComboboxSelected>>',self.choose_group)
        ttk.Button(files,text='Select LAS files…',command=self.choose_clouds).grid(row=0,column=3)
        self.tree=ttk.Treeview(files,columns=('count','path','state'),show='tree headings',height=5)
        self.tree.heading('#0',text='Input');self.tree.column('#0',width=105)
        for col,label,width in [('count','Count',65),('path','Location',420),('state','State',170)]:self.tree.heading(col,text=label);self.tree.column(col,width=width)
        self.tree.grid(row=1,column=0,columnspan=4,sticky='nsew',pady=8)
        ttk.Button(files,text='Select trajectories…',command=self.choose_tracks).grid(row=2,column=0,sticky='w')
        self.clock=tk.StringVar(value='Detected per file');ttk.Combobox(files,textvariable=self.clock,values=('Detected per file','same','week'),state='readonly',width=20).grid(row=2,column=1,sticky='w')
        self.week=tk.StringVar();ttk.Label(files,text='GPS week (when required)').grid(row=2,column=2,sticky='e');ttk.Entry(files,textvariable=self.week,width=12).grid(row=2,column=3,sticky='w')
        self.vars={}
        rows=[('control','Control CSV',self.choose_control),('eo','EO CSV',lambda:self.choose_file('eo','EO CSV','*.csv')),('images','Imagery folder',lambda:self.choose_folder('images')),('calibration','Calibration override (optional)',lambda:self.choose_file('calibration','Camera calibration','*.cal'))]
        for row,(key,label,command) in enumerate(rows,3):
            self.vars[key]=tk.StringVar();ttk.Label(files,text=label).grid(row=row,column=0,sticky='w',pady=3);ttk.Entry(files,textvariable=self.vars[key]).grid(row=row,column=1,columnspan=2,sticky='ew',padx=6);ttk.Button(files,text='Browse…',command=command).grid(row=row,column=3)
        self.order=tk.StringVar(value='auto');ttk.Label(files,text='Control order').grid(row=7,column=0,sticky='w');ttk.Combobox(files,textvariable=self.order,values=('auto','pnez','penz'),state='readonly',width=15).grid(row=7,column=1,sticky='w')
        self.no_control=tk.BooleanVar();ttk.Checkbutton(files,text='Continue without survey control',variable=self.no_control).grid(row=7,column=2,columnspan=2,sticky='w')
        self.recolor=tk.BooleanVar();ttk.Checkbutton(files,text='Recolor from EO and imagery (otherwise preserve existing RGB)',variable=self.recolor).grid(row=8,column=0,columnspan=4,sticky='w',pady=5)
        ttk.Label(files,textvariable=self.found,wraplength=950).grid(row=9,column=0,columnspan=4,sticky='w')
        files.columnconfigure(1,weight=1);files.columnconfigure(2,weight=1);files.rowconfigure(1,weight=1)
        self.align=tk.BooleanVar(value=True);ttk.Checkbutton(options,text='Align relative vertical offsets; trajectory attitudes are not used',variable=self.align).grid(row=0,column=0,columnspan=4,sticky='w',pady=5)
        self.shared=tk.BooleanVar();ttk.Checkbutton(options,text='All clouds share their vertical datum and XYZ units',variable=self.shared).grid(row=1,column=0,columnspan=4,sticky='w')
        self.vars['map_crs']=tk.StringVar();ttk.Label(options,text='CRS for untagged LAS').grid(row=2,column=0,sticky='w');ttk.Entry(options,textvariable=self.vars['map_crs']).grid(row=2,column=1,columnspan=3,sticky='ew')
        numbers=[('cell','Ground / surface cell'),('slope','Ground slope'),('window','Ground window'),('threshold','Ground threshold'),('alignment_cell','Alignment cell'),('min_points','Minimum alignment-cell points'),('contour_interval','Contour interval'),('max_points','Alignment point limit'),('workers','CPU tile workers'),('memory_mb','Tile memory estimate (MiB)'),('quarter_turns','Image-grid quarter turns'),('max_grid_cells','Maximum surface cells')]
        for index,(key,label) in enumerate(numbers):
            row=3+index//2;column=2*(index%2);self.vars[key]=tk.StringVar();ttk.Label(options,text=label).grid(row=row,column=column,sticky='w',padx=5,pady=5);ttk.Entry(options,textvariable=self.vars[key],width=17).grid(row=row,column=column+1,sticky='ew',padx=5)
        for index,(key,label) in enumerate((('noise_min','Optional low-noise Z limit'),('noise_max','Optional high-noise Z limit'))):
            self.vars[key]=tk.StringVar();ttk.Label(options,text=label).grid(row=9,column=index*2,sticky='w',padx=5);ttk.Entry(options,textvariable=self.vars[key],width=17).grid(row=9,column=index*2+1,sticky='ew',padx=5)
        ttk.Label(options,text='Lengths use the LAS XYZ units. Existing noise classes 7/18 are retained. No gap filling, contour smoothing, or survey fitting is applied. Completed outputs remain available for QA review.',wraplength=940).grid(row=10,column=0,columnspan=4,sticky='w',pady=12)
        options.columnconfigure(1,weight=1);options.columnconfigure(3,weight=1)
        from pyargus.alignment_report_gui import AlignmentReportPanel
        reporting=ttk.Frame(tabs);tabs.add(reporting,text='Alignment report');self.reporting=AlignmentReportPanel(reporting)
        bottom=ttk.Frame(win,padding=10);bottom.pack(fill='x')
        ttk.Label(bottom,text='Output parent').grid(row=0,column=0,sticky='w');ttk.Entry(bottom,textvariable=self.output).grid(row=0,column=1,columnspan=3,sticky='ew',padx=5);ttk.Button(bottom,text='Choose…',command=self.choose_output).grid(row=0,column=4)
        ttk.Label(bottom,textvariable=self.status,wraplength=1000).grid(row=1,column=0,columnspan=5,sticky='w',pady=7)
        self.run_button=ttk.Button(bottom,text='Run LP360 job',command=self.start);self.run_button.grid(row=2,column=0,sticky='w')
        ttk.Button(bottom,text='Stop',command=self.app.runner.cancel).grid(row=2,column=1,sticky='w')
        self.report_button=ttk.Button(bottom,text='Open results',command=self.open_report,state='disabled');self.report_button.grid(row=2,column=2,sticky='w')
        ttk.Button(bottom,text='Close',command=self.close).grid(row=2,column=4,sticky='e');bottom.columnconfigure(3,weight=1)
        self.scan()

    def choose_root(self):
        if self.busy():return
        p=filedialog.askdirectory(parent=self.window,title='LP360 project root')
        if p:self.path.set(p);self.output.set(str(Path(p)/'pyArgus_jobs'));self.scan()

    def scan(self):
        if self.busy():return
        root=self.path.get();self.running=True;self.phase='scan';self.result=None;self.scan_button.configure(state='disabled');self.run_button.configure(state='disabled');self.status.set('Finding LP360 files…')
        def work(runner):
            try:found=discover(root,cancel=runner.cancelled,log=runner.log)
            except InterruptedError:self.result=dict(status='Cancelled');return
            recipe=suggest(found);issues,info=inspect_recipe(recipe)
            self.result=dict(discovery=found,recipe=recipe,issues=issues,info=info)
        self.app.runner.stage_name='LP360 file discovery';self.app.runner.start(work);self.root.after(100,self.poll)

    def show(self,recipe,issues,info):
        self.recipe=recipe
        self.reporting.restore(recipe.alignment_reporting)
        for key,var in self.vars.items():
            value=getattr(recipe,key);var.set('' if value is None else str(value))
        self.order.set(recipe.control_order);self.no_control.set(recipe.allow_no_control);self.recolor.set(recipe.colorize);self.align.set(recipe.align);self.shared.set(recipe.same_vertical);self.week.set('' if recipe.gps_week is None else str(recipe.gps_week));self.clock.set('Detected per file')
        for key in self.tree.get_children():self.tree.delete(key)
        data=[('LAS/LAZ',len(recipe.clouds),str(Path(recipe.clouds[0]).parent) if recipe.clouds else '', 'Selected' if recipe.clouds else 'Choose source folder'),('TRJ/SBET',len(recipe.trajectories),str(Path(recipe.trajectories[0]['path']).parent) if recipe.trajectories else '', 'Found' if recipe.trajectories else 'Missing / choose files'),('Control',1 if recipe.control else 0,recipe.control,'Found' if recipe.control else 'Missing / choose CSV'),('EO',1 if recipe.eo else 0,recipe.eo,'Optional recoloring' if recipe.eo else 'Missing; recoloring off')]
        for name,count,path,state in data:self.tree.insert('', 'end',text=name,values=(count,path,state))
        self.found.set(f"{info.get('points',0):,} points; units: {info.get('units','unknown')}. Detected control order: {info.get('control_order','auto')}. "+' '.join(self.discovery.warnings if self.discovery else []))
        self.status.set('Ready. Run LP360 job processes every stage and exports new final flight files.' if not issues else 'Needs input: '+' | '.join(i['message'] for i in issues))

    def choose_group(self,event=None):
        if self.busy() or not self.discovery:return
        recipe=suggest(self.discovery,self.group.get());issues,info=inspect_recipe(recipe);self.show(recipe,issues,info)

    def choose_clouds(self):
        if self.busy() or self.recipe is None:return
        p=filedialog.askopenfilenames(parent=self.window,title='Source LAS/LAZ',filetypes=(('LAS/LAZ','*.las *.laz'),))
        if p:self.recipe.clouds=[str(Path(v).resolve()) for v in p];self.status.set(f'{len(p)} source clouds selected. Check their trajectory settings before running.')

    def choose_tracks(self):
        if self.busy() or self.recipe is None:return
        p=filedialog.askopenfilenames(parent=self.window,title='TRJ/SBET trajectories',filetypes=(('TRJ/SBET','*.trj *.out'),))
        if p:self.recipe.trajectories=[dict(path=str(Path(v).resolve()),time_mode='week' if Path(v).suffix.lower()=='.out' else '',gps_week=None,confirmed=False) for v in p];self.status.set('Trajectories selected. Choose their time base before running.')

    def choose_control(self):self.choose_file('control','Control CSV','*.csv')
    def choose_file(self,key,title,pattern):
        if self.busy():return
        p=filedialog.askopenfilename(parent=self.window,title=title,filetypes=((title,pattern),))
        if p:self.vars[key].set(p)
    def choose_folder(self,key):
        if self.busy():return
        p=filedialog.askdirectory(parent=self.window)
        if p:self.vars[key].set(p)
    def choose_output(self):
        if self.busy():return
        p=filedialog.askdirectory(parent=self.window,title='Output parent (a new job folder will be created)')
        if p:self.output.set(p)

    def snapshot(self):
        if self.recipe is None:raise ValueError('Scan the project folder first.')
        values={}
        integer=('min_points','max_points','workers','quarter_turns','max_grid_cells')
        for key,var in self.vars.items():
            raw=var.get().strip()
            if key in integer:values[key]=int(raw)
            elif key in ('cell','slope','window','threshold','alignment_cell','contour_interval','memory_mb'):values[key]=float(raw)
            elif key in ('noise_min','noise_max'):values[key]=float(raw) if raw else None
            else:values[key]=raw
        values.update(control_order=self.order.get(),allow_no_control=self.no_control.get(),colorize=self.recolor.get(),align=self.align.get(),same_vertical=self.shared.get(),gps_week=int(self.week.get()) if self.week.get().strip() else None)
        trajectories=[dict(t) for t in self.recipe.trajectories]
        if self.clock.get()!='Detected per file':
            for t in trajectories:t['time_mode']='week' if Path(t['path']).suffix.lower()=='.out' else self.clock.get()
        values['alignment_reporting']=self.reporting.snapshot()
        values['trajectories']=trajectories
        return replace(self.recipe,**values)

    def start(self):
        if self.busy():return
        try:
            recipe=self.snapshot();parent=Path(self.output.get().strip())
            if not self.output.get().strip():raise ValueError('Choose the output parent.')
        except (ValueError,TypeError) as exc:self.status.set('Needs input: '+str(exc));return
        cleanup=getattr(self.layout,'cleanup',None)
        if cleanup is not None and not cleanup.close():return
        self.w.tracker.data['last_lp360_root']=recipe.root;self.w.persist()
        out=parent/('lp360_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
        self.output_run=out
        self.running=True;self.phase='run';self.result=None;self.run_button.configure(state='disabled');self.scan_button.configure(state='disabled');self.report_button.configure(state='disabled');self.status.set('Checking required files and settings…')
        def work(runner):
            issues,info=inspect_recipe(recipe)
            if issues:self.result=dict(status='Needs input',issues=issues,info=info);return
            from pyargus.lp360_workflow import run
            self.result=run(recipe,out,log=runner.log,cancel=runner.cancelled,on_stage=self.events.put)
            runner.report=str(out/'report.html')
        self.app.runner.stage_name='LP360 job';self.app.runner.start(work);self.root.after(100,self.poll)

    def poll(self):
        if self.window is None or not self.window.winfo_exists():return
        while not self.events.empty():
            item=self.events.get();self.status.set(item['stage']+' — '+item['status'])
        if self.app.runner.running:self.root.after(100,self.poll);return
        self.running=False;self.run_button.configure(state='normal');self.scan_button.configure(state='normal')
        if self.app.runner.error is not None:
            self.status.set('Stopped: '+str(self.app.runner.error)+'. Completed stages and the failure record are retained.')
            out=getattr(self,'output_run',None)
            if self.phase=='run' and out and (out/'report.html').is_file():self.result=dict(workspace=str(out/'project.argus.json'));self.report_button.configure(state='normal')
            return
        if self.phase=='scan' and self.result and self.result.get('status')=='Cancelled':self.status.set('Discovery stopped. Scan again when ready.');return
        if self.phase=='scan' and self.result:
            self.discovery=self.result['discovery'];self.group_choice.configure(values=list(self.discovery.cloud_groups));self.group.set(next(iter(self.discovery.cloud_groups)) if len(self.discovery.cloud_groups)==1 else '')
            self.show(self.result['recipe'],self.result['issues'],self.result['info'])
        elif self.result:
            if self.result['status']=='Needs input':self.status.set('Needs input: '+' | '.join(i['message'] for i in self.result['issues']));return
            self.status.set(self.result['status']+'. '+self.result.get('error','')+' Results: '+self.result['workspace']);self.report_button.configure(state='normal')
            if self.result['status'].startswith('Completed'):
                self.w.restore(self.result['workspace']);self.w.layout.set_mode('Review');self.w.layout.show_panel(self.w.progress_tab);self.w.stage_tree.selection_set('Delivery');self.w.history();self.w.viewer.mode.set('Classification')

    def open_report(self):
        if self.result and self.result.get('workspace'):
            import webbrowser
            webbrowser.open((Path(self.result['workspace']).parent/'report.html').as_uri())

    def close(self):
        if self.running:self.status.set('Use Stop; wait for the current operation to finish before closing this setup screen.');return False
        if self.window is not None:self.window.destroy();self.window=None
        return True
