"""Geometry and mouse handling for a read-only section corridor in Top view."""
import math
import numpy as np


def drag_corridor(kind, start, end, width, pressed, pointer, minimum=1e-6):
    from pyargus.sections import section_coordinates
    a,b=np.array(start,dtype=float),np.array(end,dtype=float)
    section_coordinates([],[],a,b,width)
    p,q=np.array(pressed,dtype=float),np.array(pointer,dtype=float)
    if p.shape!=(2,) or q.shape!=(2,) or not np.isfinite([*p,*q,minimum]).all() or minimum<=0:
        raise ValueError('Drag coordinates and minimum size must be finite and valid.')
    delta=q-p;axis=b-a;length=np.linalg.norm(axis);normal=np.array([-axis[1],axis[0]])/length
    if kind=='move':a+=delta;b+=delta
    elif kind=='a':a+=delta
    elif kind=='b':b+=delta
    elif kind=='width':width=max(minimum,float(width+2*np.dot(delta,normal)))
    elif kind=='rotate':
        center=(a+b)/2;u=p-center;v=q-center
        if min(np.linalg.norm(u),np.linalg.norm(v))<minimum:raise ValueError('Move the rotation handle away from the center.')
        angle=math.atan2(v[1],v[0])-math.atan2(u[1],u[0])
        c,s=math.cos(angle),math.sin(angle);rotation=np.array([[c,-s],[s,c]])
        a=center+rotation@(a-center);b=center+rotation@(b-center)
    else:raise ValueError('Unknown section handle.')
    if np.linalg.norm(b-a)<minimum:raise ValueError('Section length is too small.')
    section_coordinates([],[],a,b,width)
    return a,b,float(width)


class CorridorEditor:
    def __init__(self,workspace):
        import tkinter as tk
        self.w=workspace;self.v=workspace.viewer;self.review=workspace.review
        self.enabled=tk.BooleanVar(value=False);self.auto_extract=tk.BooleanVar(value=False)
        self.drag=None;self.v.corridor_editor=self
        self.v.canvas.bind('<Escape>',self.escape,add='+')

    def ready(self):
        return (self.enabled.get() and self.v.scene is not None and not self.v.stereo.get()
                and abs(self.v.pitch-90)<1e-6 and self.w.show_dock.get()
                and self.w.tabs.select()==str(self.w.review_tab))

    def scale(self):
        return min(max(2,self.v.canvas.winfo_width()),max(2,self.v.canvas.winfo_height()))*.85/self.v.span*self.v.zoom

    def screen(self,xy):
        from pyargus.viewer3d import project_points
        v=self.v;xyz=np.column_stack([np.atleast_2d(xy),np.full(len(np.atleast_2d(xy)),v.center[2])])
        return project_points(xyz,v.center,v.yaw,v.pitch)[:,:2]*[self.scale(),-self.scale()]+[v.canvas.winfo_width()/2,v.canvas.winfo_height()/2]+v.pan

    def map_xy(self,e):
        v=self.v;q=(np.array([e.x,e.y])-[v.canvas.winfo_width()/2,v.canvas.winfo_height()/2]-v.pan)/[self.scale(),-self.scale()]
        angle=math.radians(v.yaw);right=np.array([math.cos(angle),math.sin(angle)]);up=np.array([-math.sin(angle),math.cos(angle)])
        return v.center[:2]+q[0]*right+q[1]*up

    def handles(self):
        if not self.ready() or self.v.corridor is None:return {}
        a,b,width=self.v.corridor;axis=b-a;length=np.linalg.norm(axis)
        if length<=1e-9:return {}
        normal=np.array([-axis[1],axis[0]])/length;center=(a+b)/2
        # Offset the width handle in pixels so narrow corridors remain pickable.
        return dict(a=a,b=b,move=center,width=center+normal*(width/2+18/self.scale()),
                    rotate=center+normal*(width/2+53/self.scale()))

    def hit(self,e):
        handles=self.handles()
        if not handles:return None
        pointer=np.array([e.x,e.y]);names=list(handles);pixels=self.screen(list(handles.values()))
        distance=np.linalg.norm(pixels-pointer,axis=1);nearest=int(np.argmin(distance))
        if distance[nearest]<=9:return names[nearest]
        a,b,width=self.v.corridor;axis=b-a;length=np.linalg.norm(axis);q=self.map_xy(e)-a
        along=np.dot(q,axis/length);across=np.dot(q,[-axis[1]/length,axis[0]/length])
        if 0<=along<=length and abs(across)<=max(width/2,7/self.scale()):return 'move'
        return None

    def toggle(self):
        self.cancel()
        if not self.enabled.get():self.v.canvas.configure(cursor='');self.v.draw();return
        if self.v.scene is None or self.review.busy or self.v.busy:
            self.enabled.set(False);self.v.status.set('Load clouds and finish the current scan before editing a section.');return
        if (not self.w.show_dock.get() or self.w.tabs.select()!=str(self.w.review_tab)
                or self.w.layout.mode!='Review'):self.w.show_section_review()
        self.v.stereo.set(False);self.v.view(0,90)
        if self.v.corridor is None:
            center=self.v.center[:2];half=max(1.,self.v.canvas.winfo_width()*.2/self.scale())
            a,b=center+[-half,0],center+[half,0]
            try:width=float(self.review.width.get())
            except ValueError:width=3.
            if not np.isfinite(width) or width<=0:width=3.
            for var,value in zip(self.review.coords,[*a,*b]):var.set(repr(float(value)))
            self.review.width.set(repr(width));self.review.route.stop();self.review.set_corridor()
        self.v.choose_pivot=False;self.v.orbit_anchor=None;self.v.canvas.configure(cursor='crosshair');self.v.canvas.focus_set()
        self.v.status.set('Drag inside to move; A/B resize length; W changes width; R rotates. Esc cancels.');self.v.draw()

    def context(self):
        return (self.v.view_key(),tuple(v.get() for v in self.review.coords),self.review.width.get(),tuple(self.review.loaded_paths))

    def press(self,e):
        if not self.ready() or getattr(e,'state',0)&5:return False
        kind=self.hit(e)
        if kind is None:return False
        self.v.orbit_anchor=None
        if self.review.busy or self.v.busy:
            self.v.status.set('Finish or stop the current scan before dragging the section.');return True
        if self.auto_extract.get():
            try:self.review.section_paths()
            except ValueError as exc:self.v.status.set(str(exc));return True
        self.original=self.v.corridor;self.preview=self.original
        a,b,width=self.original
        self.drag=dict(kind=kind,a=a.copy(),b=b.copy(),width=width,pointer=self.map_xy(e),pixel=np.array([e.x,e.y]),context=self.context(),moved=False)
        self.v.canvas.focus_set();return True

    def motion(self,e):
        if self.drag is None:return False
        if not self.ready() or self.context()!=self.drag['context'] or getattr(e,'state',0)&5:
            self.cancel();self.v.status.set('Section drag cancelled because the view or definition changed.');return True
        if np.linalg.norm(np.array([e.x,e.y])-self.drag['pixel'])<3 and not self.drag['moved']:return True
        d=self.drag
        try:
            result=drag_corridor(d['kind'],d['a'],d['b'],d['width'],d['pointer'],self.map_xy(e),max(1e-6,2/self.scale()))
        except ValueError as exc:self.v.status.set(str(exc));return True
        self.preview=result;self.v.corridor=result;d['moved']=True;self.v.draw()
        self.v.status.set(f"Section preview: length {np.linalg.norm(result[1]-result[0]):.3f}, width {result[2]:.3f} map units. Release to apply.")
        return True

    def release(self,e):
        if self.drag is None:return False
        self.motion(e)
        if self.drag is None:return True
        if self.review.busy or self.v.busy:self.cancel();return True
        d=self.drag;result=self.preview;self.drag=None
        if not d['moved']:return True
        if np.array_equal(result[0],d['a']) and np.array_equal(result[1],d['b']) and result[2]==d['width']:
            self.v.corridor=self.original;self.v.draw();return True
        a,b,width=result;self.review.route.stop();self.review.endpoint=None
        for var,value in zip(self.review.coords,[*a,*b]):var.set(repr(float(value)))
        self.review.width.set(repr(width));self.review.set_corridor();self.w.persist()
        self.review.status.set('Section moved. Click Extract section, or enable Extract on release.')
        if self.auto_extract.get():self.review.extract()
        return True

    def cancel(self):
        if self.drag is not None:
            if self.v.corridor is self.preview:self.v.corridor=self.original
            self.drag=None;self.v.draw()

    def escape(self,e=None):
        if self.drag is not None:self.cancel();self.v.status.set('Section drag cancelled; original section retained.');return 'break'
        if self.enabled.get():self.enabled.set(False);self.toggle();self.v.status.set('Section handles off.');return 'break'

    def draw(self):
        handles=self.handles()
        if not handles:return
        v=self.v;pixels=dict(zip(handles,self.screen(list(handles.values()))))
        v.canvas.create_line(*pixels['move'],*pixels['rotate'],fill='#80e6ff',dash=(3,3),tags='section-handles')
        for name,(x,y) in pixels.items():
            if name=='move':v.canvas.create_oval(x-5,y-5,x+5,y+5,fill='#80e6ff',outline='#101925',tags='section-handles')
            else:v.canvas.create_rectangle(x-5,y-5,x+5,y+5,fill='#80e6ff',outline='#101925',tags='section-handles')
            v.canvas.create_text(x+9,y+9 if name=='move' else y-9,
                text=dict(a='A',b='B',width='W',rotate='R',move='Move')[name],fill='#80e6ff',
                anchor='nw' if name=='move' else 'sw',font=('Segoe UI',10,'bold'),tags='section-handles')
