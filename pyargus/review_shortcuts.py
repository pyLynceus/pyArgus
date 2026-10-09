"""Read-only project context and quick display controls for the workspace."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from pyargus.display_filters import CLASS_GROUPS,parse_classes


class ReviewShortcuts:
    def __init__(self,layout):
        self.layout=layout;self.w=layout.w;self.v=layout.v;self.previous=None
        self.strip=ttk.Frame(layout.root,padding=(8,3))
        self.strip.pack(fill='x',before=layout.nav)
        self.project=tk.StringVar();self.dataset=tk.StringVar();self.coordinates=tk.StringVar()
        for var in (self.project,self.dataset,self.coordinates):
            ttk.Label(self.strip,textvariable=var,width=1,anchor='w').pack(side='left',fill='x',expand=True,padx=4)
        ttk.Button(self.strip,text='Project details…',command=self.details).pack(side='right')
        self.location=tk.StringVar()
        ttk.Label(layout.root,textvariable=self.location,anchor='w',width=1).pack(fill='x',before=layout.nav,padx=12)
        bar=ttk.Frame(self.v.window)
        bar.pack(fill='x',before=self.v.canvas.master)
        ttk.Label(bar,text='Show classes:').pack(side='left')
        for name in CLASS_GROUPS:
            ttk.Radiobutton(bar,text=name,value=name,variable=self.w.class_filter,
                            command=self.w.filter).pack(side='left',padx=2)
        ttk.Button(bar,text='Custom…',command=layout.filters).pack(side='left',padx=3)
        self.visibility_note=tk.StringVar(value='Select loaded cloud rows; Solo/Compare affect only visibility.')
        tools=ttk.Frame(self.w.sidebar);tools.pack(fill='x',before=self.w.layer_summary)
        for name,fn in [('Solo',lambda:self.show_selected(False)),('Compare',lambda:self.show_selected(True)),('Restore',self.restore)]:
            ttk.Button(tools,text=name,width=8,command=fn).pack(side='left')
        ttk.Label(self.w.sidebar,textvariable=self.visibility_note,wraplength=275).pack(fill='x',before=self.w.layer_summary)
        self.update()

    def show_selected(self,compare=False):
        if self.v.busy:
            self.visibility_note.set('Wait for cloud loading to finish.');return
        selected=[l['path'] for l in self.w.selected_layers() if Path(l['path']).suffix.lower() in ('.las','.laz')]
        if (compare and len(selected)<2) or (not compare and len(selected)!=1):
            self.visibility_note.set('Select two or more loaded clouds to compare.' if compare else 'Select exactly one loaded cloud to solo.');return
        if any(p not in self.v.paths for p in selected):
            self.visibility_note.set('Load the selected clouds into the viewer first.');return
        if self.previous is None:
            self.previous=(tuple(self.v.paths),[b.get() for b in self.v.visible],self.v.mode.get())
        for path,visible in zip(self.v.paths,self.v.visible):visible.set(path in selected)
        if compare:self.v.mode.set('Dataset')
        palette=('cyan','orange','green','purple','pink','yellow','teal','lavender')
        legend='; '.join(palette[i%8]+': '+Path(path).name for i,path in enumerate(self.v.paths) if path in selected)
        self.visibility_note.set(('Compare — '+legend if compare else 'Solo: '+Path(selected[0]).name)+' Display only; section source is separate.')
        self.v.draw();self.w.refresh_layers();self.w.persist()

    def restore(self):
        if self.previous is None:return
        paths,shown,mode=self.previous
        if self.v.busy:return
        if tuple(self.v.paths)!=paths:
            self.previous=None;self.visibility_note.set('Cloud list changed; previous visibility cannot be restored.');return
        for var,value in zip(self.v.visible,shown):var.set(value)
        self.v.mode.set(mode);self.previous=None
        self.visibility_note.set('Previous cloud visibility and coloring restored.')
        self.v.draw();self.w.refresh_layers();self.w.persist()

    def context(self):
        w=self.w;crs=self.v.scene[5] if self.v.scene is not None else None
        active=w.app.cloud_path.get()
        version=w.tracker.data.get('cloud_versions',{}).get(active)
        stage=None
        if version:
            stage=next((j['stage'] for j in w.tracker.data['jobs'] if j['id']==version.get('job')),None)
        source='Result: '+stage if stage else 'Registered result' if version and version.get('parent') else 'Version not established'
        units=', '.join(dict.fromkeys(a.unit_name for a in crs.axis_info)) if crs else 'unknown'
        return dict(workspace=str(w.path),directory=str(w.path.parent),active=active,
                    version=source,crs=crs.name if crs else 'No cloud CRS loaded',units=units)

    def update(self):
        c=self.context();name=Path(c['workspace']).name.removesuffix('.argus.json').removesuffix('.json')
        self.project.set('Workspace: '+name)
        self.dataset.set('Processing input: '+(Path(c['active']).name if c['active'] else 'None'))
        self.coordinates.set(c['crs']+' | '+c['units'])
        self.location.set('Workspace directory: '+c['directory']+'   |   '+c['version'])

    def details(self):
        c=self.context()
        messagebox.showinfo('Project context',
            f"Workspace: {c['workspace']}\nWorkspace directory: {c['directory']}\n\nProcessing input: {c['active'] or 'None'}\nVersion: {c['version']}\n\nLoaded cloud CRS: {c['crs']}\nAxis units: {c['units']}\nVertical datum: verify source metadata/project declaration.\n\nVisible clouds and section source are independent of the processing input.",parent=self.layout.root)
