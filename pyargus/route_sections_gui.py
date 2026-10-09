"""Line-following section controls using the existing section extraction worker."""
from copy import deepcopy
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import numpy as np
from pyargus.route_sections import route_xy,corridor_at


class RouteSections:
    def __init__(self,review,parent,manual_bar):
        self.review=review;self.manual_bar=manual_bar;self.layers=lambda:[];self.state=None;self.on_activate=lambda:None
        self.is_active=lambda:str(review.tabs.select())==str(review.inspect_tab)
        self.frame=ttk.Frame(parent);self.frame.pack(fill='x',pady=3)
        ttk.Button(self.frame,text='Follow DXF line…',command=lambda:self.run(self.choose)).pack(side='left')
        self.note=tk.StringVar(value='Sections perpendicular to one imported line; distances use XY map units.')
        ttk.Label(self.frame,textvariable=self.note,width=1,anchor='w').pack(side='left',fill='x',expand=True)
        self.controls=ttk.Frame(parent)
        self.station=tk.StringVar(value='0');self.span=tk.StringVar(value='100')
        for label,var in [('Station',self.station),('Across-line span',self.span),('Spacing',review.step_distance)]:
            ttk.Label(self.controls,text=label).pack(side='left');ttk.Entry(self.controls,textvariable=var,width=10).pack(side='left')
        for text,fn in [('Previous',lambda:self.go(-1)),('Next',lambda:self.go(1)),('Go / extract',self.go),('Stop following',self.stop)]:
            ttk.Button(self.controls,text=text,command=lambda f=fn:self.run(f)).pack(side='left',padx=2)
        ttk.Label(self.controls,text='Alt+← / → on view or profile').pack(side='left',padx=5)

    def run(self,fn):
        if self.review.busy:return
        try:return fn()
        except Exception as exc:self.review.error(exc)

    def bind_keys(self,canvas):
        canvas.bind('<ButtonPress-1>',lambda e:canvas.focus_set(),add='+')
        for key,direction in [('<Alt-Left>',-1),('<Alt-Right>',1)]:
            canvas.bind(key,lambda e,d=direction:self.key(d),add='+')

    def key(self,direction):
        if self.state is not None and self.is_active():
            self.run(lambda:self.go(direction));return 'break'

    def layer(self,state=None,verify=True):
        from pyargus.job_manifest import identity
        state=state or self.state
        if state is None:raise ValueError('Choose an imported line first.')
        layer=next((x for x in self.layers() if x['id']==state['layer']),None)
        if layer is None:raise ValueError('The route layer was removed. Choose a line again.')
        if state['source']!=layer['source']:raise ValueError('Route source changed; choose a line again.')
        if verify and identity(layer['source']['path'])!=layer['source']:
            raise ValueError('DXF changed since import. Reimport it before following this route.')
        index=state['segment']
        if not isinstance(index,int) or not 0<=index<len(layer['segments']):raise ValueError('Route entity is unavailable.')
        return layer,layer['segments'][index]

    def activate(self,layer,index):
        """Choose a single entity, without starting expensive extraction."""
        if self.review.busy:return
        state=dict(layer=layer['id'],segment=index,source=deepcopy(layer['source']),station=0.,span=100.,width=float(self.review.width.get()),spacing=float(self.review.step_distance.get()))
        _,vertices=self.layer(state)
        corridor_at(vertices,0,state['span'],state['width'])
        self.restore(state)
        self.on_activate()

    def restore(self,state):
        self.stop()
        if state is None:return
        try:
            layer,vertices=self.layer(state,verify=False)
            _,_,total=corridor_at(vertices,float(state['station']),float(state['span']),float(state['width']))
            if not np.isfinite(float(state['spacing'])) or float(state['spacing'])<=0:raise ValueError('Invalid spacing.')
            self.state=deepcopy(state)
            self.station.set(str(state['station']));self.span.set(str(state['span']))
            self.review.width.set(str(state['width']));self.review.step_distance.set(str(state['spacing']))
            self.manual_bar.pack_forget();self.controls.pack(fill='x',pady=3,after=self.frame)
            self.note.set(f"{layer['name']} / entity {state['segment']+1} | length {total:.3f} | A left → B right. Go to extract.")
        except (KeyError,TypeError,ValueError,IndexError) as exc:
            self.note.set('Saved route unavailable: '+str(exc))

    def stop(self):
        self.state=None;self.controls.pack_forget()
        self.manual_bar.pack(fill='x',pady=3,before=self.frame)
        self.note.set('Manual A/B sections. Choose a DXF line to follow it.')

    def choose(self,only_layer=None):
        if self.review.busy:return
        candidates=[];labels=[]
        for layer in self.layers():
            if only_layer is not None and layer['id']!=only_layer['id']:continue
            for index,vertices in enumerate(layer['segments']):
                try:total=route_xy(vertices)[2][-1]
                except ValueError:continue
                candidates.append((layer,index))
                labels.append(f"{len(labels)+1}. {layer['name']} | entity {index+1} | {total:.3f} map units | {Path(layer['source']['path']).name}")
        if not candidates:raise ValueError('Import DXF linework first. Points and vertical-only entities cannot define an XY route.')
        dialog=tk.Toplevel(self.frame);dialog.title('Choose section route');dialog.transient(self.frame.winfo_toplevel());dialog.grab_set()
        ttk.Label(dialog,text='One entity per route; disconnected lines are not joined. Station 0 is its first vertex.').pack(padx=12,pady=8)
        selected=tk.StringVar(value=labels[0]);choice=ttk.Combobox(dialog,values=labels,textvariable=selected,state='readonly',width=100);choice.pack(padx=12)
        def use():
            try:
                if self.review.busy:raise ValueError('Wait for the current section operation.')
                self.activate(*candidates[choice.current()]);dialog.destroy()
            except Exception as exc:self.review.error(exc)
        ttk.Button(dialog,text='Use line',command=use).pack(pady=10)

    def go(self,direction=0):
        if self.review.busy:return
        from pyproj import CRS
        r=self.review
        if not r.loaded_paths or r.scene is None:raise ValueError('Load clouds and choose a Section source first.')
        r.section_paths()  # Do not move the corridor if the source is ambiguous.
        layer,vertices=self.layer()
        if CRS(layer['crs'])!=r.scene[5]:raise ValueError('Route and loaded clouds must share their projected CRS.')
        station=float(self.station.get());span=float(self.span.get());spacing=float(r.step_distance.get());width=float(r.width.get())
        if not np.isfinite(spacing) or spacing<=0:raise ValueError('Spacing must be finite and positive.')
        _,_,total=corridor_at(vertices,station,span,width)
        if direction not in (-1,0,1):raise ValueError('Invalid route direction.')
        target=float(np.clip(station+direction*spacing,0,total))
        if direction and target==station:
            self.note.set('End of route.' if direction>0 else 'Start of route.');return
        a,b,_=corridor_at(vertices,target,span,width)
        self.state.update(station=target,span=span,width=width,spacing=spacing)
        self.station.set(repr(target));r.endpoint=None
        for var,value in zip(r.coords,[*a,*b]):var.set(repr(float(value)))
        self.note.set(f"{layer['name']} / entity {self.state['segment']+1} | requested station {target:.3f} / {total:.3f} | A left → B right")
        r.extract()

    def manual_changed(self):
        if self.state is None:return
        try:
            _,vertices=self.layer(verify=False)
            a,b,_=corridor_at(vertices,self.state['station'],self.state['span'],self.state['width'])
            same=np.allclose([float(x.get()) for x in self.review.coords],[*a,*b],rtol=0,atol=1e-7)
        except (ValueError,TypeError,KeyError):same=False
        if not same:self.stop()
