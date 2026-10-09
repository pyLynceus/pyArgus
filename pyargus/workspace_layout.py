"""Desktop navigation shell; processing and data operations stay in their adapters."""
from pathlib import Path
import os
import tkinter as tk
from tkinter import ttk,messagebox


class WorkspaceLayout:
    def __init__(self,workspace):
        self.w=workspace;self.app=workspace.app;self.root=workspace.root;self.v=workspace.viewer
        self.mode='Review';self.switching=False;self.dialogs={};self.progress_key=None
        self.mode_docks={'Review':False,'Process':False,'Deliver':False};self.split_fraction=.48;self.split_pending=False
        workspace.review_panes.bind('<Configure>',lambda e:self.root.after_idle(self.ensure_split),add='+')
        workspace.review_panes.bind('<Map>',lambda e:self.root.after_idle(self.ensure_split),add='+')
        for pane in workspace.review_panes.panes():workspace.review_panes.nametowidget(pane).pack_propagate(False)
        workspace.command_bar.pack_forget();workspace.location_label.pack_forget();workspace.filter_bar.pack_forget()
        # Keep the standalone viewer's controls; replace only the embedded toolbar.
        for child in self.v.window.pack_slaves():
            if child is not self.v.canvas.master:child.pack_forget()
        self.nav=ttk.Notebook(self.root,height=1)
        self.pages={name:ttk.Frame(self.nav) for name in ('Review','Process','Deliver')}
        for name,page in self.pages.items():self.nav.add(page,text=name)
        self.nav.pack(side='top',fill='x',before=self.app.task_panel)
        self.nav.bind('<<NotebookTabChanged>>',self.tab_changed)
        self.statusbar=ttk.Frame(self.root)
        self.statusbar.pack(side='bottom',fill='x',before=self.app.task_panel)
        ttk.Label(self.statusbar,textvariable=self.app.job_status,width=40).pack(side='left',padx=6)
        ttk.Label(self.statusbar,textvariable=self.v.render_note,width=38,anchor='w').pack(side='left',padx=4)
        ttk.Label(self.statusbar,textvariable=self.v.status,width=1,anchor='w').pack(side='left',fill='x',expand=True)
        self.stop_job=ttk.Button(self.statusbar,text='Stop job',command=self.app.runner.cancel,state='disabled');self.stop_job.pack(side='right')
        ttk.Button(self.statusbar,text='Jobs / log',command=lambda:self.show_panel(workspace.progress_tab)).pack(side='right')
        from pyargus.section_interaction import CorridorEditor
        self.corridor=CorridorEditor(workspace)
        self.preset=tk.StringVar(value='Custom');self.applying_layout=False
        handles=workspace.review.primary_controls
        ttk.Checkbutton(handles,text='Edit corridor',variable=self.corridor.enabled,command=self.corridor.toggle).pack(side='left',padx=6)
        ttk.Checkbutton(handles,text='Extract on release',variable=self.corridor.auto_extract).pack(side='left')
        self.deliver=ttk.Frame(self.root,padding=10,width=350)
        self.build_delivery();self.build_toolbar();self.build_menus();self.build_sidebar()
        workspace.tabs.tab(workspace.review_tab,text='Cross-section')
        workspace.tabs.tab(workspace.progress_tab,text='Job history')
        for index,frame in enumerate((workspace.review_tab,workspace.qa_tab,workspace.features_tab,workspace.progress_tab,workspace.log_tab,workspace.project_tab)):
            workspace.tabs.insert(index,frame)
        workspace.tabs.select(workspace.review_tab)
        workspace.tabs.bind('<<NotebookTabChanged>>',self.dock_changed,add='+')
        # Imported layer settings and optional tracing use a menu, not nested tabs.
        ttk.Style(self.root).layout('Flat.TNotebook.Tab',[])
        workspace.linework_tabs.configure(style='Flat.TNotebook')
        tools=ttk.Frame(workspace.features_tab);tools.pack(fill='x',before=workspace.linework_tabs)
        menu=self.dropdown(tools,'Linework tools')
        menu.add_command(label='Imported layer settings',command=lambda:workspace.linework_tabs.select(workspace.imported_tab))
        menu.add_command(label='Edit / trace features',command=lambda:workspace.linework_tabs.select(workspace.edit_tab))
        self.linework_selection=tk.StringVar(value='Select a DXF layer in Layers to change its style or follow it.')
        ttk.Label(tools,textvariable=self.linework_selection).pack(side='left',padx=8)
        workspace.linework.tree.pack_forget()
        for child in workspace.linework.tree.master.winfo_children():
            if isinstance(child,ttk.Frame):
                for button in child.winfo_children():
                    if isinstance(button,ttk.Button) and button.cget('text')=='Import DXF…':button.pack_forget()
        from pyargus.review_shortcuts import ReviewShortcuts
        self.shortcuts=ReviewShortcuts(self)
        from pyargus.review_memory_gui import ReviewNotes
        self.notes=ReviewNotes(self);self.w.notes=self.notes
        from pyargus.project_overview_gui import ProjectOverview
        self.overview=ProjectOverview(self);self.w.overview=self.overview
        from pyargus.version_comparison_gui import VersionComparison
        self.comparison=VersionComparison(self);self.w.comparison=self.comparison
        from pyargus.review_package_gui import ReviewPackageExport
        self.package_export=ReviewPackageExport(self);self.w.package_export=self.package_export
        self.w.review.on_details=self.section_options
        workspace.show_dock.set(False);self.set_mode('Review');self.update()

    def dropdown(self,parent,label):
        button=ttk.Menubutton(parent,text=label+' ▾');button.pack(side='left',padx=2)
        menu=tk.Menu(button,tearoff=False);button.configure(menu=menu);return menu

    def build_toolbar(self):
        w=self.w;v=self.v
        toolbar=ttk.Frame(v.window);toolbar.pack(fill='x',before=v.canvas.master,pady=3)
        bar=ttk.Frame(toolbar);bar.pack(side='left')
        extras=ttk.Frame(toolbar);extras.pack(side='left')
        self.toolbar=toolbar;self.toolbar_rows=(bar,extras)
        toolbar.bind('<Configure>',self.wrap_toolbar)
        self.view_menu=self.dropdown(bar,'View')
        for name,angles in [('Top',(0,90)),('Front',(0,0)),('Side',(90,0)),('Oblique',(25,45))]:
            self.view_menu.add_command(label=name,command=lambda a=angles:v.view(*a))
        self.view_menu.add_separator();self.view_menu.add_command(label='Set orbit center',command=v.arm_pivot)
        self.view_menu.add_command(label='Fit selected clouds',command=v.fit_selected)
        self.layouts_menu=self.dropdown(bar,'Layout')
        for name in ('Full 3D','3D + Profile','Comparison review'):
            self.layouts_menu.add_radiobutton(label=name,variable=self.preset,value=name,command=lambda n=name:self.apply_preset(n))
        ttk.Label(bar,text='Color:').pack(side='left',padx=(6,0))
        color=ttk.Combobox(bar,textvariable=v.mode,values=('Dataset','Flight line','Elevation','Classification'),state='readonly',width=14)
        color.pack(side='left');color.bind('<<ComboboxSelected>>',lambda e:v.draw())
        for label,fn in [('Fit',v.fit),('Previous view',v.previous_view)]:ttk.Button(bar,text=label,command=fn).pack(side='left',padx=2)
        ttk.Checkbutton(extras,text='Auto detail',variable=v.auto_detail,command=v.reset_auto).pack(side='left',padx=4)
        self.renderer_menu=self.dropdown(extras,'Renderer')
        for backend in ('Auto','GPU','CPU'):
            self.renderer_menu.add_radiobutton(label=backend,variable=v.renderer,value=backend,command=v.change_renderer)
        self.stereo_menu=self.dropdown(extras,'Stereo')
        self.stereo_menu.add_checkbutton(label='Anaglyph enabled',variable=v.stereo,command=v.draw)
        self.stereo_menu.add_checkbutton(label='Swap eyes',variable=v.stereo_swap,command=v.draw)
        self.stereo_menu.add_command(label='Depth settings…',command=self.stereo_settings)
        self.sections_menu=self.dropdown(extras,'Sections')
        self.sections_menu.add_checkbutton(label='Edit corridor handles (Top view)',variable=self.corridor.enabled,command=self.corridor.toggle)
        self.sections_menu.add_checkbutton(label='Extract on release',variable=self.corridor.auto_extract)
        self.sections_menu.add_separator()
        for label,fn in [('Draw A/B section',self.draw_section),('Follow imported line…',self.follow_line),
                         ('Previous along route',lambda:self.route_step(-1)),('Next along route',lambda:self.route_step(1)),
                         ('Section controls',w.show_section_review),('Hide review pane',self.hide_dock)]:
            self.sections_menu.add_command(label=label,command=fn)
        menu=self.dropdown(extras,'More')
        for label,fn in [('Cloud filters…',self.filters),('Refine current view',v.refine),('Build view cache',v.build_view_cache),
                         ('Reset detail',lambda:v.load(v.paths) if v.paths else None),('Stop loading',v.stop_loading)]:
            menu.add_command(label=label,command=fn)
        ttk.Checkbutton(extras,text='Review pane',variable=w.show_dock,command=self.apply_dock).pack(side='right')

    def wrap_toolbar(self,event=None):
        rows=self.toolbar_rows
        narrow=self.toolbar.winfo_width()<sum(row.winfo_reqwidth() for row in rows)
        if narrow==getattr(self,"toolbar_narrow",None):return
        self.toolbar_narrow=narrow
        for row in rows:
            row.pack_forget();row.pack(side="top" if narrow else "left",anchor="w")

    def build_menus(self):
        w=self.w;v=self.v
        self.menubar=tk.Menu(self.root);self.root.configure(menu=self.menubar)
        self.menus={}
        for name in ('File','View','Tools','Help'):
            menu=tk.Menu(self.menubar,tearoff=False);self.menubar.add_cascade(label=name,menu=menu);self.menus[name]=menu
        file=self.menus['File']
        for label,fn in [('Open workspace…',w.open),('Save workspace',w.persist),('Save workspace as…',w.save_as),('Resume last workspace',w.resume)]:file.add_command(label=label,command=fn)
        self.add_menu=tk.Menu(file,tearoff=False);file.add_cascade(label='Add data',menu=self.add_menu);self.add_commands(self.add_menu)
        file.add_separator()
        file.add_command(label='Load analysis project…',command=w.load_analysis_project)
        file.add_command(label='Save analysis project…',command=w.project_panel.save_project)
        file.add_command(label='Exit',command=self.app._confirm_close)
        view=self.menus['View'];view.add_cascade(label='Orientation',menu=self.view_menu)
        view.add_cascade(label='Renderer',menu=self.renderer_menu)
        view.add_cascade(label='Stereo',menu=self.stereo_menu)
        view.add_cascade(label='Layout presets',menu=self.layouts_menu)
        for label,fn in [('Fit cloud',v.fit),('Previous view',v.previous_view),('Cloud filters…',self.filters),('Refine current view',v.refine),('Build view cache',v.build_view_cache)]:view.add_command(label=label,command=fn)
        view.add_checkbutton(label='Automatic local detail',variable=v.auto_detail,command=v.reset_auto)
        view.add_checkbutton(label='Review pane',variable=w.show_dock,command=self.apply_dock)
        view.add_command(label='Linework settings',command=self.linework_settings)
        view.add_command(label='Job history',command=lambda:self.show_panel(w.progress_tab))
        tools=self.menus['Tools'];tasks=tk.Menu(tools,tearoff=False);tools.add_cascade(label='Processing tasks',menu=tasks)
        for name in ('Inspect / match',*[s.title for s in self.app.stages]):tasks.add_command(label=name,command=lambda n=name:self.select_task(n))
        tools.add_command(label='Project / trajectory settings',command=self.project_settings)
        tools.add_cascade(label='Cross-sections',menu=self.sections_menu)
        tools.add_command(label='Open QA / alignment report…',command=w.review.choose_record)
        tools.add_command(label='Optional feature tracing',command=self.tracing)
        tools.add_command(label='Open pyLynceus',command=self.app.open_pylynceus)
        self.menus['Help'].add_command(label='Viewing controls',command=lambda:messagebox.showinfo('Viewing controls',
            'Left drag: orbit\nRight drag: pan\nWheel: zoom at cursor\nDouble-click: fit\nShift-click: inspect a point (normal view)\nCtrl-click A/B: section in Top view\nSections > Edit corridor: drag A/B, W width, R rotation, or inside to move. Escape cancels.\nLayout: Full 3D, 3D + Profile, Comparison review\nAlt+Left/Right: step along selected route while reviewing sections\n\nBuild view cache before enabling Auto detail.\nThe display is a sample; measurements and exports retain their existing limits.',parent=self.root))
        self.menus['Help'].add_command(label='About this build',command=self.about)

    def add_commands(self,menu):
        w=self.w
        for label,fn in [('Clouds / trajectories…',w.add_files),('Cloud / trajectory folder…',w.add_folder),
                         ('Reference linework (DXF)…',lambda:w.linework.run(w.linework.choose)),
                         ('Control points (CSV)…',w.add_control),('Terrain breaklines…',w.add_breaklines),
                         ('Existing output…',w.import_output),('Job record…',w.import_record)]:menu.add_command(label=label,command=fn)

    def build_sidebar(self):
        w=self.w
        w.layer_tools.pack_forget()
        tools=ttk.Frame(w.sidebar);tools.pack(fill='x',before=w.layer_summary,pady=4)
        menu=self.dropdown(tools,'Add data');self.add_commands(menu)
        ttk.Button(tools,text='Settings',command=self.project_settings).pack(side='left')
        frame=ttk.LabelFrame(w.sidebar,text='Project progress',padding=4);frame.pack(fill='x',before=w.layer_help,pady=5)
        self.progress=ttk.Treeview(frame,columns=('status',),show='tree headings',height=6,selectmode='browse')
        self.progress.heading('#0',text='Stage');self.progress.column('#0',width=100,minwidth=70)
        self.progress.heading('status',text='Status');self.progress.column('status',width=115,minwidth=90)
        self.progress.pack(fill='x');self.progress.bind('<<TreeviewSelect>>',self.choose_progress)
        self.progress_help=ttk.Label(frame,text='Click a stage for history and review.',wraplength=240);self.progress_help.pack(anchor='w')
        w.layer_note_label.configure(wraplength=250)

    def choose_progress(self,event=None):
        selected=self.progress.selection()
        if selected and self.w.stage_tree.exists(selected[0]):
            self.w.stage_tree.selection_set(selected[0]);self.w.history();self.show_panel(self.w.progress_tab)

    def build_delivery(self):
        ttk.Label(self.deliver,text='Deliver',font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(self.deliver,text='Existing outputs and exports. Processing creates clouds and surfaces.',wraplength=330).pack(fill='x',pady=6)
        self.outputs=ttk.Treeview(self.deliver,columns=('kind',),show='tree headings',height=8,selectmode='browse')
        self.outputs.heading('#0',text='Output');self.outputs.column('#0',width=215)
        self.outputs.heading('kind',text='Type');self.outputs.column('kind',width=70)
        self.outputs.pack(fill='x',pady=4)
        ttk.Button(self.deliver,text='Open selected output folder',command=self.open_output_folder).pack(fill='x')
        self.export_choice=tk.StringVar(value='Section sample CSV')
        ttk.Label(self.deliver,text='Export action').pack(anchor='w',pady=(15,2))
        ttk.Combobox(self.deliver,textvariable=self.export_choice,state='readonly',values=('Section sample CSV','Traced linework DXF','Record selected deliverables')).pack(fill='x')
        ttk.Button(self.deliver,text='Continue…',command=self.export).pack(fill='x',pady=6)
        ttk.Label(self.deliver,text='CSV exports the current section sample. DXF uses the feature review/export rules. Recording deliverables does not copy or approve files.',wraplength=330).pack(fill='x')

    def export(self):
        action=self.export_choice.get()
        if action=='Section sample CSV':self.w.review.export()
        elif action=='Traced linework DXF':self.w.features.run(self.w.features.export)
        elif action=='QA review package':self.package_export.run(self.package_export.choose)
        else:
            if not self.w.selected_layers():messagebox.showinfo('Deliver','Select project files in Layers first.',parent=self.root);return
            self.w.delivery()

    def open_output_folder(self):
        chosen=self.outputs.selection()
        if not chosen:return
        path=Path(self.output_paths[chosen[0]])
        if not path.exists():messagebox.showerror('Output','Output is missing: '+str(path),parent=self.root);return
        os.startfile(str(path if path.is_dir() else path.parent))

    def tab_changed(self,event=None):
        name=next((name for name,page in self.pages.items() if str(page)==self.nav.select()),None)
        if name and name!=self.mode:self.set_mode(name)

    def set_mode(self,name):
        if name not in self.pages:name='Review'
        if name!=self.mode:
            if hasattr(self,'notes'):self.notes.disarm()
            self.corridor.cancel()
            if not self.applying_layout:self.preset.set('Custom')
            self.mode_docks[self.mode]=self.w.show_dock.get();self.w.show_dock.set(self.mode_docks[name])
            self.w.features.mode.set('Inspect')
        self.mode=name;self.w.review_mode.set(name=='Review')
        self.nav.select(self.pages[name]);self.app.task_panel.pack_forget();self.deliver.pack_forget()
        if name=='Process':
            self.app.task_panel.pack(side='right',fill='y',before=self.w.workspace_host)
            self.w.tabs.tab(self.w.project_tab,state='normal')
        else:
            self.w.tabs.hide(self.w.project_tab)
            if name=='Deliver':self.deliver.pack(side='right',fill='y',before=self.w.workspace_host)
        self.apply_dock();self.update()

    def apply_dock(self):
        self.corridor.cancel()
        if not self.applying_layout:self.preset.set('Custom')
        w=self.w;visible=str(w.review_bottom) in w.review_panes.panes()
        if w.show_dock.get() and not visible:
            w.review_panes.add(w.review_bottom,weight=1)
            self.request_split(.48)
        elif not w.show_dock.get() and visible:w.review_panes.forget(w.review_bottom)

    def section_options(self,opened):
        panes=self.w.review_panes
        if len(panes.panes())<2:return
        if opened:
            self.before_options_split=panes.sashpos(0)/max(1,panes.winfo_height())
            self.request_split(.25)
        else:self.request_split(getattr(self,'before_options_split',.38))

    def request_split(self,fraction):
        self.split_fraction=fraction;self.split_pending=True
        self.root.after_idle(self.ensure_split);self.root.after(250,self.ensure_split)

    def ensure_split(self):
        panes=self.w.review_panes
        if self.w.closed or len(panes.panes())<2 or not panes.winfo_ismapped() or panes.winfo_height()<250:return
        height=panes.winfo_height();position=panes.sashpos(0)
        if self.split_pending or position<100 or position>height-100:
            panes.sashpos(0,int(height*self.split_fraction));self.split_pending=False

    def split(self,fraction):
        self.request_split(fraction)

    def hide_dock(self):self.w.show_dock.set(False);self.apply_dock()

    def show_panel(self,panel):
        if panel is self.w.project_tab:self.set_mode('Process')
        self.w.show_dock.set(True);self.apply_dock();self.w.tabs.select(panel)

    def dock_changed(self,event=None):
        if self.w.tabs.select()!=str(self.w.review_tab):self.corridor.cancel()
        # Legacy adapters selecting a page must also reveal a collapsed drawer.
        if self.w.tabs.select()==str(self.w.project_tab):self.set_mode('Process')

    def project_settings(self):self.show_panel(self.w.project_tab)
    def select_task(self,name):self.set_mode('Process');self.app.task_name.set(name);self.w.select_task()
    def draw_section(self):
        self.w.show_section_review();self.w.review.route.stop();self.v.stereo.set(False);self.v.view(0,90)
        self.w.review.status.set('Ctrl-click A then B in the cloud, then Extract section.')
    def follow_line(self):self.w.show_section_review();self.w.review.route.run(self.w.review.route.choose)
    def route_step(self,direction):self.w.show_section_review();self.w.review.route.run(lambda:self.w.review.route.go(direction))
    def linework_settings(self):
        self.show_panel(self.w.features_tab);self.w.linework_tabs.select(self.w.imported_tab)

    def tracing(self):self.set_mode('Review');self.show_panel(self.w.features_tab);self.w.linework_tabs.select(self.w.edit_tab)

    def dialog(self,key,title):
        old=self.dialogs.get(key)
        if old is not None and old.winfo_exists():old.lift();return None
        win=tk.Toplevel(self.root);win.title(title);win.transient(self.root);self.dialogs[key]=win
        return win

    def stereo_settings(self):
        win=self.dialog('stereo','Stereo settings')
        if win is None:return
        ttk.Checkbutton(win,text='Enable red/cyan anaglyph',variable=self.v.stereo,command=self.v.draw).pack(anchor='w',padx=15,pady=8)
        ttk.Label(win,text='Depth (0–6 degrees)').pack(anchor='w',padx=15)
        ttk.Scale(win,from_=0,to=6,variable=self.v.stereo_depth,command=lambda x:self.v.schedule(),length=280).pack(padx=15,pady=5)
        ttk.Checkbutton(win,text='Swap eyes',variable=self.v.stereo_swap,command=self.v.draw).pack(anchor='w',padx=15)
        ttk.Button(win,text='Close',command=win.destroy).pack(pady=10)

    def filters(self):
        win=self.dialog('filters','Cloud display filters')
        if win is None:return
        for label,var in [('Class group or numbers (e.g. 2,3,4)',self.w.class_filter),('LAS line (All or number)',self.w.line_filter)]:
            ttk.Label(win,text=label).pack(anchor='w',padx=15,pady=(8,0));ttk.Entry(win,textvariable=var).pack(fill='x',padx=15)
        ttk.Button(win,text='Apply',command=self.w.filter).pack(pady=10)
        ttk.Label(win,text='Display only; processing inputs are unchanged.').pack(padx=15,pady=8)

    def about(self):
        import sys,json
        detail='Source checkout'
        if getattr(sys,'frozen',False):
            try:detail='Source '+json.loads((Path(sys.executable).parent/'build-info.json').read_text(encoding='utf-8-sig'))['source_commit']
            except (OSError,KeyError,ValueError):detail='Packaged application'
        messagebox.showinfo('pyArgus','pyArgus — lidar review and processing\n'+detail+'\n\nReview / Process / Deliver workspace',parent=self.root)

    def update(self):
        if hasattr(self,'shortcuts'):self.shortcuts.update()
        self.ensure_split()
        self.stop_job.configure(state="normal" if self.app.runner.running else "disabled")
        key=tuple((s,self.w.stage_tree.item(s,'values')) for s in self.w.stage_tree.get_children())
        if key!=self.progress_key:
            self.progress_key=key;self.progress.delete(*self.progress.get_children())
            for stage,values in key:self.progress.insert('','end',iid=stage,text=stage,values=(values[0],))
        paths=[l for l in self.w.tracker.data['layers'] if l['kind'] in ('output','Corrected','surface')]
        key=tuple((l['path'],l['kind']) for l in paths)
        if key!=getattr(self,'output_key',None):
            self.output_key=key;self.outputs.delete(*self.outputs.get_children());self.output_paths={}
            for i,(path,kind) in enumerate(key):
                self.outputs.insert('','end',iid=str(i),text=Path(path).name,values=(kind,));self.output_paths[str(i)]=path

    def apply_preset(self,name):
        if name not in ('Full 3D','3D + Profile','Comparison review'):return
        self.applying_layout=True
        try:
            self.corridor.cancel();self.set_mode('Review')
            self.w.review.details_visible.set(False);self.w.review.toggle_details()
            self.w.show_dock.set(name!='Full 3D');self.apply_dock()
            self.w.tabs.select(self.w.review_tab)
            self.request_split(.42 if name=='Comparison review' else .5)
            if name=='Comparison review':
                self.v.mode.set('Dataset');self.w.review.mode.set('Dataset');self.w.review.redraw();self.v.draw()
            self.preset.set(name)
        finally:self.applying_layout=False

    def snapshot(self):
        tab=self.w.tabs.select();fraction=self.split_fraction
        panes=self.w.review_panes
        if not self.split_pending and len(panes.panes())==2 and panes.winfo_height()>250:
            fraction=panes.sashpos(0)/panes.winfo_height()
        return dict(mode=self.mode,dock=self.w.show_dock.get(),pane=self.w.tabs.tab(tab,'text') if tab else 'Cross-section',
                    preset=self.preset.get(),split_fraction=fraction,extract_on_release=self.corridor.auto_extract.get())

    def restore(self,state):
        import math
        self.applying_layout=True
        try:
            self.corridor.cancel();self.corridor.enabled.set(False);self.v.canvas.configure(cursor='')
            self.corridor.auto_extract.set(bool(state.get('extract_on_release',False)))
            self.set_mode(state.get('mode','Review'));self.w.show_dock.set(bool(state.get('dock',False)));self.apply_dock()
            for tab in self.w.tabs.tabs():
                if self.w.tabs.tab(tab,'text')==state.get('pane') and self.w.tabs.tab(tab,'state')!='hidden':self.w.tabs.select(tab);break
            name=state.get('preset','Custom')
            self.preset.set(name if name in ('Full 3D','3D + Profile','Comparison review') else 'Custom')
            try:fraction=float(state.get('split_fraction',.48))
            except (TypeError,ValueError):fraction=.48
            self.request_split(fraction if math.isfinite(fraction) and .15<=fraction<=.85 else .48)
        finally:self.applying_layout=False
