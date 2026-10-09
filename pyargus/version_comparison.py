"""Read-only original/result pairing. Never infer lineage from filenames."""
from pathlib import Path
import numpy as np

ROLES=('Original','Result','Both')


def cloud_path(value):
    p=Path(value)
    if not p.is_absolute() or p.suffix.lower() not in ('.las','.laz'):
        raise ValueError('Choose an absolute LAS/LAZ path.')
    return str(p.resolve())


def preferences(data=None):
    if not data:return dict(schema_version=1,original='',result='',confirmed=False,role='Result')
    if not isinstance(data,dict) or data.get('schema_version')!=1:raise ValueError('Unsupported version comparison settings.')
    if type(data.get('confirmed')) is not bool or data.get('role') not in ROLES:raise ValueError('Invalid comparison preference.')
    return dict(schema_version=1,original=cloud_path(data['original']) if data.get('original') else '',
        result=cloud_path(data['result']) if data.get('result') else '',confirmed=data['confirmed'],role=data['role'])


def recorded_pair(tracker,anchor):
    if not anchor:return None
    anchor=cloud_path(anchor);root=tracker.cloud_root(anchor)
    versions=tracker.data.get('cloud_versions',{})
    candidates=[p for p,v in versions.items() if v.get('root')==root and v.get('parent')]
    if not candidates:return None
    return root,anchor if anchor in candidates else candidates[-1]


def lineage_evidence(tracker,original,result):
    """Return provenance and metadata expectations for a recorded descendant."""
    versions=tracker.data.get('cloud_versions',{});chain=[];seen=set();path=result
    while path in versions and versions[path].get('parent'):
        if path in seen:raise ValueError('Circular cloud lineage; repair the workspace record.')
        seen.add(path);entry=versions[path];parent=cloud_path(entry['parent']);job_id=entry.get('job')
        job=next((j for j in tracker.data['jobs'] if j['id']==job_id),None)
        if job is None:raise ValueError('Recorded result has no supporting job record.')
        if job['status'] not in ('Needs review','Accepted'):
            raise ValueError('Recorded result did not finish successfully; use a verified completed result.')
        ins=next((i for i in job['inputs'] if str(Path(i[0]).resolve())==parent),None)
        outs=next((i for i in job['outputs'] if str(Path(i[0]).resolve())==path),None)
        if not ins or not outs or ins[1] is None or outs[1] is None:
            raise ValueError('Recorded lineage lacks source/output identities.')
        chain.append(dict(job=job_id,stage=job['stage'],source=ins,result=outs));path=parent
        if path==original:return chain
    return None


def inspect_pair(tracker,original,result,confirmed,expected_crs=None):
    import laspy
    from pyargus.job_manifest import identity
    from pyargus.workspace_state import signature
    original,result=cloud_path(original),cloud_path(result)
    if original==result:raise ValueError('Original and Result must be different files.')
    if not confirmed:raise ValueError('Confirm common XYZ units and vertical datum before comparing.')
    chain=lineage_evidence(tracker,original,result)
    if chain:
        for step in chain:
            for item in (step['source'],step['result']):
                if signature([item[0]])!=[item]:raise ValueError('Recorded source/result changed or is missing; comparison refused.')
    sources=[identity(original),identity(result)];crs=None
    for source in sources:
        with laspy.open(source['path']) as reader:
            current=reader.header.parse_crs()
            if not reader.header.point_count:raise ValueError('Comparison cloud is empty.')
            if current is None or not current.is_projected:raise ValueError('Comparison needs declared projected LAS CRS.')
            if crs is not None and current!=crs:raise ValueError('Original and Result CRS differ; comparison does not reproject.')
            factors=[a.unit_conversion_factor for a in current.axis_info]
            if not np.allclose(factors,factors[0],rtol=1e-12,atol=0):raise ValueError('Comparison requires matching XYZ units.')
            crs=current
    if expected_crs is not None and crs!=expected_crs:raise ValueError('Comparison CRS differs from the current view and reference overlays.')
    if [identity(s['path']) for s in sources]!=sources:raise ValueError('Cloud changed during comparison preparation.')
    return dict(original=original,result=result,inputs=sources,crs=crs.to_wkt(),
        provenance='Recorded lineage' if chain else 'Manual pair — relationship not verified',jobs=chain or [])


def check_sources(info):
    from pyargus.job_manifest import identity
    from pyargus.workspace_state import signature
    for step in info.get('jobs',[]):
        for item in (step['source'],step['result']):
            if signature([item[0]])!=[item]:raise ValueError('Recorded comparison lineage changed; prepare a verified pair.')
    for source in info['inputs']:
        if identity(source['path'])!=source:raise ValueError('Comparison source changed; reload the pair before switching.')


def role_visibility(role):
    if role not in ROLES:raise ValueError('Choose Original, Result or Both.')
    return [role!='Result',role!='Original']


def section_matches(section,info,corridor):
    if section is None or corridor is None:return False
    a,b,width=corridor
    return (section.inputs==info['inputs'] and np.array_equal(section.start,a)
        and np.array_equal(section.end,b) and section.width==width)
