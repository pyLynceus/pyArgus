"""Read-only Summerville acceptance for the multi-file importer.

Create small temporary copies of two real lines and matching SBET intervals.
Original files and pyLynceus are never modified. This checks import/matching,
not the accuracy of a newly adjusted survey.
"""
from pathlib import Path
import tempfile
import numpy as np
import laspy

from pyargus import project
from pyargus.formats import sbet
from reference.summerville import CLOUD, SBET


def main():
    limit = 25000
    selected = {1: [], 2: []}
    counts = {1: 0, 2: 0}
    with laspy.open(CLOUD) as reader:
        header = reader.header.copy()
        for chunk in reader.chunk_iterator(500000):
            for sid in selected:
                remaining=limit-counts[sid]
                if remaining:
                    subset=chunk[chunk.point_source_id==sid][:remaining].copy()
                    if len(subset): selected[sid].append(subset); counts[sid]+=len(subset)
            if all(n==limit for n in counts.values()): break
    assert all(n==limit for n in counts.values()), counts
    nav = sbet.read_sbet(SBET)
    with tempfile.TemporaryDirectory(prefix='pyargus-reference-project-') as temporary:
        temporary=Path(temporary)
        clouds,tracks=[],[]
        for sid in selected:
            points=laspy.ScaleAwarePointRecord.zeros(counts[sid],header=header)
            offset=0
            for chunk in selected[sid]:
                points.array[offset:offset+len(chunk)]=chunk.array
                offset+=len(chunk)
            cloud=laspy.LasData(header.copy(),points)
            path=temporary/f'line_{sid}.las'; cloud.write(path)
            clouds.append(str(path))
            week,fraction=sbet.week_alignment(cloud.gps_time,nav['time'])
            assert fraction==1.0
            times=np.asarray(cloud.gps_time)-(week*604800-1e9)
            first=max(0,int(np.searchsorted(nav['time'],times.min()))-2)
            last=min(len(nav),int(np.searchsorted(nav['time'],times.max()))+3)
            trajectory=temporary/f'line_{sid}.out'; nav[first:last].tofile(trajectory)
            tracks.append(project.TrajectoryInput(str(trajectory),'week',gps_week=week))
        spec=project.Project(clouds,tracks,same_vertical=True)
        loaded=project.load(spec,keep_points=True,log=print)
        inv=loaded.inventory
        assert inv['matched']==50000 and inv['unmatched']==0 and inv['ambiguous']==0,inv
        assert len(inv['strips'])==2
        assert set(loaded.points['original_point_source_id'])=={1,2}
        print('PASS: 2 real LAS line samples + 2 SBET intervals; all 50,000 returns matched uniquely; source IDs preserved.')
        return dict(points=inv['points'],matched=inv['matched'],strips=len(inv['strips']))


if __name__=='__main__': main()
