"""Diagnosis-only desktop action over the current project's declared inputs."""
from pathlib import Path
from dataclasses import asdict
from datetime import datetime
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pyargus.qa.flightline_diagnostics import DEFAULTS,settings


class FlightlineDiagnostics:
    def __init__(self,workspace):
        self.w=workspace;self.app=workspace.app;self.window=None;self.poll_id=None

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift();return self.window
        win=self.window=tk.Toplevel(self.app.root)
        win.title('pyArgus — Flightline diagnostics');win.geometry('850x680');win.minsize(680,500)
        footer=ttk.Frame(win,padding=12);footer.pack(side='bottom',fill='x')
        canvas=tk.Canvas(win,highlightthickness=0)
        scroll=ttk.Scrollbar(win,command=canvas.yview);scroll.pack(side='right',fill='y')
        canvas.configure(yscrollcommand=scroll.set);canvas.pack(fill='both',expand=True)
        body=ttk.Frame(canvas,padding=14);item=canvas.create_window(0,0,window=body,anchor='nw')
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        ttk.Label(body,text='Flightline coverage and ground-surface differences',font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(body,text='Reads the current project inputs using disk scratch at the output location. No alignment solve, control fit, classification or LAS export is performed. The candidate is an optional saved project referencing already processed clouds.',wraplength=760).pack(fill='x',pady=8)
        saved=self.w.tracker.data['settings'].get('flightline_diagnostics',{})
        self.vars={k:tk.StringVar(value=str(saved.get(k,v))) for k,v in DEFAULTS.items()}
        fields=ttk.LabelFrame(body,text='Ground-cell screening',padding=10);fields.pack(fill='x',pady=8)
        labels=dict(cell_ft='Cell width (US survey ft)',min_points='Minimum ground returns per flight / cell',max_scatter_ft='Maximum local plane RMS (US survey ft)',max_slope='Maximum surface slope (rise/run)',tolerance_ft='Height disagreement review threshold (US survey ft)',min_cells='Minimum qualified shared cells per pair')
        for row,(key,var) in enumerate(self.vars.items()):
            ttk.Label(fields,text=labels[key]).grid(row=row,column=0,sticky='w',pady=4)
            ttk.Entry(fields,textvariable=var,width=14).grid(row=row,column=1,padx=12,pady=4,sticky='w')
        ttk.Label(body,text='Only class-2 ground is evaluated. Local planes require support around the cell center, good conditioning, limited scatter and limited slope. Missing support is reported, not counted as agreement.',wraplength=760).pack(fill='x',pady=8)
        self.candidate=tk.StringVar(value=saved.get('candidate',''));self.out=tk.StringVar()
        for label,var,action in [('Candidate project JSON (optional)',self.candidate,self.choose_candidate),('New report folder',self.out,self.choose_output)]:
            frame=ttk.Frame(body);frame.pack(fill='x',pady=5)
            ttk.Label(frame,text=label).pack(anchor='w')
            ttk.Button(frame,text='Browse…',command=action).pack(side='right')
            ttk.Entry(frame,textvariable=var).pack(fill='x',expand=True)
        ttk.Label(body,text='Candidate comparison uses identical world cells and matching LAS-line / trajectory identities. It does not prove input lineage or independent absolute accuracy. Settings and thresholds are not a survey standard.',wraplength=760).pack(fill='x',pady=10)
        self.status=tk.StringVar(value='Ready — no cloud changes will be made.')
        ttk.Label(footer,textvariable=self.status,wraplength=760).pack(fill='x',pady=(0,6))
        self.run_button=ttk.Button(footer,text='Run flightline diagnostics',command=self.start);self.run_button.pack(side='left')
        ttk.Button(footer,text='Stop job',command=self.app.runner.cancel).pack(side='left',padx=6)
        ttk.Button(footer,text='Close',command=win.destroy).pack(side='right')
        win.bind('<Destroy>',self.closed,add='+')
        self.poll();return win

    def choose_candidate(self):
        path=filedialog.askopenfilename(parent=self.window,title='Saved pyArgus candidate project',filetypes=(('pyArgus project','*.json'),))
        if path:self.candidate.set(path)

    def choose_output(self):
        parent=filedialog.askdirectory(parent=self.window,title='Report output parent')
        if parent:self.out.set(str(Path(parent)/('flightline_diagnostics_'+datetime.now().strftime('%Y%m%d_%H%M%S'))))

    def poll(self):
        if self.window is None or not self.window.winfo_exists():return
        self.run_button.configure(state='disabled' if self.app.runner.running else 'normal')
        self.status.set(self.app.job_status.get() if self.app.runner.running else 'Ready — completed reports appear in Deliver and Job history.')
        self.poll_id=self.window.after(300,self.poll)

    def closed(self,event):
        if event.widget is self.window and self.poll_id is not None:
            try:self.window.after_cancel(self.poll_id)
            except tk.TclError:pass
            self.poll_id=None

    def start(self):
        if self.app.runner.running:return
        from pyargus import project
        from pyargus.qa.flightline_diagnostics import run
        try:
            panel=self.w.project_panel;panel.check_time_settings();spec=panel.snapshot()
            config={k:(int(var.get()) if k in ('min_points','min_cells') else float(var.get())) for k,var in self.vars.items()}
            config=settings(config)
            if not self.out.get().strip():raise ValueError('Choose a new report folder.')
            out=project._target(self.out.get().strip())
            candidate=project.Project.load(self.candidate.get().strip()) if self.candidate.get().strip() else None
            project._cloud_headers(spec)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            messagebox.showerror('Flightline diagnostics',str(exc),parent=self.window);return
        self.w.tracker.data['settings']['flightline_diagnostics']=dict(config,candidate=self.candidate.get().strip())
        self.w.begin_project('diagnostics',spec,str(out))
        def work(runner):
            try:
                run(spec,out,candidate=candidate,config=config,log=runner.log,cancel=runner.cancelled)
                runner.products.append(('report',str(out/'report.html')))
            except project.Cancelled:return
        runner=self.app.runner;runner.stage_name='Flightline diagnostics'
        self.app.run_button.configure(state='disabled');self.app.stop_button.configure(state='normal')
        runner.start(work);self.app._stage_open=True;self.app._update_job_status()
