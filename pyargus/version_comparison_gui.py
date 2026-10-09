"""One-time pair preparation and instantaneous display-only A/B review."""
from copy import deepcopy
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
import numpy as np

from pyargus.version_comparison import (preferences,recorded_pair,inspect_pair,
    check_sources,role_visibility,section_matches)
from pyargus.job_manifest import identity


class VersionComparison:
    def __init__(self,layout):
        self.layout=layout;self.w=layout.w;self.v=layout.v;self.r=self.w.review
        self.original=tk.StringVar();self.result=tk.StringVar();self.confirmed=tk.BooleanVar(value=False)
        self.role=tk.StringVar(value='Result');self.info=None;self.pending=None;self.previous=None;self.profile=None;self.profile_pending=False
        self.notice=tk.StringVar(value='Prepare an Original/Result pair once, then switch without rescanning. Processing inputs stay unchanged.')
        self.label=tk.StringVar(value='No comparison prepared');self.path_key=None
        self.frame=ttk.Frame(self.w.tabs,padding=8);self.w.tabs.insert(self.w.review_tab,self.frame,text='Version comparison')
        for title,var in [('Original',self.original),('Result',self.result)]:
            row=ttk.Frame(self.frame);row.pack(fill='x',pady=4)
            ttk.Label(row,text=title,width=10).pack(side='left')
            choice=ttk.Combobox(row,textvariable=var,state='readonly',width=80);choice.pack(side='left',fill='x',expand=True)
            choice.bind('<<ComboboxSelected>>',lambda e:self.changed_pair())
            setattr(self,title.lower()+'_choice',choice)
            ttk.Button(row,text='Browse…',command=lambda v=var:self.browse(v)).pack(side='left',padx=4)
        row=ttk.Frame(self.frame);row.pack(fill='x',pady=4)
        ttk.Button(row,text='Use recorded lineage',command=lambda:self.run(self.use_recorded)).pack(side='left')
        ttk.Checkbutton(row,text='I confirm common XYZ units and vertical datum',variable=self.confirmed).pack(side='left',padx=8)
        row=ttk.Frame(self.frame);row.pack(fill='x',pady=4)
        for text,fn in [('Prepare comparison',self.prepare),('Original',lambda:self.switch('Original')),
                        ('Result',lambda:self.switch('Result')),('Both',lambda:self.switch('Both')),
                        ('Swap A/B · F6',self.swap),('Restore previous display',self.restore_previous)]:
            ttk.Button(row,text=text,command=lambda f=fn:self.run(f)).pack(side='left',padx=2)
        ttk.Label(self.frame,textvariable=self.label,font=('Segoe UI',10,'bold'),wraplength=1000).pack(fill='x',pady=6)
        ttk.Label(self.frame,textvariable=self.notice,wraplength=1000).pack(fill='x',pady=4)
        row=ttk.Frame(self.frame);row.pack(fill='x',pady=5)
        ttk.Button(row,text='Extract comparison section',command=lambda:self.run(self.extract)).pack(side='left')
        ttk.Button(row,text='Show cross-section',command=self.w.show_section_review).pack(side='left',padx=4)
        ttk.Label(self.frame,text='Preparation may scan the two files once. Switching only changes visibility. Manual pairs carry no inferred provenance.\nA paired section is extracted explicitly; later A/B switches reuse its sample with a common profile scale. Section editing still requires a complete single-cloud section.',wraplength=1000).pack(fill='x',pady=8)
        self.menu=layout.dropdown(layout.toolbar_rows[1],'Compare');self.menu.master.configure(width=20)
        for title,fn in [('Prepare / choose pair…',self.show),('Original',lambda:self.switch('Original')),
                         ('Result',lambda:self.switch('Result')),('Both',lambda:self.switch('Both')),
                         ('Swap A/B',self.swap),('Extract comparison section',self.extract),('Restore previous display',self.restore_previous)]:
            self.menu.add_command(label=title,command=lambda f=fn:self.run(f))
        layout.menus['View'].add_cascade(label='Original / result comparison',menu=self.menu)
        layout.root.bind('<F6>',self.key,add='+')
        self.refresh_choices()

    def busy(self):return self.v.busy or self.r.busy or self.w.app.runner.running or self.w.notes.pending is not None or self.pending is not None

    def run(self,fn):
        try:fn()
        except (ValueError,OSError,KeyError,TypeError) as exc:self.notice.set(str(exc));self.v.status.set(str(exc))

    def show(self):self.layout.show_panel(self.frame)

    def browse(self,var):
        if self.busy():return
        name=filedialog.askopenfilename(parent=self.layout.root,filetypes=(('Point clouds','*.las *.laz'),))
        if name:var.set(str(Path(name).resolve()));self.changed_pair();self.refresh_choices(force=True)

    def changed_pair(self):
        if self.pending:
            self.original.set(self.pending['original']);self.result.set(self.pending['result']);return
        self.info=None;self.profile=None;self.confirmed.set(False);self.label.set('Pair changed — prepare it before switching.')
        self.menu.master.configure(text='Compare ▾')

    def refresh_choices(self,force=False):
        paths=list(dict.fromkeys([*[l['path'] for l in self.w.tracker.data['layers'] if Path(l['path']).suffix.lower() in ('.las','.laz')],
            *self.w.tracker.data.get('cloud_versions',{}),*self.v.paths,*[p for p in (self.original.get(),self.result.get()) if p]]))
        key=tuple(paths)
        if key==self.path_key and not force:return
        self.path_key=key
        for choice in (self.original_choice,self.result_choice):choice.configure(values=paths)
        if not self.original.get() and not self.result.get():
            try:pair=recorded_pair(self.w.tracker,self.w.app.cloud_path.get() or (self.v.paths[0] if self.v.paths else ''))
            except (ValueError,OSError):pair=None
            if pair:self.original.set(pair[0]);self.result.set(pair[1])

    def use_recorded(self):
        if self.busy():raise ValueError('Finish the current load/job first.')
        selected=self.w.selected_layers();anchor=selected[0]['path'] if len(selected)==1 else self.w.app.cloud_path.get()
        pair=recorded_pair(self.w.tracker,anchor)
        if pair is None:raise ValueError('No recorded descendant for this cloud. Choose a manual pair explicitly; filenames are not used to infer lineage.')
        self.original.set(pair[0]);self.result.set(pair[1]);self.changed_pair();self.refresh_choices(force=True)

    def overlays(self):
        flags=[*[var for _,var in self.v.tracks],*[var for _,_,var in self.v.extra_layers],*[var for _,var in self.v.extra_points]]
        return dict(tracks=list(self.v.tracks),track_paths=list(self.v.track_paths),layers=list(self.v.extra_layers),points=list(self.v.extra_points),
            flags=[(var,var.get()) for var in flags],registered=dict(self.w.overlay_vars))

    def capture_previous(self,state):
        return dict(state=deepcopy(state),scene=self.v.scene,overview=self.v.overview_scene,
            overlays=self.overlays(),section=self.r.section,profile=self.plot_state(),confirmed=self.r.confirm.get())

    def plot_state(self):
        p=self.r.profile
        return dict(center=p.center.copy(),span=p.span.copy(),zoom=p.zoom,pan=p.pan.copy())

    def apply_plot(self,state):
        if state:
            p=self.r.profile
            for k in ('center','span','pan'):setattr(p,k,state[k].copy())
            p.zoom=state['zoom'];p.draw()

    def prepare(self):
        if self.busy() or self.w.pending_view or getattr(self.w,'pending_version_view',False):raise ValueError('Finish the current load/job first.')
        state=self.w.notes.capture_view();original=self.original.get();result=self.result.get();confirmed=self.confirmed.get()
        if not original or not result:raise ValueError('Choose both Original and Result.')
        if not confirmed:raise ValueError('Confirm common XYZ units and vertical datum before comparing.')
        previous=self.capture_previous(state);tracker=deepcopy(self.w.tracker);expected=self.v.scene[5]
        self.info=None;self.profile=None;self.w.notes.disarm();self.v.cancel_corridor_drag()
        self.v.auto_detail.set(False);self.v.reset_auto()
        pending=dict(state=state,previous=previous,info=None,original=original,result=result);self.pending=pending
        self.notice.set('Preparing comparison. Reading the pair once; camera and section location are retained.')
        def work():
            from pyargus.viewer3d import sample_clouds
            info=inspect_pair(tracker,original,result,confirmed,expected)
            paths=tuple(s['path'] for s in info['inputs'])
            if tuple(self.v.paths)==paths and self.r.loaded_identities==info['inputs']:
                scene=self.v.scene
            else:scene=sample_clouds(paths,cancel=self.v.cancel,progress=lambda s:self.v.messages.put(('progress',s)))
            check_sources(info)
            if [identity(s['path']) for s in state['inputs']]!=state['inputs']:raise ValueError('Prior view source changed during comparison preparation.')
            pending['info']=info
            return ('review-cloud',paths,scene,state['camera'])
        self.v.launch(work)

    def ready(self):
        if self.busy():raise ValueError('Finish loading, extraction or processing before switching.')
        if self.info is None:
            raise ValueError('Prepare comparison first. Reopened workspaces retain the pair settings; preparation validates the loaded sources.')
        paths=tuple(s['path'] for s in self.info['inputs'])
        if tuple(self.v.paths)!=paths or self.r.loaded_identities!=self.info['inputs']:
            raise ValueError('Loaded clouds changed; prepare comparison again.')
        if self.original.get()!=self.info['original'] or self.result.get()!=self.info['result'] or not self.confirmed.get():
            raise ValueError('Comparison settings changed; prepare the pair again.')
        check_sources(self.info)

    def switch(self,role):
        self.ready();self.apply_role(role);self.w.persist()

    def apply_role(self,role):
        shown=role_visibility(role);self.role.set(role)
        for var,value in zip(self.v.visible,shown):var.set(value)
        self.r.filelist.selection_clear(0,'end')
        for i,value in enumerate(shown):
            if value:self.r.filelist.selection_set(i)
        self.r.section_source.set(self.info['original'] if role=='Original' else self.info['result'] if role=='Result' else 'Compare all loaded clouds')
        plot=self.plot_state()
        self.r.redraw()
        if self.profile is not None and section_matches(self.r.section,self.info,self.v.corridor):self.apply_plot(plot)
        self.v.draw();self.w.refresh_layers();self.menu.master.configure(text='Compare: '+role+' ▾')
        self.label.set(f'{role} · {self.info["provenance"]}\nOriginal: {self.info["original"]}\nResult: {self.info["result"]}')
        paired=section_matches(self.r.section,self.info,self.v.corridor)
        if paired:self.profile_status(role)
        self.notice.set('Display switched; processing inputs are unchanged. '+('Paired profile reuses the extracted sample.' if paired else 'Extract comparison section for a profile that switches with the cloud.'))
        pts,classes,lines,files,*_=self.v.scene
        visible=np.array(shown,dtype=bool)[files]
        if self.v.class_filter is not None:visible &= np.isin(classes,self.v.class_filter)
        if self.v.line_filter is not None:visible &= lines==self.v.line_filter
        if not visible.any():self.notice.set(self.notice.get()+' This version has no sampled points under the current class/line filters.')
        if self.r.section is not None and not paired:
            self.r.clear_section();self.profile=None
            self.r.status.set('Previous single-cloud profile cleared; Extract comparison section preserves this location and samples both files.')

    def profile_status(self,role):
        sec=self.r.section
        self.r.status.set(f'Comparison section: {sec.matched:,} corridor returns; {len(sec.points):,} sampled across Original and Result. Display: {role}. Counts precede display filters.')

    def swap(self):
        current=[v.get() for v in self.v.visible]
        self.switch('Original' if current==[False,True] else 'Result')

    def key(self,event):
        if self.layout.mode!='Review':return
        if self.layout.root.focus_get() is not None and self.layout.root.focus_get().winfo_class() in ('Entry','TEntry','Text','TCombobox','Spinbox','TSpinbox'):return
        self.run(self.swap);return 'break'

    def extract(self):
        self.ready()
        if self.v.corridor is None:raise ValueError('Define an A/B section at the location to compare first.')
        self.r.confirm.set(self.confirmed.get());self.r.section_source.set('Compare all loaded clouds')
        self.r.extract();self.profile_pending=self.r.busy
        self.notice.set('Extracting the comparison section explicitly. Stop loading remains available.' if self.profile_pending else self.r.status.get())

    def restore_context(self,state,overlays):
        self.v.tracks=overlays['tracks'];self.v.track_paths=overlays['track_paths'];self.v.extra_layers=overlays['layers'];self.v.extra_points=overlays['points']
        for var,value in overlays['flags']:var.set(value)
        self.w.overlay_vars.update(overlays['registered'])
        self.r.route.restore(state['route']);self.r.confirm.set(state['confirmed'])
        for var,val in zip(self.r.coords,state['section']['start']+state['section']['end'] if state['section'] else ['']*4):var.set(str(val))
        if state['section']:
            self.r.width.set(str(state['section']['width']));self.r.set_corridor()
        else:self.v.corridor=None
        self.r.mode.set(state['profile']['mode']);self.r.line.set(state['profile']['line']);self.r.exaggeration.set(str(state['profile']['exaggeration']))
        self.r.endpoint=None

    def restore_previous(self):
        if self.busy():raise ValueError('Finish the current load/job first.')
        if self.previous is None:raise ValueError('No previous display is retained in this session.')
        prev=self.previous;state=self.w.notes.verify(prev['state'])
        paths=tuple(s['path'] for s in state['inputs'])
        self.w.notes.disarm();self.v.cancel_corridor_drag()
        self.v.adopt_cloud(paths,prev['scene'],state['camera'])
        self.v.overview_scene=prev['overview'];self.w.poll()
        self.restore_context(state,prev['overlays'])
        for reference in state['references']:
            next(l for l in self.w.linework.layers if l['id']==reference['id'])['visible']=reference['visible']
        self.r.section_source.set(state['section_source']);self.r.section=prev['section'];self.r.confirm.set(prev['confirmed'])
        for var,value in zip(self.v.visible,state['visible']):var.set(value)
        self.r.filelist.selection_clear(0,'end')
        for i,value in enumerate(state['visible']):
            if value:self.r.filelist.selection_set(i)
        self.v.mode.set(state['display']['mode']);self.w.class_filter.set(state['display']['classes']);self.w.line_filter.set(state['display']['line']);self.w.filter()
        self.v.stereo.set(state['display']['stereo']);self.v.stereo_depth.set(state['display']['depth']);self.v.stereo_swap.set(state['display']['swap'])
        self.r.redraw();self.apply_plot(prev['profile']);self.v.draw();self.w.refresh_layers()
        self.info=None;self.profile=None;self.previous=None;self.menu.master.configure(text='Compare ▾')
        self.label.set('Previous display restored from its bounded in-memory sample.')
        self.notice.set('Previous camera, filters, visibility, overlays and section restored. No source scan or processing input change.');self.w.persist()

    def poll(self):
        self.refresh_choices()
        if self.pending and not self.v.busy:
            pending=self.pending
            if not pending['info'] or self.v.cancel.is_set():
                self.pending=None;self.notice.set('Comparison preparation failed/stopped; '+self.v.status.get());return
            info=pending['info']
            if tuple(self.r.loaded_paths)!=tuple(s['path'] for s in info['inputs']) or self.r.scene is not self.v.scene:return
            self.pending=None;self.info=info;self.previous=pending['previous']
            self.restore_context(pending['state'],self.previous['overlays'])
            self.r.section=None;self.r.confirm.set(self.confirmed.get())
            self.run(lambda:self.apply_role(self.role.get()));self.w.persist()
        if self.profile_pending and not self.r.busy:
            self.profile_pending=False
            if self.info and section_matches(self.r.section,self.info,self.v.corridor):
                sec=self.r.section;p=self.r.profile
                p.center=(sec.points[:,[3,2]].min(axis=0)+sec.points[:,[3,2]].max(axis=0))/2 if len(sec.points) else np.zeros(2)
                p.span=np.maximum(np.ptp(sec.points[:,[3,2]],axis=0),1e-6) if len(sec.points) else np.ones(2)
                p.zoom=1.;p.pan[:]=0;self.profile=self.plot_state();self.r.redraw();self.apply_plot(self.profile)
                self.apply_role(self.role.get())
                self.profile_status(self.role.get())
            else:self.notice.set('Comparison section was not completed; see cross-section status.')

        if self.info and not self.busy() and tuple(self.v.paths)==tuple(s['path'] for s in self.info['inputs']):
            shown=[var.get() for var in self.v.visible]
            actual='Original' if shown==[True,False] else 'Result' if shown==[False,True] else 'Both' if shown==[True,True] else 'Hidden'
            if actual in ('Original','Result','Both') and actual!=self.role.get():
                self.role.set(actual);self.menu.master.configure(text='Compare: '+actual+' ▾')
                self.label.set(f'{actual} · {self.info["provenance"]}\nOriginal: {self.info["original"]}\nResult: {self.info["result"]}')
            elif actual=='Hidden':self.label.set('Both comparison clouds are hidden. Select Original, Result or Both to show them.')
            if section_matches(self.r.section,self.info,self.v.corridor):
                selected=tuple(i for i,value in enumerate(shown) if value)
                if tuple(self.r.filelist.curselection())!=selected:
                    plot=self.plot_state();self.r.filelist.selection_clear(0,'end')
                    for i in selected:self.r.filelist.selection_set(i)
                    self.r.redraw();self.apply_plot(plot)
                    self.profile_status(actual)

    def snapshot(self):return preferences(dict(schema_version=1,original=self.original.get(),result=self.result.get(),confirmed=self.confirmed.get(),role=self.role.get()))

    def restore(self,state):
        data=preferences(state);self.pending=None;self.info=None;self.previous=None;self.profile=None;self.profile_pending=False
        self.original.set(data['original']);self.result.set(data['result']);self.confirmed.set(data['confirmed']);self.role.set(data['role'])
        self.menu.master.configure(text='Compare ▾');self.label.set('Saved pair settings restored; Prepare comparison validates sources before switching.')
        self.refresh_choices(force=True)
