"""SH 151 case study, step 2: the per-strip control table.

The client's report averages all strips into one Laser Z per mark
(RMS 0.139 ft, signs both ways). This decomposition asks the three
questions that identify the mechanism:

1. Per-strip bias: does each strip carry its own dz? (misalignment)
2. Within-strip trend: does dz drift along a strip? (time-dependent)
3. Flight vs flight: F1 vs F3 flew the SAME corridor 5.4 h apart --
   do they disagree with each other?

Runs off the local cache from sh151_gather. Z: stays read-only.
Run: python -m reference.sh151_report
"""

from collections import defaultdict
from pathlib import Path

import numpy as np

from reference.sh151_gather import CACHE, read_marks

MIN_POINTS = 8


def load_cache():
    """{(mark, strip): (median_z, n, t_mid, spread)}"""
    out = {}
    for npz_path in sorted(CACHE.glob("*.npz")):
        strip = npz_path.stem[:7]
        data = np.load(npz_path, allow_pickle=False)
        marks = data["mark"]
        if marks.size == 0:
            continue
        z = data["z"]
        t = data["t"]
        for mark in np.unique(marks):
            m = marks == mark
            if m.sum() < MIN_POINTS:
                continue
            zm = z[m]
            out[(str(mark), strip)] = (
                float(np.median(zm)), int(m.sum()),
                float(np.median(t[m])),
                float(np.percentile(zm, 90) - np.percentile(zm, 10)))
    return out


def main():
    marks = read_marks()
    cache = load_cache()
    strips = sorted({s for _, s in cache})
    by_mark = defaultdict(dict)
    for (mark, strip), row in cache.items():
        by_mark[mark][strip] = row

    # --- 1. the decomposed table ---------------------------------------
    print("mark      kind   knownZ   " + "  ".join(f"{s[:4]}" for s in strips))
    rows = []
    for mark in sorted(by_mark):
        kind, e, n, kz = marks[mark]
        cells = []
        for s in strips:
            if s in by_mark[mark]:
                dz = by_mark[mark][s][0] - kz
                cells.append(f"{dz:+.2f}")
                rows.append((mark, kind, s, dz, by_mark[mark][s][2], e, n))
            else:
                cells.append("  .  ")
        print(f"{mark:8s}  {kind:5s} {kz:8.2f}  " + "  ".join(cells))

    data = np.array([(r[3], r[4], r[5], r[6]) for r in rows])
    strip_of = np.array([r[2] for r in rows])
    kind_of = np.array([r[1] for r in rows])

    # --- 2. per-strip bias ---------------------------------------------
    print("\n[per-strip bias: lidar - control (ft), check shots + AT]")
    print("strip     flight  n_marks  median     mean    spread(nmad)")
    for s in strips:
        m = strip_of == s
        if m.sum() < 2:
            continue
        dz = data[m, 0]
        med = np.median(dz)
        nmad = 1.4826 * np.median(np.abs(dz - med))
        flight = s[5:7]
        print(f"{s:8s}  {flight:4s}  {int(m.sum()):5d}   {med:+.3f}   "
              f"{np.mean(dz):+.3f}     {nmad:.3f}")

    # --- 3. within-strip trend (marks sorted by time along the strip) --
    print("\n[within-strip trend: dz vs time, strips with >= 5 marks]")
    for s in strips:
        m = strip_of == s
        if m.sum() < 5:
            continue
        dz = data[m, 0]
        t = data[m, 1]
        order = np.argsort(t)
        slope = np.polyfit(t[order] - t[order][0], dz[order], 1)[0]
        span = t.max() - t.min()
        print(f"{s}: {int(m.sum())} marks over {span:.0f} s, "
              f"drift {slope * span:+.3f} ft end-to-end, "
              f"dz {dz[order][0]:+.2f} .. {dz[order][-1]:+.2f} "
              f"(first..last)")

    # --- 4. flight vs flight at shared marks ---------------------------
    print("\n[flight vs flight, same mark]")
    for pair in (("F1", "F3"), ("F1", "F2"), ("F2", "F3")):
        deltas = []
        for mark, per in by_mark.items():
            kz = marks[mark][3]
            a = [per[s][0] - kz for s in per if s[5:7] == pair[0]]
            b = [per[s][0] - kz for s in per if s[5:7] == pair[1]]
            if a and b:
                deltas.append(np.mean(b) - np.mean(a))
        if deltas:
            deltas = np.array(deltas)
            print(f"{pair[0]} vs {pair[1]}: {deltas.size} shared marks, "
                  f"median({pair[1]}-{pair[0]}) {np.median(deltas):+.3f} ft, "
                  f"nmad {1.4826 * np.median(np.abs(deltas - np.median(deltas))):.3f}")

    # --- 5. overall, to reconcile with their report --------------------
    check = kind_of == "check"
    per_mark_merged = []
    for mark in sorted(by_mark):
        if marks[mark][0] != "check":
            continue
        kz = marks[mark][3]
        zs = [v[0] for v in by_mark[mark].values()]
        per_mark_merged.append(np.mean(zs) - kz)
    if per_mark_merged:
        arr = np.array(per_mark_merged)
        print(f"\n[merged, check shots only -- their report says avg +0.030 "
              f"rms 0.139]")
        print(f"mean {arr.mean():+.3f}  rms {np.sqrt((arr**2).mean()):.3f}  "
              f"min {arr.min():+.3f}  max {arr.max():+.3f}  n {arr.size}")


if __name__ == "__main__":
    main()
