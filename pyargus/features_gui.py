"""Feature tracing panel for the unified viewer."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from pyargus.features import Features, KINDS, export_dxf


class FeaturePanel:
    def __init__(self, workspace, parent):
        self.workspace=workspace; self.parent=parent; self.viewer=workspace.viewer
        self.model=Features(); self.selected=None
        bar=ttk.Frame(parent);bar.pack(fill='x')
        for title,fn in [('New line',self.new),('Undo',lambda:self.history(False)),('Redo',lambda:self.history(True)),
                         ('Delete line',self.delete),('Reverse',self.reverse),('Split at vertex',self.split),('Join two lines',self.join)]:
            ttk.Button(bar,text=title,command=lambda f=fn:self.run(f)).pack(side='left',padx=2)
        self.name=tk.StringVar(value='Feature 1');self.kind=tk.StringVar(value=KINDS[0]);self.status=tk.StringVar(value='Candidate')
        bar=ttk.Frame(parent);bar.pack(fill='x',pady=3)
        ttk.Label(bar,text='Name').pack(side='left');ttk.Entry(bar,textvariable=self.name,width=25).pack(side='left')
        ttk.Combobox(bar,textvariable=self.kind,values=KINDS,state='readonly',width=17).pack(side='left')
        ttk.Combobox(bar,textvariable=self.status,values=('Candidate','Accepted'),state='readonly',width=12).pack(side='left')
        ttk.Button(bar,text='Apply properties',command=lambda:self.run(self.properties)).pack(side='left')
        self.mode=tk.StringVar(value='Inspect')
        ttk.Combobox(bar,textvariable=self.mode,values=('Inspect','Append vertices','Replace selected vertex'),state='readonly',width=24).pack(side='left',padx=5)
        ttk.Button(bar,text='Finish tracing',command=lambda:self.mode.set('Inspect')).pack(side='left')
        ttk.Label(parent,text='Shift-click cloud points to trace while this tab is open. Picks use the display sample; Refine view for more detail. XYZ units follow the source CRS.').pack(anchor='w')
        panes=ttk.Panedwindow(parent,orient='horizontal');panes.pack(fill='both',expand=True)
        left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=1);panes.add(right,weight=2)
        self.lines=ttk.Treeview(left,columns=('type','status','count'),show='tree headings',height=6,selectmode='extended')
        self.lines.heading('#0',text='Feature');self.lines.column('#0',width=150)
        for key,title,width in [('type','Type',110),('status','Review',85),('count','Vertices',60)]:
            self.lines.heading(key,text=title);self.lines.column(key,width=width)
        self.lines.pack(fill='both',expand=True);self.lines.bind('<<TreeviewSelect>>',self.select)
        self.vertices=ttk.Treeview(right,columns=('x','y','z','source'),show='headings',height=6,selectmode='browse')
        for key in ('x','y','z','source'):
            self.vertices.heading(key,text=key.upper());self.vertices.column(key,width=100 if key!='source' else 190)
        self.vertices.pack(fill='both',expand=True);self.vertices.bind('<<TreeviewSelect>>',self.select_vertex)
        bar=ttk.Frame(parent);bar.pack(fill='x')
        self.xyz=[tk.StringVar() for _ in range(3)]
        for label,var in zip(('X','Y','Z'),self.xyz):
            ttk.Label(bar,text=label).pack(side='left');ttk.Entry(bar,textvariable=var,width=15).pack(side='left')
        for label,fn in [('Apply XYZ',self.apply_xyz),('Delete vertex',self.delete_vertex)]:
            ttk.Button(bar,text=label,command=lambda f=fn:self.run(f)).pack(side='left')
        self.accepted_only=tk.BooleanVar(value=True)
        ttk.Checkbutton(bar,text='Accepted only',variable=self.accepted_only).pack(side='left',padx=4)
        ttk.Button(bar,text='Export DXF…',command=lambda:self.run(self.export)).pack(side='left')
        self.notice=tk.StringVar(value='New lines are candidates. Acceptance records your review, not an accuracy certification.')
        ttk.Label(parent,textvariable=self.notice,wraplength=1100).pack(fill='x')

    def run(self, fn):
        try: fn()
        except Exception as exc: messagebox.showerror('Features',str(exc),parent=self.parent)

    def active(self):
        if not self.selected: raise ValueError('Select a feature first.')
        return self.selected

    def vertex_index(self):
        selected=self.vertices.selection()
        if not selected: raise ValueError('Select a vertex first.')
        return int(selected[0])

    def changed(self):
        self.refresh();self.workspace.persist();self.viewer.draw()

    def new(self):
        self.selected=self.model.new(self.name.get(),self.kind.get());self.changed();self.mode.set('Append vertices')
        self.notice.set('Tracing: Shift-click displayed points in order. Finish tracing stops adding vertices.')

    def refresh(self):
        self.lines.delete(*self.lines.get_children())
        for f in self.model.items:
            self.lines.insert('','end',iid=f['id'],text=f['name'],values=(f['kind'],f['status'],len(f['vertices'])))
        if self.selected in self.lines.get_children(): self.lines.selection_set(self.selected)
        else:self.selected=None
        self.refresh_vertices()

    def select(self, event=None):
        ids=self.lines.selection()
        if not ids:return
        self.selected=ids[0];f=self.model.get(self.selected)
        self.name.set(f['name']);self.kind.set(f['kind']);self.status.set(f['status'])
        from pyargus.features import sources_current
        self.notice.set('Source missing or changed: acceptance/export blocked until retraced against current data.' if not sources_current(f) else 'Candidate lines are yellow; accepted lines green. Lines draw on top of the cloud; review from multiple angles.')
        self.refresh_vertices();self.viewer.draw()

    def refresh_vertices(self):
        self.vertices.delete(*self.vertices.get_children())
        if self.selected:
            for i,v in enumerate(self.model.get(self.selected)['vertices']):
                self.vertices.insert('','end',iid=str(i),values=(*[f'{x:.6f}' for x in v['xyz']],Path(v['source']['path']).name))

    def select_vertex(self, event=None):
        if self.vertices.selection() and self.selected:
            v=self.model.get(self.selected)['vertices'][self.vertex_index()]
            for var,x in zip(self.xyz,v['xyz']):var.set(repr(x))

    def pick(self, value):
        if self.mode.get()=='Inspect' or self.workspace.tabs.select()!=str(self.parent):return
        def accept():
            from pyargus.job_manifest import identity
            if self.viewer.busy:raise ValueError('Wait for cloud loading to finish before tracing.')
            source=identity(value['file']); review=self.workspace.review
            if value['file'] not in review.loaded_paths:raise ValueError('Wait for the loaded source to synchronize before tracing.')
            if source!=review.loaded_identities[list(review.loaded_paths).index(value['file'])]:
                raise ValueError('Cloud changed since loading; reload before tracing.')
            index=self.vertex_index() if self.mode.get()=='Replace selected vertex' else None
            self.model.vertex(self.active(),[value[k] for k in ('x','y','z')],source,self.viewer.scene[5],index)
            self.changed()
            if index is not None:self.vertices.selection_set(str(index))
        self.run(accept)

    def properties(self):
        self.model.metadata(self.active(),self.name.get(),self.kind.get(),self.status.get());self.changed()

    def apply_xyz(self):
        index=self.vertex_index();self.model.update_xyz(self.active(),index,[float(v.get()) for v in self.xyz]);self.changed()
        self.vertices.selection_set(str(index))

    def delete_vertex(self):
        self.model.delete_vertex(self.active(),self.vertex_index());self.changed()

    def delete(self):self.model.delete(self.active());self.selected=None;self.changed()
    def reverse(self):self.model.reverse(self.active());self.changed()
    def split(self):self.model.split(self.active(),self.vertex_index());self.changed()

    def join(self):
        ids=self.lines.selection()
        if len(ids)!=2:raise ValueError('Select two lines with Ctrl-click. The earlier list item ends at the later item’s start; use Reverse first if needed.')
        self.model.join(*ids);self.selected=ids[0];self.changed()

    def history(self, redo):
        self.model.redo() if redo else self.model.undo();self.mode.set('Inspect');self.changed()

    def export(self):
        path=filedialog.asksaveasfilename(parent=self.parent,defaultextension='.dxf',filetypes=(('3D feature linework','*.dxf'),))
        if path:
            outputs=export_dxf(self.model.items,path,self.accepted_only.get())
            self.notice.set('Exported '+str(outputs[0])+' and provenance sidecar. Coordinates unchanged; no reprojection.')

    def restore(self, model):
        self.model=model;self.selected=None;self.mode.set('Inspect');self.refresh();self.viewer.draw()

    def draw(self, scale, w, h):
        from pyargus.viewer3d import project_points
        from pyproj import CRS
        if self.viewer.scene is None:return
        crs=self.viewer.scene[5]
        for f in self.model.items:
            if not f['vertices'] or CRS(f['crs'])!=crs:continue
            pts=np.array([v['xyz'] for v in f['vertices']])
            coords=project_points(pts,self.viewer.center,self.viewer.yaw,self.viewer.pitch)[:,:2]*[scale,-scale]+[w/2,h/2]+self.viewer.pan
            color='#62e8aa' if f['status']=='Accepted' else '#ffd15b'
            if len(coords)>1:self.viewer.canvas.create_line(*coords.ravel(),fill=color,width=3 if f['id']==self.selected else 2)
            if f['id']==self.selected:
                for i,(x,y) in enumerate(coords):
                    self.viewer.canvas.create_oval(x-3,y-3,x+3,y+3,outline=color,fill=color)
                    self.viewer.canvas.create_text(x+6,y-6,text=str(i+1),fill=color,anchor='sw')
