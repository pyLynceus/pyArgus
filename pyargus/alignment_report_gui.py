"""Saved alignment reporting preferences shared by project and LP360 setup."""
import tkinter as tk
from tkinter import ttk, filedialog
from pyargus.qa.alignment_report import DEFAULTS, settings


class AlignmentReportPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=8)
        self.pack(fill='both', expand=True)
        self.vars={key:tk.StringVar(value=str(value)) for key,value in DEFAULTS.items()}
        ttk.Label(self,text='Every alignment creates a before/after report. Survey checks are optional and are never used to fit the adjustment.',wraplength=850).grid(row=0,column=0,columnspan=3,sticky='w',pady=6)
        ttk.Label(self,text='Survey check CSV (optional)').grid(row=1,column=0,sticky='w')
        ttk.Entry(self,textvariable=self.vars['checkpoints']).grid(row=1,column=1,sticky='ew',padx=6)
        ttk.Button(self,text='Browse…',command=self.browse).grid(row=1,column=2)
        for row,(key,label,values) in enumerate([('order','CSV coordinate order',('pnez','penz')),('role','Survey role',('reference','independent')),('surface','Surface evaluated',('unspecified','pavement','other_ground'))],2):
            ttk.Label(self,text=label).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Combobox(self,textvariable=self.vars[key],values=values,state='readonly',width=24).grid(row=row,column=1,sticky='w',padx=6)
        for row,(key,label) in enumerate([('material','Surface description (optional)'),('pavement_tolerance_ft','Pavement tolerance (US survey ft)'),('other_ground_tolerance_ft','Other-ground tolerance (US survey ft)'),('radius_ft','Check neighborhood radius (US survey ft)'),('min_points','Minimum local ground returns')],5):
            ttk.Label(self,text=label).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Entry(self,textvariable=self.vars[key],width=30).grid(row=row,column=1,sticky='ew',padx=6)
        ttk.Label(self,text='Choose independent only for shots withheld from fitting and earlier cloud adjustments. Reference comparisons remain useful but do not establish independent accuracy. Tolerances and radius are converted to the cloud units. No note is required.',wraplength=850).grid(row=10,column=0,columnspan=3,sticky='w',pady=12)
        self.columnconfigure(1,weight=1)

    def browse(self):
        path=filedialog.askopenfilename(parent=self,title='Survey checks (ID,N,E,Z or ID,E,N,Z)',filetypes=(('Survey CSV','*.csv'),))
        if path:self.vars['checkpoints'].set(path)

    def snapshot(self):
        values={k:v.get().strip() for k,v in self.vars.items()}
        for key in ('pavement_tolerance_ft','other_ground_tolerance_ft','radius_ft'):values[key]=float(values[key])
        values['min_points']=int(values['min_points'])
        return settings(values)

    def restore(self, value=None):
        for key,value in settings(value).items():self.vars[key].set(str(value))
