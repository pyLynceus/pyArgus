"""The Summerville reference dataset: Phase-0 acceptance checks.

Summerville (Z:\\Users\\BJordan\\Summerville_SS) is the real TrueView 660
delivery that pyLynceus already validates its imagery side against, and
its lidar is the transfer standard there: on the surveyed control at
+0.146 ft (robust sd 0.150, six points, measured by pyLynceus). This
script reruns that comparison with pyArgus code plus the density and
strip-dZ checks from HANDOFF.md.

EVERYTHING ON Z: IS READ-ONLY. This script writes nothing anywhere; it
prints. It is run by hand, never by pytest -- the test suite stays
synthetic and must pass with Z: unplugged (the pyLynceus rule).

What is known about the files, learned the slow way -- see also
reference/RESULTS.md for the measured numbers:

* Summerville_SS.las -- the classified, stripped cloud. 15,284,332
  points, LAS 1.4 pf7, four strips in point_source_id (1..4),
  ASPRS classes with 1,011,700 ground (class 2) points.
  NAD83(2011) Georgia West ftUS; x is EASTING (~1.94M), y NORTHING.
* pointcloud.laz -- 345M points, but psid 0 and class 0 throughout:
  useless for strip QA, do not reach for it by size.
* The control CSVs (1-4,200-207.csv and 205.csv) are P,N,E,Z,D --
  column 2 is NORTHING. Swap on read or every checkpoint lands ~1900
  survey miles from the cloud.
* POS/sbet_NAD83(2011)[2010.0].out -- 122,924 records, 200 Hz, GPS
  seconds-of-week 481638..482252. LAS gps_time is Adjusted Standard GPS
  (subtract nothing, add 1e9 for true GPS seconds); week 2385, so
  sow = gps_time + 1e9 - 2385*604800. The strips sit inside the
  trajectory window.
"""

import csv
from pathlib import Path

import numpy as np

from pyargus.formats import las, sbet
from pyargus.qa import checkpoints, density, overlap

ROOT = Path("Z:/Users/BJordan/Summerville_SS")
CLOUD = ROOT / "Summerville_SS.las"
SBET = ROOT / "Area_/Cycle_250926_134000_122SN030/POS/sbet_NAD83(2011)[2010.0].out"
CONTROL_CSVS = [ROOT / "1-4,200-207.csv", ROOT / "205.csv"]

GPS_WEEK = 2385
ADJUSTED_OFFSET = 1_000_000_000  # LAS Adjusted Standard GPS Time


def read_control():
    """Surveyed control as (ids, E, N, Z) -- the CSVs are P,N,E,Z,D."""
    ids, e, n, z = [], [], [], []
    for path in CONTROL_CSVS:
        with open(path, newline="") as fh:
            for row in csv.reader(fh):
                if not row or not row[0].strip():
                    continue
                ids.append(row[0].strip())
                n.append(float(row[1]))  # column 2 is NORTHING
                e.append(float(row[2]))
                z.append(float(row[3]))
    return ids, np.array(e), np.array(n), np.array(z)


def main():
    print(f"cloud: {CLOUD}")
    points = las.read_points(
        CLOUD, fields=("x", "y", "z", "gps_time", "classification",
                       "point_source_id"))
    n_pts = points["x"].size
    print(f"points: {n_pts:,}")

    # --- time base: strips sit inside the trajectory -------------------
    traj = sbet.read_sbet(SBET)
    sow = points["gps_time"] + ADJUSTED_OFFSET - GPS_WEEK * 604800
    inside = (sow >= traj["time"][0]) & (sow <= traj["time"][-1])
    print(f"\n[time base] LAS sow {sow.min():.1f}..{sow.max():.1f}, "
          f"sbet {traj['time'][0]:.1f}..{traj['time'][-1]:.1f}, "
          f"{100.0 * inside.mean():.2f}% of returns inside trajectory")

    # --- density (whole cloud) ----------------------------------------
    dens, _, _ = density.density_grid(points["x"], points["y"], cell=3.0)
    covered = dens[dens > 0]
    print(f"\n[density] cell 3 ft: median {np.median(covered):.2f} pts/ft^2 "
          f"({np.median(covered) * 10.7639:.1f} pts/m^2), "
          f"p5 {np.percentile(covered, 5):.2f}, "
          f"p95 {np.percentile(covered, 95):.2f}")

    # --- strip-to-strip dZ on ground returns --------------------------
    ground = points["classification"] == 2
    strips = {}
    for sid in np.unique(points["point_source_id"]):
        m = ground & (points["point_source_id"] == sid)
        strips[int(sid)] = {k: points[k][m] for k in ("x", "y", "z")}
        print(f"\n[strips] strip {sid}: {int(m.sum()):,} ground returns"
              if sid == 1 else f"[strips] strip {sid}: {int(m.sum()):,} ground returns")

    print("\n[strip dZ] ground returns, 6 ft cells, median per cell, b - a (ft):")
    sids = sorted(strips)
    for i, a in enumerate(sids):
        for b in sids[i + 1:]:
            result = overlap.strip_dz(strips[a], strips[b], cell=6.0)
            try:
                s = result.summary()
            except ValueError:
                print(f"  {a}-{b}: no overlap")
                continue
            print(f"  {a}-{b}: median {s['median']:+.3f}  rmse {s['rmse']:.3f}  "
                  f"p95|dz| {s['p95_abs']:.3f}  ({s['cells']} cells)")

    # --- checkpoints ---------------------------------------------------
    ids, ce, cn, cz = read_control()
    gx, gy, gz = (points[k][ground] for k in ("x", "y", "z"))
    near = np.zeros(gx.size, dtype=bool)
    for e, n in zip(ce, cn):
        near |= (np.abs(gx - e) < 60.0) & (np.abs(gy - n) < 60.0)
    surface = np.column_stack([gx[near], gy[near], gz[near]])
    print(f"\n[checkpoints] {len(ids)} surveyed points, TIN over "
          f"{surface.shape[0]:,} ground returns within 60 ft")
    dz = checkpoints.vertical_residuals(surface, np.column_stack([ce, cn, cz]))
    for pid, r in zip(ids, dz):
        print(f"  {pid:>4}: {r:+.3f} ft" if np.isfinite(r)
              else f"  {pid:>4}: outside ground coverage -- untestable")
    finite = dz[np.isfinite(dz)]
    acc = checkpoints.asprs_vertical(finite)
    med = np.median(finite)
    nmad = 1.4826 * np.median(np.abs(finite - med))
    print(f"  n {acc.n}  mean {acc.mean:+.3f}  median {med:+.3f}  "
          f"rmse {acc.rmse_z:.3f}  nva {acc.nva:.3f}  nmad {nmad:.3f} (ft)")

    # --- the pyLynceus cross-check: local median, not TIN --------------
    # pyLynceus's +0.146 ft is the median of ground returns within 3 ft
    # of each mark (formats/control.compare_to_control), which admits
    # only marks that actually have local ground returns. The TIN above
    # interpolates across gaps and admits marks near kerbs and edges;
    # the two disagree by design, and the local measure is the
    # acceptance test.
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([gx, gy]))
    local = []
    print("\n[cross-check] median of ground returns within 3 ft, lidar - control:")
    for pid, e, n, z in zip(ids, ce, cn, cz):
        idx = tree.query_ball_point([e, n], 3.0)
        if len(idx) < 5:
            print(f"  {pid:>4}: skipped ({len(idx)} within 3 ft)")
            continue
        local.append(float(np.median(gz[idx])) - z)
        print(f"  {pid:>4}: {local[-1]:+.3f} ft  ({len(idx)} neighbours)")
    local = np.array(local)
    lmed = np.median(local)
    print(f"  n {local.size}  median {lmed:+.3f}  "
          f"nmad {1.4826 * np.median(np.abs(local - lmed)):.3f} (ft)")
    print("  pyLynceus recorded +0.146 ft (robust sd 0.150, six points); "
          "2026-09-08 this script reproduced +0.146 / nmad 0.148 exactly.")


if __name__ == "__main__":
    main()
