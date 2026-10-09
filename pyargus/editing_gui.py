"""Complete-section editor, launched from the shared QA/section workspace."""
import queue
import threading
import time
from pathlib import Path
import numpy as np
from pyargus.editing import EditSession
from pyargus.review_gui import Plot


class SectionEditor:
    def __init__(self, parent, section):
        import tkinter as tk
        from tkinter import ttk
        self.session = EditSession(section)
        self.window = tk.Toplevel(parent); self.window.title('pyArgus — Classify section')
        self.window.geometry('1100x720'); self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.busy = False; self.saved_classes = self.session.original.copy()
        self.cancel = threading.Event(); self.messages = queue.Queue()
        self.vertices = []; self.selected = np.empty(0, dtype=int)
        ttk.Label(self.window,text=str(self.session.source),wraplength=1050).pack(anchor='w',padx=8)
        ttk.Label(self.window,text=f'All {len(section.points):,} corridor returns. Selection includes the FULL {section.width:g}-unit corridor depth. No class or flight-line filters.').pack(anchor='w',padx=8)
        ttk.Label(self.window,text='Rectangle: click two corners. Polygon: click vertices, then Finish polygon. Right-drag pans; wheel zooms.').pack(anchor='w',padx=8)
        bar=ttk.Frame(self.window); bar.pack(fill='x',padx=8,pady=6)
        self.mode=tk.StringVar(value='Rectangle')
        combo=ttk.Combobox(bar,textvariable=self.mode,values=('Rectangle','Polygon'),state='readonly',width=12)
        combo.pack(side='left'); combo.bind('<<ComboboxSelected>>',lambda e:self.clear())
        self.controls=[]
        for label,fn in [('Finish polygon',self.finish),('Clear selection',self.clear),('Fit',lambda:self.plot.fit())]:
            button=ttk.Button(bar,text=label,command=fn);button.pack(side='left');self.controls.append(button)
        ttk.Label(bar,text='Class:').pack(side='left')
        self.target=tk.StringVar(value='2')
        ttk.Entry(bar,textvariable=self.target,width=5).pack(side='left')
        for label,fn in [('Assign',self.assign),('Undo',self.undo),('Redo',self.redo),('Export LAS/LAZ…',self.export)]:
            button=ttk.Button(bar,text=label,command=fn);button.pack(side='left');self.controls.append(button)
        ttk.Button(bar,text='Cancel export',command=self.cancel.set).pack(side='left')
        ttk.Label(self.window,text=f'Common classes: 1 unclassified · 2 ground · 3/4/5 vegetation · 6 building · 7 low noise · 9 water. Supported range: 0–{self.session.max_class}.').pack(anchor='w',padx=8)
        self.status=tk.StringVar();ttk.Label(self.window,textvariable=self.status,wraplength=1050).pack(fill='x',padx=8)
        self.plot=Plot(self.window,'Station from A (map units)','Elevation (1:1)',self.pick)
        draw=self.plot.draw
        def overlay():
            draw()
            if len(self.vertices)>1:
                self.plot.canvas.create_line(*self.plot.screen(self.vertices).ravel(),fill='#ffcf40',width=2)
            for vertex in self.vertices:
                x,y=self.plot.screen(vertex);self.plot.canvas.create_oval(x-3,y-3,x+3,y+3,fill='#ffcf40')
        self.plot.draw=overlay
        self.plot.set(self.session.points[:,[3,2]],self.colors());self.refresh()
        self.poll_id=self.window.after(100,self.poll)

    def error(self,exc):
        from tkinter import messagebox
        messagebox.showerror('Classification editing',str(exc),parent=self.window)

    def colors(self):
        from pyargus.stage_preview import class_colors
        rgb=class_colors(self.session.classes).copy();rgb[self.selected]=[255,255,255];return rgb

    def refresh(self):
        self.plot.rgb=self.colors();self.plot.draw()
        self.status.set(f'{len(self.selected):,} selected (white) | {self.session.changed:,} changed from source | Undo {len(self.session.undo_stack)} / Redo {len(self.session.redo_stack)} | Export writes the full source cloud to a new file.')

    def clear(self):
        if self.busy:return
        self.vertices=[];self.selected=np.empty(0,dtype=int);self.refresh()

    def pick(self,point):
        if self.busy:return
        self.vertices.append(point.tolist())
        if self.mode.get()=='Rectangle' and len(self.vertices)==2:
            a,b=self.vertices
            self.vertices=[a,[b[0],a[1]],b,[a[0],b[1]]];self.finish()
        else:self.plot.draw()

    def finish(self):
        if self.busy:return
        try:
            self.selected=self.session.select(self.vertices);self.vertices=[];self.refresh()
        except Exception as exc:self.error(exc)

    def assign(self):
        if self.busy:return
        try:
            if not len(self.selected):raise ValueError('Select points before assigning a class.')
            self.session.assign(self.selected,int(self.target.get()));self.refresh()
        except Exception as exc:self.error(exc)

    def undo(self):
        if not self.busy:self.session.undo();self.refresh()

    def redo(self):
        if not self.busy:self.session.redo();self.refresh()

    def export(self):
        from tkinter import filedialog
        if self.busy:return
        if not self.session.changed:self.error('There are no pending classification changes.');return
        path=filedialog.asksaveasfilename(parent=self.window,defaultextension='.las',filetypes=(('LAS point cloud','*.las'),('Compressed LAZ point cloud','*.laz')))
        if not path:return
        self.busy=True;self.cancel.clear();self.started=time.monotonic();self.progress='Preparing export'
        for button in self.controls:button.configure(state='disabled')
        def run():
            try:
                result=self.session.export(path,cancel=self.cancel,progress=lambda s:self.messages.put(('progress',s)))
                self.messages.put(('done',result))
            except Exception as exc:self.messages.put(('error',str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,value=self.messages.get_nowait()
                if kind=='progress':self.progress=value;continue
                self.busy=False
                for button in self.controls:button.configure(state='normal')
                if kind=='done':
                    self.saved_classes=self.session.classes.copy()
                    self.status.set(f"VERIFIED: {value['changed']:,} classifications changed; {value['points']:,} full-cloud point records checked. {value['output']} — add this output to the main viewer to review.")
                else:self.status.set('Export stopped or failed: '+value)
        except queue.Empty:pass
        if self.busy:self.status.set(f'{self.progress} | Elapsed {time.monotonic()-self.started:.0f}s')
        self.poll_id=self.window.after(100,self.poll)

    def close(self):
        from tkinter import messagebox
        if self.busy:
            self.cancel.set();self.status.set('Cancelling export; close again after it stops.');return False
        if not np.array_equal(self.session.classes,self.saved_classes):
            if not messagebox.askyesno('Unsaved edits','Discard classification edits not included in your last export?',parent=self.window):return False
        self.window.after_cancel(self.poll_id);self.window.destroy()
        return True
