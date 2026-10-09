"""Deliver a frozen review snapshot using the existing background job runner."""
from copy import deepcopy
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog

from pyargus import __version__
from pyargus.job_manifest import utc_now, identity
from pyargus.review_memory import ReviewMemory
from pyargus.review_package import export_package


def software_info():
    result = dict(pyargus=__version__, python=platform.python_version(), source_commit=None)
    if getattr(sys, 'frozen', False):
        result['executable'] = sys.executable
        try:
            result['source_commit'] = json.loads((Path(sys.executable).parent/'build-info.json').read_text(encoding='utf-8-sig'))['source_commit']
        except (OSError, ValueError, KeyError):
            pass
    else:
        try:
            commit = subprocess.run(['git','rev-parse','HEAD'], cwd=Path(__file__).resolve().parents[1],
                capture_output=True, text=True, timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if commit.returncode == 0:
                result['source_commit'] = commit.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def canvas_png(canvas, photo):
    """Capture the app's raster and 2D annotations without desktop screenshots."""
    from PIL import ImageTk, ImageDraw, ImageFont
    from tkinter import font as tkfont
    image = ImageTk.getimage(photo).convert('RGB'); draw = ImageDraw.Draw(image)
    def color(value):
        return tuple(c//256 for c in canvas.winfo_rgb(value)) if value else None
    for item in canvas.find_all():
        if canvas.itemcget(item, 'state') == 'hidden':
            continue
        kind = canvas.type(item); xy = canvas.coords(item)
        if kind == 'image' or not xy:
            continue
        fill = color(canvas.itemcget(item, 'fill'))
        width = max(1, round(float(canvas.itemcget(item, 'width') or 1))) if kind != 'text' else 1
        if kind == 'line':
            if fill:
                draw.line(list(zip(xy[::2],xy[1::2])), fill=fill, width=width)
        elif kind in ('oval','rectangle','polygon'):
            outline = color(canvas.itemcget(item, 'outline'))
            if kind == 'polygon':
                points = list(zip(xy[::2],xy[1::2])); draw.polygon(points, fill=fill)
                if outline:
                    draw.line(points+[points[0]], fill=outline, width=width)
            else:
                getattr(draw, 'ellipse' if kind == 'oval' else 'rectangle')(xy, fill=fill, outline=outline, width=width)
        elif kind == 'text':
            text = canvas.itemcget(item, 'text')
            actual = tkfont.Font(root=canvas, font=canvas.itemcget(item, 'font')).actual()
            size = abs(actual['size']) * (canvas.winfo_fpixels('1p') if actual['size'] > 0 else 1)
            try:
                font = ImageFont.truetype(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'), max(6, round(size)))
            except OSError:
                font = ImageFont.load_default()
            box = draw.multiline_textbbox((0,0),text,font=font); w,h = box[2]-box[0],box[3]-box[1]
            anchor = canvas.itemcget(item,'anchor'); x,y = xy[:2]
            x -= 0 if 'w' in anchor else w if 'e' in anchor else w/2
            y -= 0 if 'n' in anchor else h if 's' in anchor else h/2
            draw.multiline_text((x-box[0],y-box[1]),text,font=font,fill=fill or 'white')
    stream = io.BytesIO(); image.save(stream, format='PNG'); return stream.getvalue()


def profile_png(profile):
    """Readable offscreen profile even when the dock is hidden; retain plot state."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    width,height=1024,360;ex=profile.exaggeration
    scale=min((width-100)/profile.span[0],(height-65)/(profile.span[1]*ex))*.9*profile.zoom
    old_scale=profile.transform()[2][0]
    pan=profile.pan*scale/old_scale
    factors=np.array([scale,-scale*ex]);origin=np.array([width/2,height/2])+pan
    xy=np.rint((profile.xy-profile.center)*factors+origin).astype(np.int64)
    inside=(xy[:,0]>=0)&(xy[:,0]<width)&(xy[:,1]>=0)&(xy[:,1]<height)
    pixels=np.empty((height,width,3),dtype='uint8');pixels[:]=[16,25,37]
    pixels[xy[inside,1],xy[inside,0]]=profile.rgb[inside]
    image=Image.fromarray(pixels);draw=ImageDraw.Draw(image)
    try:font=ImageFont.truetype(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'),12)
    except OSError:font=ImageFont.load_default()
    for i in range(5):
        x=50+(width-100)*i/4;y=25+(height-65)*i/4
        station=(x-origin[0])/factors[0]+profile.center[0]
        elevation=(y-origin[1])/factors[1]+profile.center[1]
        draw.text((x,height-26),f'{station:.2f}',font=font,fill='#c5d0dd',anchor='mt')
        draw.text((4,y),f'{elevation:.2f}',font=font,fill='#c5d0dd')
    draw.text((5,3),profile.ylabel,font=font,fill='white')
    draw.text((width/2,height-11),profile.xlabel,font=font,fill='white',anchor='mm')
    stream=io.BytesIO();image.save(stream,format='PNG');return stream.getvalue()


class ReviewPackageExport:
    def __init__(self, layout):
        self.layout=layout; self.w=layout.w; self.v=layout.v; self.r=self.w.review; self.app=layout.app
        self.pending=None; self.result=None; self.last_path=None
        self.include_previews=tk.BooleanVar(value=True); self.include_section=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value='Export review records and references to a new ZIP. No cloud scan or stage approval.')
        self.frame=ttk.LabelFrame(layout.deliver,text='QA review package',padding=7); self.frame.pack(fill='x',pady=(15,3))
        ttk.Label(self.frame,text='Issues, saved views, source/version checks, stage history and an offline report.',wraplength=315).pack(fill='x')
        ttk.Label(self.frame,text='Review summary (optional)').pack(anchor='w',pady=(5,2))
        self.note=tk.Text(self.frame,height=3,width=36,wrap='word'); self.note.pack(fill='x')
        ttk.Checkbutton(self.frame,text='Include current view / profile previews',variable=self.include_previews).pack(anchor='w')
        ttk.Checkbutton(self.frame,text='Include extracted section sample CSV',variable=self.include_section).pack(anchor='w')
        self.button=ttk.Button(self.frame,text='Export QA review package…',command=lambda:self.run(self.choose)); self.button.pack(fill='x',pady=5)
        self.folder=ttk.Button(self.frame,text='Open last package folder',state='disabled',command=self.open_folder); self.folder.pack(fill='x')
        ttk.Label(self.frame,textvariable=self.status,wraplength=315).pack(fill='x',pady=5)
        layout.menus['File'].add_command(label='Export QA review package…',command=lambda:self.run(self.choose))
        layout.notes.menu.add_command(label='Export QA review package…',command=lambda:self.run(self.choose))
        # Keep the existing Deliver action selector and add the same export route there.
        for child in layout.deliver.winfo_children():
            if isinstance(child,ttk.Combobox):
                child.configure(values=(*child.cget('values'),'QA review package'))

    def run(self, fn):
        try:
            return fn()
        except (ValueError,OSError,KeyError,TypeError) as exc:
            self.status.set(str(exc)); self.v.status.set(str(exc))

    def ready(self):
        w=self.w; c=w.comparison
        if self.pending or self.app.runner.running or self.app._stage_open or w.active is not None or self.v.busy or self.r.busy or w.notes.pending or c.pending:
            raise ValueError('Wait for the current load, extraction or job to finish before exporting.')
        if w.pending_view or getattr(w,'pending_version_view',False) or self.layout.corridor.drag is not None:
            raise ValueError('Finish restoring the view or dragging the corridor before exporting.')
        notes=w.notes
        if notes.selected_issue:
            row=notes.model.get('issues',notes.selected_issue)
            edited=(notes.title.get().strip(),notes.category.get(),notes.state.get(),notes.note.get('1.0','end-1c').strip())
            if edited != (row['title'],row['category'],row['state'],row['note']):
                raise ValueError('Apply note in Review notes before exporting; the selected issue has unapplied edits.')

    def capture(self):
        self.ready(); self.layout.root.update_idletasks(); w=self.w; data=deepcopy(w.tracker.data)
        data['review_notes']=deepcopy(w.notes.model.data); data['linework']=deepcopy(w.linework.layers); data['features']=deepcopy(w.features.model.items)
        try:
            data['project']=asdict(w.project_panel.snapshot())
        except ValueError as exc:
            data['project']=dict(data.get('project',{}),clouds=list(w.project_panel.clouds),trajectories=[asdict(t) for t in w.project_panel.tracks],bindings=dict(w.project_panel.bindings))
            data['project_settings_warning']=str(exc)
        data['settings']={type(s).__name__:w.stage_settings(s) for s in self.app.stages}
        data['active_cloud']=self.app.cloud_path.get(); data['trajectory']=self.app.sbet_path.get(); data['trj_time']=self.app.trj_time.get()
        data['section_route']=deepcopy(self.r.route.state); data['ui_layout']=self.layout.snapshot()
        data['version_comparison']=w.comparison.snapshot(); data['review_only_clouds']=sorted(self.v.review_only_paths)
        current=dict(state=None,warning='No cloud view is loaded.')
        if self.v.scene is not None:
            try:
                current=dict(state=w.notes.capture_view(),warning='',sampled_points=len(self.v.scene[0]),source_points=self.v.scene[4],
                    visible_files=[p for p,var in zip(self.v.paths,self.v.visible) if var.get()])
            except (ValueError,OSError) as exc:
                current['warning']='Current display not exported: '+str(exc)
        if current['state']:
            data['view']=dict(paths=list(self.v.paths),visible=[v.get() for v in self.v.visible],yaw=self.v.yaw,pitch=self.v.pitch,zoom=self.v.zoom,
                pan=self.v.pan.tolist(),center=self.v.center.tolist(),span=self.v.span,mode=self.v.mode.get(),auto_detail=self.v.auto_detail.get(),
                stereo=self.v.stereo.get(),stereo_depth=self.v.stereo_depth.get(),stereo_swap=self.v.stereo_swap.get(),
                class_filter=w.class_filter.get(),line_filter=w.line_filter.get())
        section_meta={}; section=None; previews={}; sec=self.r.section
        if sec is not None:
            corridor=self.v.corridor
            import numpy as np
            matches=bool(corridor is not None and np.array_equal(sec.start,corridor[0]) and np.array_equal(sec.end,corridor[1]) and sec.width==corridor[2])
            sources_current=all(identity(s['path'])==s for s in sec.inputs) if all(Path(s['path']).is_file() for s in sec.inputs) else False
            section_meta=dict(inputs=deepcopy(sec.inputs),crs=sec.crs,start=list(sec.start),end=list(sec.end),width=sec.width,
                matched=sec.matched,matched_by_file=list(sec.matched_by_file),sampled=len(sec.points),limit=sec.limit,
                matches_current_corridor=matches,sources_current=sources_current,profile_display=dict(mode=self.r.mode.get(),line=self.r.line.get(),
                    vertical_exaggeration=self.r.exaggeration.get(),center=self.r.profile.center.tolist(),span=self.r.profile.span.tolist(),
                    zoom=self.r.profile.zoom,pan=self.r.profile.pan.tolist()))
            if self.include_section.get():
                if not matches or not sources_current:
                    raise ValueError('The extracted section is stale or at a different corridor. Re-extract, or turn off section sample CSV.')
                section=deepcopy(sec)
        elif self.include_section.get():
            raise ValueError('Extract a section first, or turn off section sample CSV.')
        if self.include_previews.get() and current['state']:
            self.v.draw()
            previews['current-cloud.png']=dict(data=canvas_png(self.v.canvas,self.v.photo),caption='Current 3D display sample with canvas annotations. Rendering is for visual review, not a measured surface. Font/arrow styling may differ from the live canvas.')
            if sec is not None and section_meta['matches_current_corridor'] and section_meta['sources_current']:
                previews['current-profile.png']=dict(data=profile_png(self.r.profile),caption='Extracted section preview at 1024 × 360 using the existing display filters, profile zoom/pan and vertical exaggeration. Rendered from its sample without source reads; the optional CSV retains all sampled inputs.')
        comparison=dict(preferences=w.comparison.snapshot(),prepared=deepcopy(w.comparison.info) or {},display_ready=False,
            note='Saved selections are not evidence of a completed comparison or accuracy.')
        try:
            w.comparison.ready();comparison['display_ready']=True
        except (ValueError,OSError) as exc:
            comparison['warning']=str(exc)
        snapshot=dict(title=w.path.stem.replace('.argus','')+' — QA review',workspace_path=str(w.path.resolve()),workspace=data,
            captured_utc=utc_now(),operator_note=self.note.get('1.0','end-1c').strip(),software=software_info(),review_notes=data['review_notes'],
            current_settings={j['id']:deepcopy(w.current_settings(j)) for j in data['jobs']},current_view=current,section=section_meta,
            comparison=comparison,header_inventory=deepcopy(w.overview.rows))
        return snapshot,previews,section

    def choose(self):
        self.ready()
        path=filedialog.asksaveasfilename(parent=self.layout.root,filetypes=(('QA review package ZIP','*.zip'),),defaultextension='.zip',
            initialdir=str(self.w.path.parent),initialfile='QA_review_'+time.strftime('%Y%m%d_%H%M%S')+'.zip')
        if path:
            self.start(path)

    def start(self,path):
        snapshot,previews,section=self.capture(); self.result=None
        target=Path(path).resolve()
        if target.exists() or target in (self.w.path.resolve(),self.w.resume_path.resolve()):
            raise ValueError('Choose a separate, new ZIP filename; existing files are not overwritten.')
        self.pending=self.app.runner; self.status.set('Exporting review package. Stop job cancels before publication.'); self.button.configure(state='disabled')
        runner=self.app.runner; runner.stage_name='Export QA review package'
        def work(runner):
            try:
                result=export_package(target,snapshot,previews=previews,section=section,cancel=runner.cancelled,progress=runner.log)
                self.result=result
            except InterruptedError as exc:
                runner.log(str(exc)); return
            runner.log('Review package written: '+result['path'])
        runner.start(work); self.app._update_job_status()

    def poll(self):
        if not self.pending or self.pending.running:
            return
        runner=self.pending; self.pending=None; self.button.configure(state='normal')
        if self.result:
            result=self.result; self.last_path=result['path']; self.folder.configure(state='normal')
            self.w.add_layer(self.last_path,'output','QA review package')
            self.w.tracker.data.setdefault('review_exports',[]).append(dict(**result,identity=identity(self.last_path)))
            self.w.persist(); self.w.refresh_layers()
            self.status.set(f'Written: {Path(self.last_path).name}\n{result["issues"]} issues; {result["views"]} views; {result["warnings"]} source warning(s). Extract the ZIP, then open report.html.')
        else:
            self.status.set('Export failed: '+str(runner.error) if runner.error else 'Export stopped; no archive published.')
        self.app._update_job_status();self.layout.update()
        self.v.status.set(self.status.get())

    def open_folder(self):
        if self.last_path and Path(self.last_path).is_file():
            os.startfile(str(Path(self.last_path).parent))
