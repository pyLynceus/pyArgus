"""DXF layer review controls, separate from optional digitizing tools."""
from copy import deepcopy
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,colorchooser
import numpy as np
from pyargus.linework import read_dxf,validate


class LineworkPanel:
    def __init__(self,workspace,parent):
        self.workspace=workspace;self.viewer=workspace.viewer;self.parent=parent;self.layers=[]
        bar=ttk.Frame(parent);bar.pack(fill='x')
        for name,fn in [('Import DXF…',self.choose),('Show/hide',self.toggle),('Isolate',self.isolate),('Show all',self.show_all),('Fit layer',self.fit),('Sections…',self.sections),('Color…',self.color),('Remove',self.remove)]:
            ttk.Button(bar,text=name,command=lambda f=fn:self.run(f)).pack(side='left',padx=2)
        self.width=tk.StringVar(value='2');self.top=tk.BooleanVar(value=True)
        ttk.Spinbox(bar,from_=1,to=6,width=3,textvariable=self.width).pack(side='left')
        ttk.Checkbutton(bar,text='Always on top',variable=self.top).pack(side='left')
        ttk.Button(bar,text='Apply style',command=lambda:self.run(self.style)).pack(side='left')
        self.tree=ttk.Treeview(parent,columns=('shown','kind','source'),show='tree headings',height=5,selectmode='browse')
        self.tree.heading('#0',text='DXF layer');self.tree.column('#0',width=180)
        for key,label in [('shown','Visible'),('kind','Elevation mode'),('source','Source DXF')]:self.tree.heading(key,text=label)
        self.tree.pack(fill='both',expand=True)
        self.tree.bind('<Double-Button-1>',lambda e:self.run(self.toggle));self.tree.bind('<<TreeviewSelect>>',self.select)
        self.notice=tk.StringVar(value='Import linework in the cloud frame. Uncheck Always on top for depth testing against displayed cloud points.')
        ttk.Label(parent,textvariable=self.notice,wraplength=1000).pack(fill='x')

    def run(self,fn):
        try:fn()
        except Exception as exc:messagebox.showerror('Linework',str(exc),parent=self.parent)

    def selected(self):
        ids=self.tree.selection()
        if not ids:raise ValueError('Select a DXF layer first.')
        return next(layer for layer in self.layers if layer['id']==ids[0])

    def select(self,event=None):
        if self.tree.selection():
            layer=self.selected();self.width.set(str(layer['width']));self.top.set(layer['on_top'])

    def refresh(self):
        selected=self.tree.selection();self.tree.delete(*self.tree.get_children())
        for layer in self.layers:
            self.tree.insert('','end',iid=layer['id'],text=layer['name'],values=('Yes' if layer['visible'] else 'No',
                f"2D at display Z {layer['elevation']:g}" if layer['planar'] else 'Supplied XYZ',Path(layer['source']['path']).name))
        if selected and selected[0] in self.tree.get_children():self.tree.selection_set(selected[0])

    def changed(self):
        self.refresh();self.viewer.draw();self.workspace.persist()
        if hasattr(self.workspace,"layout"):self.workspace.refresh_layers()
    def toggle(self):l=self.selected();l['visible']=not l['visible'];self.changed()
    def isolate(self):
        selected=self.selected()
        for layer in self.layers:layer['visible']=layer is selected
        self.changed()
    def show_all(self):
        for layer in self.layers:layer['visible']=True
        self.changed()
    def remove(self):self.layers.remove(self.selected());self.changed()
    def style(self):
        width=int(self.width.get())
        if not 1<=width<=6:raise ValueError('Width must be 1–6 pixels.')
        self.selected().update(width=width,on_top=self.top.get());self.changed()
    def color(self):
        layer=self.selected();chosen=colorchooser.askcolor(layer['color'],parent=self.parent)[1]
        if chosen:layer['color']=chosen;self.changed()
    def fit(self):
        from pyproj import CRS
        layer=self.selected()
        if self.viewer.scene is None or CRS(layer['crs'])!=self.viewer.scene[5]:raise ValueError('Load the matching cloud CRS first.')
        points=np.concatenate(layer['segments']);self.viewer.remember_view()
        self.viewer.center=(points.min(axis=0)+points.max(axis=0))/2
        self.viewer.span=max(float(np.linalg.norm(np.ptp(points,axis=0))),1.)
        self.viewer.zoom=1.;self.viewer.pan[:]=0;self.viewer.draw()

    def sections(self):
        self.workspace.show_section_review()
        review=self.workspace.review
        review.route.choose(self.selected())

    def choose(self):
        if self.viewer.busy:raise ValueError('Wait for the current viewer operation, or Stop loading.')
        if self.viewer.scene is None:raise ValueError('Load a cloud before importing reference linework.')
        path=filedialog.askopenfilename(parent=self.parent,filetypes=(('DXF linework','*.dxf'),))
        if not path:return
        dialog=tk.Toplevel(self.parent);dialog.title('DXF coordinate declaration');dialog.transient(self.parent.winfo_toplevel());dialog.grab_set()
        crs=self.viewer.scene[5]
        ttk.Label(dialog,text=f'Cloud frame: {crs.name}\nUnits: {crs.axis_info[0].unit_name}\nNo rescaling or reprojection is performed.',wraplength=500).pack(padx=12,pady=8)
        confirmed=tk.BooleanVar(value=False);planar=tk.BooleanVar(value=False)
        z=tk.StringVar(value=str(self.viewer.center[2]));tol=tk.StringVar(value='0.1')
        ttk.Checkbutton(dialog,text='I confirm DXF shares the cloud XY frame, units and (for 3D) height datum',variable=confirmed).pack(anchor='w',padx=12)
        ttk.Checkbutton(dialog,text='2D plan only — use display elevation below (not measured height)',variable=planar).pack(anchor='w',padx=12)
        for label,var in [('2D display elevation',z),('Curve tolerance (map units)',tol)]:
            row=ttk.Frame(dialog);row.pack(fill='x',padx=12);ttk.Label(row,text=label).pack(side='left');ttk.Entry(row,textvariable=var).pack(side='right')
        def start():
            try:
                if not confirmed.get():raise ValueError('Confirm coordinate compatibility before importing.')
                args=dict(crs=crs,planar=planar.get(),elevation=float(z.get()),tolerance=float(tol.get()),cancel=self.viewer.cancel)
                if not np.isfinite([args['elevation'],args['tolerance']]).all() or args['tolerance']<=0:raise ValueError('Invalid elevation or tolerance.')
                dialog.destroy()
                self.viewer.launch(lambda:('linework',*read_dxf(path,**args)))
            except Exception as exc:messagebox.showerror('Linework',str(exc),parent=dialog)
        ttk.Button(dialog,text='Import',command=start).pack(pady=8)

    def imported(self,layers,skipped):
        combined=self.layers+layers;validate(combined);self.layers=combined;self.changed()
        self.notice.set(f'Imported {len(layers)} layers. Skipped entity types/counts: {skipped or "none"}. Blocks are not expanded; explode them before import.')

    def restore(self,layers):
        from pyargus.job_manifest import identity
        validate(layers);self.layers=deepcopy(layers);missing=[]
        for layer in self.layers:
            try:current=identity(layer['source']['path'])==layer['source']
            except OSError:current=False
            if not current:layer['visible']=False;missing.append(layer['name'])
        self.refresh()
        if missing:self.notice.set('Saved geometry retained; sources changed/missing, layers hidden: '+', '.join(missing))

    def geometry(self):
        from pyproj import CRS
        if self.viewer.scene is None:return []
        return [(np.asarray(segment),tuple(bytes.fromhex(layer['color'][1:])),int(layer['width']),layer['on_top'])
                for layer in self.layers if layer['visible'] and CRS(layer['crs'])==self.viewer.scene[5] for segment in layer['segments']]
