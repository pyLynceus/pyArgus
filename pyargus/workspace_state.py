"""Persistent workflow history. Review decisions never certify accuracy."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

STAGES = ("Inspect", "Initial QA", "Classification", "Alignment", "Surface", "Contours", "Colorization", "Final QA", "Delivery")
DEPENDENCIES = {"Initial QA": ["Inspect"], "Classification": ["Inspect"],
                "Alignment": ["Initial QA", "Classification"], "Surface": ["Classification", "Alignment"],
                "Contours": ["Surface"], "Colorization": ["Alignment"],
                "Final QA": ["Alignment", "Surface", "Contours"], "Delivery": ["Final QA"]}


def stamp(): return datetime.now(timezone.utc).isoformat()


def signature(paths):
    result=[]
    for name in sorted(set(str(Path(p).resolve()) for p in paths if p)):
        try:
            stat=Path(name).stat(); result.append([name, stat.st_size, stat.st_mtime_ns])
        except OSError: result.append([name, None, None])
    return result


class Tracker:
    def __init__(self, data=None):
        self.data=data or dict(version=1, layers=[], jobs=[], decisions=[], view={}, project={}, settings={}, sections=[])
        if self.data.get("version") != 1: raise ValueError("Unsupported workspace version")
        for key, value in dict(layers=[], jobs=[], decisions=[], view={}, project={}, settings={}, sections=[]).items():
            self.data.setdefault(key,value)

    def latest(self, stage):
        return next((j for j in reversed(self.data['jobs']) if j['stage']==stage), None)

    def dependencies(self,stage):
        return {s: self.latest(s)['id'] if self.latest(s) else None for s in DEPENDENCIES.get(stage,[])}

    def begin(self,stage,settings,inputs):
        job=dict(id=uuid.uuid4().hex,stage=stage,started=stamp(),status='Running',settings=settings,
                 inputs=signature(inputs),dependencies=self.dependencies(stage),outputs=[],records=[],notes=[])
        self.data['jobs'].append(job)
        return job

    def finish(self,job,status,outputs=(),error=None,elapsed=0):
        if status not in ('Needs review','Failed','Cancelled'): raise ValueError('Invalid job outcome')
        job.update(status=status,finished=stamp(),outputs=signature(outputs),error=error,elapsed=elapsed)

    def status(self, stage, settings=None):
        job=self.latest(stage)
        if job is None: return 'Not started'
        if job['status'] in ('Running','Failed','Cancelled','Unverified import'): return job['status']
        if signature([i[0] for i in job['inputs']]) != job['inputs']: return 'Outdated'
        if job.get('outputs') and signature([i[0] for i in job['outputs']]) != job['outputs']: return 'Outdated'
        if settings is not None and settings != job['settings']: return 'Outdated'
        if self.dependencies(stage) != job.get('dependencies',{}): return 'Outdated'
        if any(self.status(s)=='Outdated' for s in DEPENDENCIES.get(stage,[]) if self.latest(s)): return 'Outdated'
        return job['status']

    def decide(self,stage,decision,note,settings=None):
        if not note.strip(): raise ValueError('Add a review note explaining the decision.')
        job=self.latest(stage)
        if decision=='Skipped':
            job=self.begin(stage,settings or {},[])
        elif job is None or self.status(stage,settings) not in ('Needs review','Accepted'):
            raise ValueError('Only current completed work can be accepted or returned for review.')
        if decision not in ('Accepted','Needs review','Skipped'): raise ValueError('Invalid decision')
        job['status']=decision
        event=dict(job=job['id'],stage=stage,decision=decision,note=note,time=stamp())
        job['notes'].append(event); self.data['decisions'].append(event)

    def import_output(self,path):
        job=self.begin('Delivery',{},[])
        job.update(status='Unverified import',outputs=signature([path]))
        return job

    def save(self,path):
        path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temp.open('x',encoding='utf-8') as f:
                json.dump(self.data,f,indent=2,allow_nan=False); f.flush(); os.fsync(f.fileno())
            os.replace(temp,path)
        finally: temp.unlink(missing_ok=True)

    @classmethod
    def load(cls,path):
        tracker=cls(json.loads(Path(path).read_text(encoding='utf-8')))
        for job in tracker.data['jobs']:
            if job['status']=='Running':
                job.update(status='Needs review',error='Previous session ended while running; completion is unverified.')
                job['status']='Unverified import'
        return tracker
