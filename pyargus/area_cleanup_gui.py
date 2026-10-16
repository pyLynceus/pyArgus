"""Polygon cleanup controls in the existing 3D review viewer."""
import queue
import threading
import time
from pathlib import Path
import numpy as np
from pyargus.area_cleanup import AreaEditSession, extract_area, screen_to_map
from pyargus.editing import polygon_mask


class AreaCleanup:
    def __init__(self, workspace):
        self.w = workspace; self.v = workspace.viewer
        self.window = None; self.session = None; self.drawing = False; self.busy = False
        self.polygon = []; self.saved_classes = None
        self.cancel = threading.Event(); self.messages = queue.Queue()
        self.v.cleanup_tool = self
        self.v.canvas.bind('<Escape>', self.escape, add='+')

    def error(self, exc):
        from tkinter import messagebox
        messagebox.showerror('Area cleanup', str(exc), parent=self.window or self.w.root)

    def open(self):
        import tkinter as tk
        from tkinter import ttk
        if self.window is not None and self.window.winfo_exists():
            self.window.lift(); return
        paths = list(self.w.project_panel.clouds)
        if not paths or self.v.scene is None:
            self.error('Load the active project clouds first.'); return
        self.window = tk.Toplevel(self.w.root); self.window.title('pyArgus — Area cleanup')
        self.window.geometry('660x600'); self.window.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(self.window, padding=12); body.pack(fill='both', expand=True)
        ttk.Label(body, text='1. Choose one active cloud and draw an area', font=('Segoe UI',11,'bold')).pack(anchor='w')
        self.source = tk.StringVar(value=self.w.app.cloud_path.get() if self.w.app.cloud_path.get() in paths else paths[0])
        chooser = ttk.Combobox(body, textvariable=self.source, values=paths, state='readonly', width=75)
        chooser.pack(fill='x', pady=5)
        self.inputs = [(chooser, 'readonly')]; self.controls = []
        ttk.Label(body, text='XY and height use the source CRS units. This edits one flight at a time; other overlapping clouds remain unchanged.', wraplength=625).pack(anchor='w')
        bar = ttk.Frame(body); bar.pack(fill='x', pady=6)
        for name, action in [('Draw polygon', self.start), ('Finish polygon', self.finish), ('Back one corner', self.back)]:
            self.button(bar, name, action)
        self.vertices_note = tk.StringVar(value='No polygon yet.'); ttk.Label(body, textvariable=self.vertices_note).pack(anchor='w')
        ttk.Label(body, text='Click corners in Top view. Right-drag pans; wheel zooms. Esc stops drawing. Then orbit or enable stereo to review the selected area.', wraplength=625).pack(anchor='w', pady=4)
        limits = ttk.LabelFrame(body, text='Explicit selection limits — independent of viewer filters', padding=8)
        limits.pack(fill='x', pady=8)
        self.classes = tk.StringVar(value='2'); self.line = tk.StringVar(value='All')
        self.z_min = tk.StringVar(); self.z_max = tk.StringVar()
        for row,(name,var,hint) in enumerate([
            ('Classes', self.classes, '2 = ground; All or comma-separated numbers'),
            ('LAS line ID', self.line, 'All or one source line ID'),
            ('Minimum Z', self.z_min, 'Blank = no lower height limit'),
            ('Maximum Z', self.z_max, 'Blank = no upper height limit')]):
            ttk.Label(limits, text=name).grid(row=row,column=0,sticky='w')
            entry = ttk.Entry(limits,textvariable=var,width=15); entry.grid(row=row,column=1,padx=8,pady=2)
            self.inputs.append((entry,'normal')); ttk.Label(limits,text=hint).grid(row=row,column=2,sticky='w')
        self.button(body,'2. Read full-resolution area',self.scan)
        self.summary = tk.StringVar(value='Read the area before assigning a class. Oversized selections are refused; edits never use a display sample.')
        ttk.Label(body,textvariable=self.summary,wraplength=625).pack(fill='x',pady=8)
        edit = ttk.Frame(body); edit.pack(fill='x',pady=5)
        ttk.Label(edit,text='3. Reclassify selected returns to').pack(side='left')
        self.target=tk.StringVar(value='1'); entry=ttk.Entry(edit,textvariable=self.target,width=5); entry.pack(side='left',padx=6)
        self.inputs.append((entry,'normal'))
        for name,action in [('Assign',self.assign),('Undo',self.undo),('Redo',self.redo)]:self.button(edit,name,action)
        self.button(body,'4. Export verified cloud and use for processing…',self.export)
        ttk.Label(body,text='Export retains every source point and changes classification only. The new version requires review; dependent QA, alignment review, surfaces and contours become outdated.',wraplength=625).pack(anchor='w',pady=5)
        footer=ttk.Frame(body);footer.pack(fill='x',pady=5)
        ttk.Button(footer,text='Stop scan / export',command=self.cancel.set).pack(side='left')
        ttk.Button(footer,text='Job history / rebuild status',command=lambda:self.w.layout.show_panel(self.w.progress_tab)).pack(side='left',padx=5)
        self.status=tk.StringVar(value='Ready');ttk.Label(body,textvariable=self.status,wraplength=625).pack(fill='x')
        self.loaded_key = None; self.session = None; self.saved_classes = None; self.polygon = []
        self.poll_id=self.window.after(100,self.poll)

    def button(self,parent,label,action):
        from tkinter import ttk
        b=ttk.Button(parent,text=label,command=action)
        b.pack(side='left',padx=2) if parent.winfo_class()=='TFrame' and parent is not self.window.winfo_children()[0] else b.pack(anchor='w',pady=3)
        self.controls.append(b)
        return b

    def discard(self):
        from tkinter import messagebox
        if self.session is not None and not np.array_equal(self.session.classes,self.saved_classes):
            return messagebox.askyesno('Unsaved cleanup','Discard classification edits not included in your last export?',parent=self.window)
        return True

    def start(self):
        if self.busy:return
        if self.v.busy or self.w.app.runner.running or self.w.review.busy:
            self.error('Finish or stop the current job before drawing a cleanup area.');return
        if not self.discard():return
        self.session=None;self.loaded_key=None;self.polygon=[]
        self.summary.set('Read the new full-resolution area before assigning a class.')
        self.w.layout.corridor.enabled.set(False);self.w.layout.corridor.toggle()
        self.v.choose_pivot=False;self.v.orbit_anchor=None;self.v.stereo.set(False)
        self.v.view(self.v.yaw,90)  # retain center, zoom and pan
        self.drawing=True;self.v.canvas.configure(cursor='crosshair');self.v.canvas.focus_set()
        self.status.set('Click polygon corners in the main viewer; Finish polygon when done.');self.update_polygon()

    def press(self,event):
        if not self.drawing:return False
        self.v.orbit_anchor=None
        if self.busy:return True
        if self.v.stereo.get() or abs(self.v.pitch-90)>1e-6:
            self.drawing=False;self.v.canvas.configure(cursor='');self.status.set('Drawing stopped: return to Top view and click Draw polygon.');return True
        self.polygon.append(screen_to_map(self.v,event.x,event.y).tolist());self.update_polygon()
        return True

    def back(self):
        if not self.busy and self.drawing and self.polygon:self.polygon.pop();self.update_polygon()

    def update_polygon(self):
        self.vertices_note.set(f'{len(self.polygon)} polygon corners'+(' — drawing' if self.drawing else ''))
        self.v.draw()

    def finish(self):
        if self.busy:return
        try:polygon_mask(np.empty((0,2)),self.polygon)
        except ValueError as exc:self.error(exc);return
        self.drawing=False;self.v.orbit_anchor=None;self.v.canvas.configure(cursor='');self.update_polygon()
        self.status.set('Polygon ready. Set explicit limits, then read the full-resolution area.')

    def escape(self,event=None):
        if not self.drawing:return
        self.drawing=False;self.v.orbit_anchor=None;self.v.canvas.configure(cursor='');self.update_polygon()
        self.status.set('Drawing stopped. Existing corners retained; Finish polygon to use them.');return 'break'

    def definition(self):
        source=str(Path(self.source.get()).resolve())
        if source not in self.w.project_panel.clouds:raise ValueError('Source is no longer an active processing version. Reopen Area cleanup.')
        classes=None if self.classes.get().strip().lower()=='all' else [int(v.strip()) for v in self.classes.get().split(',')]
        line=None if self.line.get().strip().lower()=='all' else int(self.line.get())
        low=None if not self.z_min.get().strip() else float(self.z_min.get())
        high=None if not self.z_max.get().strip() else float(self.z_max.get())
        polygon_mask(np.empty((0,2)),self.polygon)
        return source,dict(polygon=[list(p) for p in self.polygon],classes=classes,line_id=line,z_min=low,z_max=high)

    def key(self):return repr(self.definition())

    def launch(self,work,kind):
        self.busy=True;self.cancel.clear();self.started=time.monotonic();self.progress='Preparing '+kind
        for b in self.controls:b.configure(state='disabled')
        for widget,_ in self.inputs:widget.configure(state='disabled')
        def run():
            try:self.messages.put((kind,work()))
            except Exception as exc:self.messages.put(('error',exc))
        threading.Thread(target=run,daemon=True).start()

    def scan(self):
        if self.busy:return
        try:
            if self.v.busy or self.w.app.runner.running or self.w.review.busy:raise ValueError('Finish or stop the current job before reading an area.')
            source,options=self.definition()
            if self.drawing:self.finish()
            if self.drawing:return
            if not self.discard():return
            self.session=None;self.loaded_key=None;self.v.draw()
            self.summary.set('Reading the current polygon and explicit limits; no edits are active.')
            self.scan_key=repr((source,options));self.scan_tracker=self.w.tracker
            self.launch(lambda:extract_area(source,**options,cancel=self.cancel,progress=lambda s:self.messages.put(('progress',s))),'area')
        except Exception as exc:self.error(exc)

    def valid_session(self):
        if self.session is None:raise ValueError('Read a full-resolution area first.')
        if self.w.tracker is not self.scan_tracker or self.key()!=self.loaded_key:
            raise ValueError('Source, polygon or limits changed. Read the area again before editing or exporting.')
        self.session.check_source()

    def refresh(self):
        if self.session is None:return
        s=self.session;unique,counts=np.unique(s.classes,return_counts=True)
        classes=', '.join(f'class {int(c)}: {int(n):,}' for c,n in zip(unique,counts))
        low,high=s.points[:,2].min(),s.points[:,2].max()
        self.summary.set(f'{len(s.points):,} full-resolution selected returns / {s.area.in_polygon:,} inside polygon. Z {low:.3f} to {high:.3f}. {classes}. {s.changed:,} changed; Undo {len(s.undo_stack)} / Redo {len(s.redo_stack)}. White overlay previews up to 50,000 selected returns, independent of viewer filters.')
        self.v.draw()

    def assign(self):
        if self.busy:return
        try:self.valid_session();self.session.assign(np.arange(len(self.session.points)),int(self.target.get()));self.refresh()
        except Exception as exc:self.error(exc)

    def undo(self):
        if not self.busy and self.session is not None:self.session.undo();self.refresh()

    def redo(self):
        if not self.busy and self.session is not None:self.session.redo();self.refresh()

    def export(self,path=None):
        from tkinter import filedialog
        from pyargus.job_manifest import JobRecord,identity
        if self.busy:return
        try:
            self.valid_session()
            if self.drawing:raise ValueError('Finish the polygon first.')
            if self.v.busy or self.w.app.runner.running or self.w.review.busy:raise ValueError('Finish the current job before exporting.')
            if not self.session.changed:raise ValueError('Assign a class before exporting.')
            source=str(self.session.source.resolve())
            bindings={self.w.project_panel.bindings[p] for p in self.w.project_panel.clouds
                      if self.w.tracker.cloud_root(p)==self.w.tracker.cloud_root(source) and p in self.w.project_panel.bindings}
            if len(bindings)>1:raise ValueError('Resolve conflicting trajectory bindings before exporting.')
            if path is None:
                path=filedialog.asksaveasfilename(parent=self.window,initialdir=str(self.session.source.parent),
                    initialfile=self.session.source.stem+'_cleanup_01.las',defaultextension='.las',
                    filetypes=(('LAS point cloud','*.las'),('Compressed LAZ point cloud','*.laz')))
            if not path:return
            settings=dict(cloud=source,operation='manual-area-cleanup',area=self.session.area.definition())
            self.export_tracker=self.w.tracker
            self.export_job=self.export_tracker.begin('Classification',settings,[source])
            self.export_job.update(source='imported',stage_class='ClassifyStage')
            self.w.persist();self.w.refresh()
            record=JobRecord('manual-area-cleanup',path,settings)
            record.data['inputs']=[self.session.identity]
            self.export_job['records']=[str(record.path)]
            self.w.persist()
            def work():
                with record:
                    try:
                        report=self.session.export(path,cancel=self.cancel,progress=lambda s:self.messages.put(('progress',s)))
                    except InterruptedError as exc:
                        record._cancelled_exception=exc;record.finish('cancelled',{});raise
                    sidecar=str(Path(report['output']).with_suffix(Path(report['output']).suffix+'.edits.json'))
                    record.data['outputs']=[identity(report['output']),identity(sidecar)]
                    record.finish('completed',{k:report[k] for k in ('points','changed','source_record_sha256','output_record_sha256')})
                return report
            self.launch(work,'exported')
        except Exception as exc:self.error(exc)

    def adopted(self,report):
        output=report['output'];job=self.export_job
        self.saved_classes=self.session.classes.copy()
        self.export_tracker.finish(job,'Needs review',[output,output+'.edits.json',*job['records']],elapsed=time.monotonic()-self.started)
        if self.w.tracker is not self.export_tracker or str(self.session.source.resolve()) not in self.w.project_panel.clouds:
            raise ValueError('Active workspace/source changed during export. Verified cloud is saved at '+output+'; import its job record to review it before promotion.')
        self.session.check_source()
        self.w.tracker.register_cloud_result(str(self.session.source),output,job['id'])
        self.w.add_layer(output,'output',job['id']);self.w.add_layer(output+'.edits.json','output',job['id'])
        job['notes'].append('Manual polygon cleanup; XYZ unchanged. Review new cloud, rerun project ground QA, review alignment, rebuild surface/contours, then final QA and delivery.')
        # Prevent the scan's old source from remaining an editable active version.
        self.session=None;self.loaded_key=None;self.polygon=[];self.vertices_note.set('Export completed. Reopen this tool for another area.')
        self.w.viewer.mode.set('Classification')
        self.w.activate_cloud_version(output,preserve_view=True)
        self.w.refresh();self.w.history();self.w.persist()
        self.summary.set(f"VERIFIED: {report['changed']:,} classifications changed; all {report['points']:,} point records checked. New active version: {output}")
        self.status.set('Needs review. Job history identifies outdated results. Choose another active cloud by reopening this tool.')
        self.source.set(output);self.inputs[0][0].configure(values=list(self.w.project_panel.clouds))
        self.export_job=None

    def poll(self):
        try:
            while True:
                kind,value=self.messages.get_nowait()
                if kind=='progress':self.progress=value;continue
                self.busy=False
                for b in self.controls:b.configure(state='normal')
                for widget,state in self.inputs:widget.configure(state=state)
                try:
                    if kind=='area':
                        if self.w.tracker is not self.scan_tracker or self.key()!=self.scan_key:raise ValueError('Workspace or selection changed during scan; read the area again.')
                        self.session=AreaEditSession(value);self.saved_classes=self.session.original.copy();self.loaded_key=self.scan_key
                        self.refresh();self.status.set('Full-resolution selection ready. Review in 3D; Assign changes every selected return.')
                    elif kind=='exported':self.adopted(value)
                    else:
                        job=getattr(self,'export_job',None)
                        if job is not None:
                            self.export_tracker.finish(job,'Cancelled' if isinstance(value,InterruptedError) else 'Failed',error=str(value),elapsed=time.monotonic()-self.started)
                            self.export_job=None;self.w.persist();self.w.refresh()
                        self.status.set('Stopped or failed: '+str(value))
                except Exception as exc:
                    self.status.set('Result saved, but workspace update failed: '+str(exc) if kind=='exported' else str(exc))
                    self.w.persist();self.w.refresh()
        except queue.Empty:pass
        if self.busy:self.status.set(f'{self.progress} | Elapsed {time.monotonic()-self.started:.0f}s')
        self.poll_id=self.window.after(100,self.poll)

    def preview_points(self):
        if self.session is None or str(self.session.source.resolve()) not in self.v.paths:return np.empty((0,3))
        return self.session.points[::max(1,int(np.ceil(len(self.session.points)/50000)))]

    def paint(self,pixels,scale,width,height):
        from pyargus.viewer3d import project_points
        points=self.preview_points()
        if not len(points):return
        xy=np.rint(project_points(points,self.v.center,self.v.yaw,self.v.pitch)[:,:2]*[scale,-scale]+[width/2,height/2]+self.v.pan).astype(int)
        keep=(xy[:,0]>=0)&(xy[:,0]<width)&(xy[:,1]>=0)&(xy[:,1]<height)
        xy=xy[keep];pixels[xy[:,1],xy[:,0]]=[255,255,255]

    def draw(self):
        if self.window is None or not self.polygon or self.v.scene is None:return
        if self.drawing and (self.v.stereo.get() or abs(self.v.pitch-90)>1e-6):self.escape()
        if self.v.stereo.get():return
        from pyargus.viewer3d import project_points
        xyz=np.column_stack([self.polygon,np.full(len(self.polygon),self.v.center[2])])
        width,height=self.v.canvas.winfo_width(),self.v.canvas.winfo_height();scale=min(max(2,width),max(2,height))*.85/self.v.span*self.v.zoom
        xy=project_points(xyz,self.v.center,self.v.yaw,self.v.pitch)[:,:2]*[scale,-scale]+[width/2,height/2]+self.v.pan
        if len(xy)>1:
            line=xy if self.drawing else np.vstack([xy,xy[0]])
            self.v.canvas.create_line(*line.ravel(),fill='#ffcf40',width=2,dash=(5,3),tags='cleanup-polygon')
        for x,y in xy:self.v.canvas.create_oval(x-3,y-3,x+3,y+3,fill='#ffcf40',tags='cleanup-polygon')

    def close(self):
        if self.busy:
            self.cancel.set();self.status.set('Cancelling; close again after the job stops.');return False
        if self.window is None:return True
        if not self.discard():return False
        self.window.after_cancel(self.poll_id);self.window.destroy();self.window=None
        self.drawing=False;self.session=None;self.polygon=[];self.loaded_key=None
        self.v.canvas.configure(cursor='');self.v.draw();return True
