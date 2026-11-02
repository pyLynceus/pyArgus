"""Saved alignment reporting preferences shared by project and LP360 setup."""
import tkinter as tk
from tkinter import ttk, filedialog
from pyargus.qa.alignment_report import DEFAULTS, settings


class AlignmentReportPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=8)
        self.pack(fill='both', expand=True)
        self.vars={key:tk.StringVar(value=str(value)) for key,value in DEFAULTS.items()}
        tabs=ttk.Notebook(self);tabs.pack(fill='both',expand=True)
        checks=ttk.Frame(tabs,padding=8);audit=ttk.Frame(tabs,padding=8)
        tabs.add(checks,text='Survey checks');tabs.add(audit,text='Control coverage')
        ttk.Label(checks,text='Every alignment creates a before/after report. Survey checks are optional and are never used to fit the adjustment.',wraplength=850).grid(row=0,column=0,columnspan=3,sticky='w',pady=6)
        ttk.Label(checks,text='Survey check CSV (optional)').grid(row=1,column=0,sticky='w')
        ttk.Entry(checks,textvariable=self.vars['checkpoints']).grid(row=1,column=1,sticky='ew',padx=6)
        ttk.Button(checks,text='Browse…',command=self.browse).grid(row=1,column=2)
        for row,(key,label,values) in enumerate([('order','CSV coordinate order',('pnez','penz')),('role','Survey role',('reference','independent')),('surface','Surface evaluated',('unspecified','pavement','other_ground'))],2):
            ttk.Label(checks,text=label).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Combobox(checks,textvariable=self.vars[key],values=values,state='readonly',width=24).grid(row=row,column=1,sticky='w',padx=6)
        for row,(key,label) in enumerate([('material','Surface description (optional)'),('pavement_tolerance_ft','Pavement tolerance (US survey ft)'),('other_ground_tolerance_ft','Other-ground tolerance (US survey ft)'),('radius_ft','Check / audit neighborhood radius (US survey ft)'),('min_points','Minimum local ground returns')],5):
            ttk.Label(checks,text=label).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Entry(checks,textvariable=self.vars[key],width=30).grid(row=row,column=1,sticky='ew',padx=6)
        ttk.Label(checks,text='Choose independent only for shots withheld from fitting and earlier cloud adjustments. Reference comparisons do not establish independent accuracy. Length settings convert to the cloud units. No note is required.',wraplength=850).grid(row=10,column=0,columnspan=3,sticky='w',pady=12)
        ttk.Label(audit,text='Every alignment audits control coverage by flight. Add reference PIDs here while keeping independent survey checks on their own tab. In LP360 jobs the selected project Control CSV is included automatically when this field is blank.',wraplength=850).grid(row=0,column=0,columnspan=3,sticky='w',pady=6)
        ttk.Label(audit,text='Reference control / PID CSV (optional)').grid(row=1,column=0,sticky='w')
        ttk.Entry(audit,textvariable=self.vars['control_points']).grid(row=1,column=1,sticky='ew',padx=6)
        ttk.Button(audit,text='Browse…',command=lambda:self.browse('control_points')).grid(row=1,column=2)
        ttk.Label(audit,text='PID coordinate order').grid(row=2,column=0,sticky='w',pady=5)
        ttk.Combobox(audit,textvariable=self.vars['control_order'],values=('pnez','penz'),state='readonly',width=24).grid(row=2,column=1,sticky='w',padx=6)
        for row,(key,label) in enumerate([('coverage_min_sites','Minimum distinct supported sites per flight'),('coverage_max_gap_ft','Projected gap warning (US survey ft)')],3):
            ttk.Label(audit,text=label).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Entry(audit,textvariable=self.vars[key],width=30).grid(row=row,column=1,sticky='ew',padx=6)
        ttk.Label(audit,text='These are editable planning thresholds, not GDOT / ASPRS minimums. Sites spanning less than half the flight ground extent length, less than a quarter of its width, or nearly collinear geometry are also flagged. Footprint outlines and gap distances use a straight principal-axis extent, not curved-route stationing.',wraplength=850).grid(row=5,column=0,columnspan=3,sticky='w',pady=12)
        ttk.Label(audit,text='Adding PIDs here never fits or changes a cloud. Supplied fitting controls, reference PIDs, independent checks, and excluded check neighborhoods retain separate counts. Local report support is not final solver observation membership.',wraplength=850).grid(row=6,column=0,columnspan=3,sticky='w',pady=6)
        for frame in (checks,audit):frame.columnconfigure(1,weight=1)

    def browse(self, key='checkpoints'):
        path=filedialog.askopenfilename(parent=self,title='Survey CSV (ID,N,E,Z or ID,E,N,Z)',filetypes=(('Survey CSV','*.csv'),))
        if path:self.vars[key].set(path)

    def snapshot(self):
        values={k:v.get().strip() for k,v in self.vars.items()}
        for key in ('pavement_tolerance_ft','other_ground_tolerance_ft','radius_ft','coverage_max_gap_ft'):values[key]=float(values[key])
        for key in ('min_points','coverage_min_sites'):values[key]=int(values[key])
        return settings(values)

    def restore(self, value=None):
        for key,value in settings(value).items():self.vars[key].set(str(value))
