"""SH 151 case study, step 1: gather lidar points near every check
mark, PER STRIP, into a local cache.

The question the cache answers: at each surveyed mark, what does EACH
strip's surface read? Reading 22 strips (~54 GB) off Z: is the slow
part, so each strip's near-mark points land in an .npz under
reference/reports/sh151_cache/ (local, gitignored) and a rerun skips
strips already cached. Z: stays read-only.

Run: python -m reference.sh151_gather
"""

import glob
from pathlib import Path

import numpy as np

RADIUS = 3.0        # ft, the pyLynceus-proven gather radius
LAS_DIR = "Z:/Users/BJordan/SH 151/LIDAR/TERRAFLIGHT/LAS"
CACHE = Path("reference/reports/sh151_cache")


def read_marks():
    """Check shots (Number, E, N, KnownZ) from the survey report, and
    the AT targets (P,N,E,Z csv) as a second population."""
    marks = {}
    report = Path("Z:/Users/BJordan/SH 151/SURVEY/"
                  "ControlReport_OSSDACheckShots_reduxlidar.txt")
    for line in report.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0].isdigit():
            marks[parts[0]] = ("check", float(parts[1]), float(parts[2]),
                               float(parts[3]))
    at = Path("Z:/Users/BJordan/SH 151/SURVEY/25-0162 Allpts - AT.csv")
    for line in at.read_text().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4 and parts[0].isdigit():
            # P,N,E,Z -- northing first (the Summerville lesson, and
            # confirmed here: col2 ~416k = N, col3 ~2474k = E)
            marks[parts[0]] = ("at", float(parts[2]), float(parts[1]),
                               float(parts[3]))
    return marks


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    marks = read_marks()
    ids = sorted(marks)
    me = np.array([marks[i][1] for i in ids])
    mn = np.array([marks[i][2] for i in ids])
    print(f"{len(ids)} marks ({sum(1 for i in ids if marks[i][0]=='check')} "
          f"check shots, {sum(1 for i in ids if marks[i][0]=='at')} AT)")

    import laspy

    for path in sorted(glob.glob(f"{LAS_DIR}/*.las")):
        name = Path(path).stem
        out = CACHE / f"{name}.npz"
        if out.exists():
            print(f"{name}: cached")
            continue
        with laspy.open(path) as reader:
            h = reader.header
            near = ((me >= h.mins[0] - RADIUS) & (me <= h.maxs[0] + RADIUS)
                    & (mn >= h.mins[1] - RADIUS) & (mn <= h.maxs[1] + RADIUS))
            candidates = np.flatnonzero(near)
            if candidates.size == 0:
                np.savez(out, mark=np.array([], dtype="U8"),
                         x=[], y=[], z=[], t=[])
                print(f"{name}: no marks in extent")
                continue
            ce, cn = me[candidates], mn[candidates]
            got = {"mark": [], "x": [], "y": [], "z": [], "t": []}
            for pts in reader.chunk_iterator(5_000_000):
                x = np.asarray(pts.x)
                y = np.asarray(pts.y)
                keep_any = np.zeros(x.size, dtype=bool)
                which = np.full(x.size, -1, dtype=np.int32)
                for k in range(candidates.size):
                    m = ((np.abs(x - ce[k]) <= RADIUS)
                         & (np.abs(y - cn[k]) <= RADIUS))
                    which[m & ~keep_any] = k
                    keep_any |= m
                idx = np.flatnonzero(keep_any)
                if idx.size:
                    got["mark"].extend(
                        ids[candidates[which[i]]] for i in idx)
                    got["x"].extend(x[idx])
                    got["y"].extend(y[idx])
                    got["z"].extend(np.asarray(pts.z)[idx])
                    got["t"].extend(np.asarray(pts.gps_time)[idx])
        np.savez(out, mark=np.array(got["mark"], dtype="U8"),
                 x=np.array(got["x"]), y=np.array(got["y"]),
                 z=np.array(got["z"]), t=np.array(got["t"]))
        print(f"{name}: {len(got['x']):,} points near "
              f"{len(set(got['mark']))} marks")
    print("gather complete")


if __name__ == "__main__":
    main()
