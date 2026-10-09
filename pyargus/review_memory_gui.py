"""Saved viewing positions, issue annotations and read-only review resumption."""
from copy import deepcopy
from pathlib import Path
import json
import time
import tkinter as tk
from tkinter import ttk,simpledialog,filedialog
import numpy as np
from pyargus.review_memory import ReviewMemory,validate_state,context_errors,CATEGORIES,STATES
from pyargus.job_manifest import identity


class ReviewNotes:
    def __init__(self,layout):
        self.layout=layout;self.w=layout.w;self.v=layout.v;self.r=self.w.review
        self.model=ReviewMemory();self.pending=None;self.resume_pending=False;self.armed=False
        self.selected_issue=None;self.availability={};self.last_check=0.;self.refresh_key=None;self.marker_pixels={}
        self.frame=ttk.Frame(self.w.tabs,padding=5);self.w.tabs.insert(self.w.features_tab,self.frame,text='Review notes')
        bar=ttk.Frame(self.frame);bar.pack(fill='x')
        for label,fn in [('Save view…',self.save_view),('Place issue on point',self.arm),('Issue at view center',self.issue_here),
                         ('Resume Review',self.resume),('Next open issue',self.next_issue),('Export notes…',self.export)]:
            ttk.Button(bar,text=label,command=lambda f=fn:self.run(f)).pack(side='left',padx=2)
        self.notice=tk.StringVar(value='Views and issue notes are saved in the workspace. Returning restores context; extract the profile when needed.')
        ttk.Label(self.frame,textvariable=self.notice,wraplength=1100).pack(fill='x',pady=4)
        panes=ttk.Panedwindow(self.frame,orient='horizontal');panes.pack(fill='both',expand=True)
        left=ttk.LabelFrame(panes,text='Saved views',padding=3);right=ttk.LabelFrame(panes,text='Issues',padding=3)
        panes.add(left,weight=1);panes.add(right,weight=2)
        self.views=self.tree(left,('state',),('Context',),(120,))
        self.views.bind('<Double-Button-1>',lambda e:self.run(self.go_view))
        buttons=ttk.Frame(left);buttons.pack(fill='x')
        for label,fn in [('Go',self.go_view),('Replace',self.replace_view),('Rename…',self.rename_view),('Delete',self.delete_view)]:
            ttk.Button(buttons,text=label,command=lambda f=fn:self.run(f)).pack(side='left',padx=2)
        filters=ttk.Frame(right);filters.pack(fill='x')
        self.issue_filter=tk.StringVar(value='Open');self.show_resolved=tk.BooleanVar(value=False)
        ttk.Label(filters,text='Show:').pack(side='left')
        combo=ttk.Combobox(filters,textvariable=self.issue_filter,values=('Open','All','Resolved'),state='readonly',width=12)
        combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda e:self.refresh(force=True))
        ttk.Checkbutton(filters,text='Resolved pins',variable=self.show_resolved,command=self.v.draw).pack(side='left',padx=6)
        self.issues=self.tree(right,('category','state','context'),('Type','Status','Context'),(155,95,100))
        self.issues.bind('<<TreeviewSelect>>',self.select_issue)
        self.issues.bind('<Double-Button-1>',lambda e:self.run(self.go_issue))
        buttons=ttk.Frame(right);buttons.pack(fill='x')
        for label,fn in [('Go to issue',self.go_issue),('Resolve',lambda:self.set_state('Resolved')),('Reopen',lambda:self.set_state('Open')),('Delete',self.delete_issue)]:
            ttk.Button(buttons,text=label,command=lambda f=fn:self.run(f)).pack(side='left',padx=2)
        edit=ttk.Frame(self.frame);edit.pack(fill='x',pady=4)
        self.title=tk.StringVar();self.category=tk.StringVar(value='Other');self.state=tk.StringVar(value='Open')
        ttk.Label(edit,text='Title').pack(side='left');ttk.Entry(edit,textvariable=self.title,width=35).pack(side='left',fill='x',expand=True)
        for var,values,width in [(self.category,CATEGORIES,22),(self.state,STATES,12)]:
            ttk.Combobox(edit,textvariable=var,values=values,state='readonly',width=width).pack(side='left',padx=3)
        ttk.Button(edit,text='Apply note',command=lambda:self.run(self.apply_issue)).pack(side='left')
        self.note=tk.Text(self.frame,height=3,wrap='word');self.note.pack(fill='x')
        self.location=tk.StringVar(value='Select an issue. Resolved records an operator decision; it does not approve a processing stage.')
        ttk.Label(self.frame,textvariable=self.location,wraplength=1100).pack(fill='x',pady=3)
        self.menu=layout.dropdown(layout.toolbar_rows[1],'Review')
        for label,fn in [('Save current view…',self.save_view),('Resume Review',self.resume),('Place issue on point',self.arm),('Issue at view center',self.issue_here),('Review notes',self.show)]:
            self.menu.add_command(label=label,command=lambda f=fn:self.run(f))
        self.saved_menu=tk.Menu(self.menu,tearoff=False);self.menu.add_cascade(label='Saved views',menu=self.saved_menu)
        layout.menus['View'].add_cascade(label='Review notes / saved views',menu=self.menu)
        layout.menus['File'].add_command(label='Resume Review',command=lambda:self.run(self.resume))
        self.v.on_note_draw=self.draw;self.v.note_geometry=self.geometry;self.v.on_note_click=self.click_pin
        self.v.on_issue_pick=self.picked;self.v.issue_armed=lambda:self.armed
        self.v.canvas.bind('<Escape>',lambda e:self.disarm() if self.armed else None,add='+')
        self.refresh(force=True)

    @staticmethod
    def tree(parent,columns,headings,widths):
        box=ttk.Frame(parent);box.pack(fill='both',expand=True)
        tree=ttk.Treeview(box,columns=columns,show='tree headings',height=5,selectmode='browse')
        tree.heading('#0',text='Name');tree.column('#0',width=200,minwidth=100)
        for column,title,width in zip(columns,headings,widths):tree.heading(column,text=title);tree.column(column,width=width,minwidth=60)
        scroll=ttk.Scrollbar(box,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');tree.pack(fill='both',expand=True);return tree

    def run(self,fn):
        try:return fn()
        except (ValueError,OSError,KeyError,TypeError) as exc:self.notice.set(str(exc));self.v.status.set(str(exc))

    def show(self):
        self.layout.set_mode('Review');self.layout.show_panel(self.frame);self.layout.request_split(.45)

    def busy(self):return self.v.busy or self.r.busy or self.w.app.runner.running or self.pending is not None

    def capture_view(self):
        if self.busy():raise ValueError('Finish the current load or job before saving or returning to a review position.')
        if self.v.scene is None or not self.v.paths or self.r.scene is not self.v.scene or tuple(self.r.loaded_paths)!=tuple(self.v.paths):
            raise ValueError('Load clouds and wait for the workspace inventory to synchronize first.')
        sources=[identity(p) for p in self.v.paths]
        if sources!=self.r.loaded_identities:raise ValueError('Clouds changed since loading. Reload them before saving a review position.')
        if self.layout.corridor.drag is not None:raise ValueError('Finish or cancel the corridor drag before saving a review position.')
        v=self.v;r=self.r;scale=min(max(2,v.canvas.winfo_width()),max(2,v.canvas.winfo_height()))*.85/v.span*v.zoom
        section=None
        if v.corridor is not None:
            a,b,width=v.corridor;section=dict(start=a.tolist(),end=b.tolist(),width=width)
        state=dict(schema_version=1,inputs=sources,crs=v.scene[5].to_wkt() if v.scene[5] else None,
            camera=dict(center=v.center.tolist(),pan_units=(v.pan/scale).tolist(),yaw=v.yaw%360,pitch=v.pitch,zoom=v.zoom,span=v.span),
            display=dict(mode=v.mode.get(),classes=self.w.class_filter.get(),line=self.w.line_filter.get(),stereo=v.stereo.get(),depth=v.stereo_depth.get(),swap=v.stereo_swap.get()),
            visible=[x.get() for x in v.visible],section=section,section_source=r.section_source.get(),confirmed=r.confirm.get(),route=deepcopy(r.route.state),
            profile=dict(mode=r.mode.get(),line=r.line.get(),exaggeration=r.exaggeration.get()),layout=self.layout.snapshot(),details=r.details_visible.get(),
            references=[dict(id=l['id'],source=deepcopy(l['source']),visible=l['visible']) for l in self.w.linework.layers])
        state=validate_state(state)
        errors=context_errors(state)
        if errors:raise ValueError('Cannot save changed review context. '+errors[0])
        return state

    def checkpoint(self):
        if self.layout.mode!='Review' or self.resume_pending:return
        try:self.model.data['last_review']=self.capture_view()
        except (ValueError,OSError,KeyError,TypeError):pass
        self.model.data['issue_filter']=self.issue_filter.get();self.model.data['show_resolved']=self.show_resolved.get()
        self.model.data['selected_issue']=self.selected_issue

    def restore(self,model):
        self.disarm();self.pending=None;self.resume_pending=False;self.model=model;self.selected_issue=None;self.refresh_key=None
        self.title.set('');self.note.delete('1.0','end');self.marker_pixels={}
        self.notice.set('Workspace review notes loaded. Resume Review returns to its saved checkpoint without extracting a profile.')
        self.issue_filter.set(model.data.get('issue_filter','Open') if model.data.get('issue_filter','Open') in ('Open','All','Resolved') else 'Open')
        self.show_resolved.set(bool(model.data.get('show_resolved',False)))
        self.refresh(force=True)
        saved=model.data.get('selected_issue')
        if saved and self.issues.exists(saved):self.issues.selection_set(saved);self.select_issue()

    def changed(self):
        self.refresh(force=True);self.v.draw();self.w.persist()

    def save_view(self):
        state=self.capture_view();name=simpledialog.askstring('Save view','Name this review location:',initialvalue=f'View {len(self.model.data["views"])+1}',parent=self.layout.root)
        if name is None:return
        row=self.model.save_view(name,state);self.changed();self.views.selection_set(row['id'])
        self.notice.set('Saved view: '+row['title'])

    def view_id(self):
        selected=self.views.selection()
        if not selected:raise ValueError('Select a saved view first.')
        return selected[0]

    def go_view(self):
        row=self.model.get('views',self.view_id());self.recall(row['view'],'Saved view: '+row['title'])

    def replace_view(self):
        row=self.model.get('views',self.view_id());self.model.save_view(row['title'],self.capture_view(),row['id']);self.changed()
        self.views.selection_set(row['id']);self.notice.set('Saved view replaced with the current viewing position.')

    def rename_view(self):
        row=self.model.get('views',self.view_id());name=simpledialog.askstring('Rename view','View name:',initialvalue=row['title'],parent=self.layout.root)
        if name is not None:self.model.save_view(name,row['view'],row['id']);self.changed();self.views.selection_set(row['id'])

    def delete_view(self):
        row=self.model.get('views',self.view_id());self.model.data['views'].remove(row);self.changed()

    def verify(self,state):
        state=validate_state(state);errors=context_errors(state)
        if errors:raise ValueError('Saved review position unavailable. '+errors[0])
        known={l['id']:l for l in self.w.linework.layers}
        for ref in state['references']:
            if ref['id'] not in known or ref['source']!=known[ref['id']]['source']:
                raise ValueError('Saved reference layer is not imported in this workspace. Open its original workspace first.')
        if state['route'] is not None:
            from pyargus.route_sections import corridor_at
            from pyproj import CRS
            layer,vertices=self.r.route.layer(state['route']);route=state['route']
            corridor_at(vertices,route['station'],route['span'],route['width'])
            if state['crs'] is None or CRS(layer['crs'])!=CRS(state['crs']):raise ValueError('Saved route and cloud CRS differ.')
        return state

    def recall(self,state,label):
        if self.busy() or self.w.pending_view or getattr(self.w,'pending_version_view',False):raise ValueError('Wait for the current load or job before returning to a review position.')
        state=self.verify(state);self.disarm();self.v.cancel_corridor_drag();self.v.auto_detail.set(False);self.v.reset_auto()
        paths=tuple(s['path'] for s in state['inputs'])
        if self.v.scene is None or tuple(self.v.paths)!=paths:
            self.pending=(state,label);self.v.load(paths);self.notice.set('Loading the saved view clouds. Processing inputs are retained.');return
        self.apply(state,label)

    def apply(self,state,label):
        state=self.verify(state)
        from pyproj import CRS
        current=self.v.scene[5]
        if (current is None)!=(state['crs'] is None) or (current is not None and current!=CRS(state['crs'])):
            raise ValueError('Saved view CRS differs from the loaded cloud. Reload the recorded source.')
        if self.r.loaded_identities!=state['inputs']:raise ValueError('Loaded cloud identities differ from the saved view. Reload the recorded source.')
        self.v.remember_view();self.layout.restore(state['layout'])
        self.r.details_visible.set(state['details']);self.r.toggle_details()
        self.layout.request_split(state['layout'].get('split_fraction',.48))
        self.r.route.restore(state['route']);self.r.confirm.set(state['confirmed']);self.r.section_source.set(state['section_source'])
        self.r.mode.set(state['profile']['mode']);self.r.line.set(state['profile']['line']);self.r.exaggeration.set(str(state['profile']['exaggeration']))
        self.r.clear_section();self.r.endpoint=None
        if state['section'] is None:
            self.v.corridor=None
            for var in self.r.coords:var.set('')
        else:
            cut=state['section']
            for var,value in zip(self.r.coords,cut['start']+cut['end']):var.set(repr(value))
            self.r.width.set(repr(cut['width']));self.r.set_corridor()
        for ref in state['references']:
            next(l for l in self.w.linework.layers if l['id']==ref['id'])['visible']=ref['visible']
        display=state['display'];self.v.mode.set(display['mode']);self.v.stereo.set(display['stereo']);self.v.stereo_depth.set(display['depth']);self.v.stereo_swap.set(display['swap'])
        self.w.class_filter.set(display['classes']);self.w.line_filter.set(display['line'])
        for var,value in zip(self.v.visible,state['visible']):var.set(value)
        camera=state['camera'];self.v.center=np.array(camera['center']);self.v.pan=np.zeros(2)
        for key in ('yaw','pitch','zoom','span'):setattr(self.v,key,camera[key])
        self.layout.root.update_idletasks()
        scale=min(max(2,self.v.canvas.winfo_width()),max(2,self.v.canvas.winfo_height()))*.85/self.v.span*self.v.zoom
        self.v.pan=np.array(camera['pan_units'])*scale;self.w.filter();self.r.redraw()
        self.layout.shortcuts.previous=None;self.w.refresh_layers()
        self.notice.set(label+' — context restored. Extract section to refresh the profile. Auto detail is off.')
        self.r.status.set('Saved section definition restored; click Extract section to refresh the profile.')
        self.model.data['last_review']=deepcopy(state);self.v.status.set(label);self.w.persist()

    def resume(self):
        state=self.model.data.get('last_review')
        if state is not None:self.recall(state,'Resumed review');return
        if self.busy():raise ValueError('Wait for the current load or job before resuming.')
        target=self.w.path
        if self.w.resume_path.exists():target=Path(json.loads(self.w.resume_path.read_text(encoding='utf-8'))['workspace'])
        if not target.exists():raise ValueError('No saved review checkpoint. Open a workspace and inspect a cloud first.')
        from pyargus.workspace_state import Tracker
        tracker=Tracker.load(target);model=ReviewMemory(tracker.data.get('review_notes'));state=model.data.get('last_review')
        if state is None:raise ValueError('This workspace has no review checkpoint yet. Open it through File → Open workspace.')
        errors=context_errors(state)
        if errors:raise ValueError('Saved review position unavailable. '+errors[0])
        if not self.w.restore(target,load_view=False):raise ValueError('The saved workspace could not be opened.')
        self.recall(self.model.data['last_review'],'Resumed review')

    def arm(self):
        self.capture_view()
        if self.v.stereo.get():raise ValueError('Turn off Stereo before placing an issue on a point; Issue at view center is available in stereo.')
        self.v.cancel_corridor_drag();self.layout.corridor.enabled.set(False);self.v.choose_pivot=False;self.w.features.mode.set('Inspect')
        self.armed=True;self.v.orbit_anchor=None;self.v.canvas.focus_set();self.v.canvas.configure(cursor='crosshair')
        self.v.status.set('Click a displayed cloud point to place an issue. Esc cancels. The location comes from the display sample.')

    def disarm(self):
        if self.armed:self.armed=False;self.v.canvas.configure(cursor='');self.v.orbit_anchor=None;return 'break'

    def picked(self,pick):
        if not self.armed:return False
        self.run(lambda:self.new_issue(pick));self.disarm();return True

    def issue_here(self):self.new_issue()

    def new_issue(self,pick=None):
        state=self.capture_view();number=self.model.data['next_issue_number']
        row=self.model.issue(f'Issue {number:03d}',state,pick)
        self.issue_filter.set('Open');self.selected_issue=row['id'];self.changed();self.show()
        self.issues.selection_set(row['id']);self.select_issue()
        self.notice.set('Issue placed. Add a title, type and note, then Apply note. Its location is '+row['anchor']['kind']+'.')

    def select_issue(self,event=None):
        selected=self.issues.selection()
        if not selected:return
        self.selected_issue=selected[0];row=self.model.get('issues',self.selected_issue)
        self.title.set(row['title']);self.category.set(row['category']);self.state.set(row['state'])
        self.note.delete('1.0','end');self.note.insert('1.0',row['note'])
        anchor=row['anchor'];xyz=' / '.join(f'{x:.3f}' for x in anchor['xyz'])
        available=self.availability.get(row['id'],'Unknown')
        self.location.set(f"I-{row['number']:03d} | XYZ {xyz} | {anchor['kind']} | {Path(anchor.get('file','')).name} | {available}. Resolved is an operator decision, not accuracy certification.")
        self.model.data['selected_issue']=row['id'];self.v.draw()

    def apply_issue(self):
        self.model.update_issue(self.selected_issue,self.title.get(),self.category.get(),self.state.get(),self.note.get('1.0','end-1c'))
        self.changed();self.notice.set('Issue note saved in the workspace.')

    def set_state(self,state):
        if self.selected_issue is None:raise ValueError('Select an issue first.')
        self.state.set(state);self.apply_issue()

    def go_issue(self):
        row=self.model.get('issues',self.selected_issue);self.recall(row['view'],f"I-{row['number']:03d}: {row['title']}")

    def next_issue(self):
        rows=[r for r in self.model.data['issues'] if r['state']!='Resolved']
        if not rows:raise ValueError('No open issues in this workspace.')
        current=next((i for i,row in enumerate(rows) if row['id']==self.selected_issue),-1);row=rows[(current+1)%len(rows)]
        self.issue_filter.set('Open');self.selected_issue=row['id'];self.refresh(force=True);self.issues.selection_set(row['id']);self.select_issue();self.go_issue()

    def delete_issue(self):
        row=self.model.get('issues',self.selected_issue);self.model.data['issues'].remove(row);self.selected_issue=None
        self.title.set('');self.note.delete('1.0','end');self.changed()

    def export(self):
        path=filedialog.asksaveasfilename(parent=self.layout.root,filetypes=(('Review notes JSON','*.json'),),defaultextension='.json',initialfile='review-notes.json')
        if not path:return
        # Do not let an annotations export overwrite a workspace or source file.
        target=Path(path).resolve();protected={self.w.path.resolve(),self.w.resume_path.resolve()}
        protected.update(Path(layer['path']).resolve() for layer in self.w.tracker.data['layers'])
        protected.update(Path(p).resolve() for p in self.v.paths)
        for row in [*self.model.data['views'],*self.model.data['issues']]:
            protected.update(Path(s['path']).resolve() for s in row['view']['inputs'])
            protected.update(Path(s['source']['path']).resolve() for s in row['view']['references'])
        if target in protected:raise ValueError('Choose a separate JSON file for review notes.')
        target.write_text(json.dumps(self.model.data,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        self.notice.set('Review notes exported: '+str(target))

    def refresh(self,force=False):
        rows=[*self.model.data['views'],*self.model.data['issues']]
        if force or time.monotonic()-self.last_check>3:
            observed={};self.availability={};known={l['id']:l for l in self.w.linework.layers}
            for row in rows:
                error=None
                for saved in [*row['view']['inputs'],*[r['source'] for r in row['view']['references']]]:
                    path=saved['path']
                    if path not in observed:
                        try:observed[path]=identity(path)
                        except OSError:observed[path]=None
                    if observed[path]!=saved:error='Missing source' if observed[path] is None else 'Changed source';break
                if not error and any(r['id'] not in known or known[r['id']]['source']!=r['source'] for r in row['view']['references']):error='Reference not imported'
                self.availability[row['id']]=error or 'Available'
            self.last_check=time.monotonic()
        key=(tuple((row['id'],row.get('updated'),row.get('state'),self.availability.get(row['id'])) for row in rows),self.issue_filter.get())
        if key==self.refresh_key and not force:return
        self.refresh_key=key;views=self.views.selection();issues=self.issues.selection()
        self.views.delete(*self.views.get_children());self.issues.delete(*self.issues.get_children());self.saved_menu.delete(0,'end')
        for row in self.model.data['views']:
            self.views.insert('','end',iid=row['id'],text=row['title'],values=(self.availability[row['id']],))
            self.saved_menu.add_command(label=row['title'][:60]+(' [unavailable]' if self.availability[row['id']]!='Available' else ''),
                command=lambda row=row:self.run(lambda:self.recall(row['view'],'Saved view: '+row['title'])))
        if not self.model.data['views']:self.saved_menu.add_command(label='No saved views yet',state='disabled')
        for row in self.model.data['issues']:
            if self.issue_filter.get()=='Open' and row['state']=='Resolved':continue
            if self.issue_filter.get()=='Resolved' and row['state']!='Resolved':continue
            self.issues.insert('','end',iid=row['id'],text=f"I-{row['number']:03d} {row['title']}",values=(row['category'],row['state'],self.availability[row['id']]))
        for tree,selected in ((self.views,views),(self.issues,issues)):
            if selected and tree.exists(selected[0]):tree.selection_set(selected[0])

    def visible_markers(self):
        if self.v.scene is None:return []
        loaded={source['path']:source for source in self.r.loaded_identities}
        shown={p for p,var in zip(self.v.paths,self.v.visible) if var.get()}
        result=[]
        crs=self.v.scene[5].to_wkt() if self.v.scene[5] else None
        for row in self.model.data['issues']:
            if row['state']=='Resolved' and not self.show_resolved.get():continue
            if self.availability.get(row['id'])!='Available':continue
            if row['view']['crs']!=crs:continue
            inputs=row['view']['inputs'];anchor=row['anchor']
            if any(loaded.get(s['path'])!=s for s in inputs):continue
            if anchor['kind']=='picked-sample' and anchor['file'] not in shown:continue
            if anchor['kind']=='view-center' and not any(s['path'] in shown for s in inputs):continue
            result.append(row)
        return result

    def geometry(self):return [np.array([row['anchor']['xyz']]) for row in self.visible_markers()]

    def draw(self,scale,width,height):
        from pyargus.viewer3d import project_points
        self.marker_pixels={}
        if self.v.stereo.get():return
        for row in self.visible_markers():
            q=project_points(np.array([row['anchor']['xyz']]),self.v.center,self.v.yaw,self.v.pitch)[0]
            x,y=q[:2]*[scale,-scale]+[width/2,height/2]+self.v.pan
            if not 8<x<width-8 or not 8<y<height-8:continue
            color='#62d596' if row['state']=='Resolved' else '#ffc35a' if row['state']=='In review' else '#ff7d72'
            self.v.canvas.create_oval(x-7,y-7,x+7,y+7,fill='#101925',outline=color,width=2,tags='review-issue')
            self.v.canvas.create_line(x-4,y,x+4,y,fill=color,tags='review-issue');self.v.canvas.create_line(x,y-4,x,y+4,fill=color,tags='review-issue')
            label=f"I-{row['number']:03d}"+(' '+row['title'][:32] if row['id']==self.selected_issue else '')
            self.v.canvas.create_text(x+11,y-11,text=label,fill=color,anchor='sw',tags='review-issue')
            self.marker_pixels[row['id']]=np.array([x,y])

    def click_pin(self,event):
        if self.armed or self.v.stereo.get() or self.layout.corridor.enabled.get() or getattr(event,'state',0)&5:return False
        hits=[(np.linalg.norm(xy-[event.x,event.y]),item_id) for item_id,xy in self.marker_pixels.items()]
        if not hits:return False
        distance,item_id=min(hits)
        if distance>10:return False
        self.issue_filter.set('All');self.selected_issue=item_id;self.refresh(force=True);self.show();self.issues.selection_set(item_id);self.select_issue()
        self.v.orbit_anchor=None;return True

    def poll(self):
        if self.resume_pending and not self.v.busy and not self.w.pending_view:
            self.resume_pending=False;self.run(lambda:self.recall(self.model.data['last_review'],'Resumed review'))
        if self.pending is not None and not self.v.busy:
            state,label=self.pending;self.pending=None
            if tuple(self.v.paths)!=tuple(s['path'] for s in state['inputs']):self.notice.set('Saved clouds could not be loaded; see viewer status.')
            else:self.run(lambda:self.apply(state,label))
        previous=dict(self.availability);self.refresh()
        if previous!=self.availability:self.v.draw()
