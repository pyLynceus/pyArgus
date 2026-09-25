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
# The Classify stage's default "Noise max fraction" as the stage records it
# (text). A literal, so this module stays free of the numeric stack; a test
# pins it to classify.noise.DEFAULT_MAX_FRACTION and to the stage's default.
NOISE_MAX_FRACTION_TEXT = "0.001"


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

    def cloud_root(self, path):
        path=str(Path(path).resolve())
        return self.data.get('cloud_versions',{}).get(path,{}).get('root',path)

    def register_cloud_result(self, source, output, job_id):
        source,output=str(Path(source).resolve()),str(Path(output).resolve())
        if source==output: raise ValueError('A result must be a new file')
        versions=self.data.setdefault('cloud_versions',{})
        root=self.cloud_root(source)
        versions.setdefault(source,dict(root=root,parent=None,job=None))
        versions[output]=dict(root=root,parent=source,job=job_id)

    def latest(self, stage):
        return next((j for j in reversed(self.data['jobs']) if j['stage']==stage), None)

    def scope(self, job):
        if job['stage']=='Classification':
            return (job.get('stage_class', 'ClassifyStage'), self.cloud_root(job['settings']['cloud']) if job.get('settings',{}).get('cloud') else None)
        return None

    def current_jobs(self, stage):
        jobs={}
        for job in self.data['jobs']:
            if job['stage']==stage: jobs[self.scope(job)]=job
        return list(jobs.values())

    def dependencies(self,stage):
        return {s: ([j['id'] for j in self.current_jobs(s)] if s=='Classification' else self.latest(s)['id'] if self.latest(s) else None) for s in DEPENDENCIES.get(stage,[])}

    def begin(self,stage,settings,inputs):
        job=dict(id=uuid.uuid4().hex,stage=stage,started=stamp(),status='Running',settings=settings,
                 inputs=signature(inputs),dependencies=self.dependencies(stage),outputs=[],records=[],notes=[])
        self.data['jobs'].append(job)
        return job

    def finish(self,job,status,outputs=(),error=None,elapsed=0):
        if status not in ('Needs review','Failed','Cancelled'): raise ValueError('Invalid job outcome')
        job.update(status=status,finished=stamp(),outputs=signature(outputs),error=error,elapsed=elapsed)

    def comparable_settings(self, job, settings):
        if job['stage']=='Classification' and job.get('stage_class','ClassifyStage')=='ClassifyStage':
            # These are routing fields, not ground-classification parameters.
            # The attempt's own source identity is checked separately.
            settings=dict(settings)
            for key in ('cloud','trajectory','trj_time'): settings.pop(key,None)
            if isinstance(settings.get('stage'),dict):
                # blank as the run reads it: prepare() and batch strip the
                # text, so a field holding only spaces screens nothing
                stage={k:v for k,v in settings['stage'].items() if k not in ('out_path','batch_dir') and not (k in ('noise_min','noise_max') and (v is None or not str(v).strip()))}
                # The noise max fraction only decides whether a screening run
                # refuses; it never changes what a completed run wrote. Without
                # a window it cannot have mattered. Jobs recorded before the
                # field existed ran with NO guard at all; they are compared at
                # the default by choice, because calling every earlier windowed
                # classification outdated would say its output changed, and it
                # did not.
                if 'noise_min' in stage or 'noise_max' in stage:
                    stage.setdefault('noise_max_fraction',NOISE_MAX_FRACTION_TEXT)
                else:
                    stage.pop('noise_max_fraction',None)
                settings['stage']=stage
        return settings

    def stale_reason(self, job, settings=None):
        if job not in self.current_jobs(job['stage']): return 'newer attempt for this input'
        if signature([i[0] for i in job['inputs']]) != job['inputs']: return 'input changed or missing'
        if job.get('outputs') and signature([i[0] for i in job['outputs']]) != job['outputs']: return 'output changed or missing'
        if settings is not None and self.comparable_settings(job,settings) != self.comparable_settings(job,job['settings']): return 'processing settings changed'
        current=self.dependencies(job['stage']);recorded=dict(job.get('dependencies',{}))
        stages=list(DEPENDENCIES.get(job['stage'],[]))
        # Ground classification uses the recorded LAS and its parameters,
        # not trajectory matching of subsequently promoted outputs.
        if job['stage']=='Classification' and job.get('stage_class','ClassifyStage')=='ClassifyStage':
            current.pop('Inspect',None);recorded.pop('Inspect',None)
            stages=[s for s in stages if s!='Inspect']
        if current != recorded: return 'upstream run changed'
        if any(self.status(s)=='Outdated' for s in stages if self.latest(s)): return 'upstream work outdated'
        return None

    def job_status(self, job, settings=None):
        if job['status'] in ('Running','Failed','Cancelled','Unverified import'): return job['status']
        return 'Outdated' if self.stale_reason(job,settings) else job['status']

    def status(self, stage, settings=None):
        jobs=self.current_jobs(stage)
        if not jobs: return 'Not started'
        states=[self.job_status(j,settings(j) if callable(settings) else settings) for j in jobs]
        for state in ('Running','Outdated','Failed','Cancelled','Unverified import','Needs review'):
            if state in states: return state
        return 'Accepted' if 'Accepted' in states else states[-1]

    def decide(self,stage,decision,note,settings=None,job_id=None):
        if not note.strip(): raise ValueError('Add a review note explaining the decision.')
        if decision not in ('Accepted','Needs review','Skipped'): raise ValueError('Invalid decision')
        job=(next((j for j in self.data['jobs'] if j['id']==job_id and j['stage']==stage),None)
             if job_id else self.latest(stage))
        if decision=='Skipped':
            job=self.begin(stage,settings or {},[])
        elif job is None or self.job_status(job,settings) not in ('Needs review','Accepted'):
            raise ValueError('Only current completed work for this input can be accepted or returned for review.')
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
        # Recover only unambiguous recorded ground-classification lineage.
        # Do not change the saved active project versions on load.
        for job in tracker.data['jobs']:
            if job.get('stage_class')!='ClassifyStage' or job['status'] not in ('Needs review','Accepted'):
                continue
            source=job.get('settings',{}).get('cloud')
            outputs=[item for item in job.get('outputs',[]) if Path(item[0]).suffix.lower() in ('.las','.laz')]
            if not source or len(outputs)!=1:continue
            output=outputs[0]
            source_items=[item for item in job.get('inputs',[]) if str(Path(item[0]).resolve())==str(Path(source).resolve())]
            if len(source_items)!=1 or signature([source])!=source_items or signature([output[0]])!=[output]:continue
            if source_items[0][1] is None or output[1] is None:continue
            if str(Path(source).resolve())==str(Path(output[0]).resolve()):continue
            if str(Path(output[0]).resolve()) not in tracker.data.get('cloud_versions',{}):
                tracker.register_cloud_result(source,output[0],job['id'])
        return tracker
