"""Phase-3 acceptance: SMRF against Summerville's delivered ground.

The delivered cloud carries a production classification (1,011,700
class-2 points that put the cloud on the surveyed control at +0.146 ft),
so it is the answer key: classify the same points from scratch and the
confusion matrix says how far the in-core SMRF is from the delivery.
The delivered classification is a strong reference, not truth -- the
numbers say distance, not who is right.

Read-only against Z:, run by hand, prints. Parameters are the meter
defaults scaled to survey feet. Class 7 (delivered low noise) is
scored separately: SMRF sees those points too, and whether cut_lows
rejects them is part of the result.

Also compares the DTM built from SMRF ground with the DTM built from
delivered ground over the cells both cover.
"""

import time

import numpy as np

from pyargus.classify import ground
from pyargus.core import gridding
from pyargus.formats import las
from pyargus.qa import checkpoints
from pyargus.surfaces import dtm
from reference.summerville import CLOUD, read_control

# low_cut stays OFF: under canopy the min-surface is salt-and-pepper
# and a cell-level low cut deletes the ground penetrations themselves
# (measured: 144k cells flagged, DEM in the canopy, FP p90 +39 ft).
PARAMS = dict(cell=3.0, slope=0.15, window=60.0, threshold=1.5,
              scalar=1.25, low_cut=None)


def main():
    print(f"cloud: {CLOUD}")
    points = las.read_points(
        CLOUD, fields=("x", "y", "z", "classification",
                       "return_number", "number_of_returns"))
    n = points["x"].size
    delivered = points["classification"] == 2
    noise = points["classification"] == 7
    eligible = points["return_number"] == points["number_of_returns"]
    print(f"points: {n:,}  delivered ground {delivered.sum():,}  "
          f"delivered noise {noise.sum():,}  last returns {eligible.sum():,}")
    print(f"params: {PARAMS}")

    t0 = time.perf_counter()
    result = ground.smrf(points["x"][eligible], points["y"][eligible],
                         points["z"][eligible], **PARAMS)
    print(f"smrf:   {time.perf_counter() - t0:.1f} s, "
          f"{int(result.object_cells.sum()):,} object cells, "
          f"{int(result.low_cells.sum()):,} low cells")

    predicted = np.zeros(n, dtype=bool)
    predicted[np.flatnonzero(eligible)[result.ground]] = True

    # Raw point-set agreement is recorded, but it is NOT the acceptance
    # number: the delivery labels a deliberately thin ground class
    # (surface-hugging returns sit in class 1/3), so precision against
    # it measures a labeling convention. What must be right: recall
    # (their ground is our ground), FP height (our extras hug the
    # surface), the DTM difference, and the control comparison.
    print("\n[confusion vs delivered class 2 -- context, not acceptance]")
    s = ground.confusion(predicted, delivered)
    print(f"  agreement {s['agreement']:.4f}  precision {s['precision']:.4f}  "
          f"recall {s['recall']:.4f}  kappa {s['kappa']:.4f}")
    caught = int(np.count_nonzero(predicted & noise))
    print(f"  delivered-noise points classified ground: {caught:,} "
          f"of {int(noise.sum()):,}")

    print("\n[FP height above delivered-ground DTM]")
    dg, xe, ye = dtm.dtm_grid(points["x"][delivered], points["y"][delivered],
                              points["z"][delivered], cell=3.0, max_fill=10)
    fp = predicted & ~delivered & ~noise
    fz = points["z"][fp] - gridding.bilinear_sample(
        np.where(np.isfinite(dg), dg, np.nan),
        points["x"][fp], points["y"][fp], xe, ye)
    fz = fz[np.isfinite(fz)]
    print(f"  {fz.size:,} measurable: median {np.median(fz):+.2f}  "
          f"p90 {np.percentile(fz, 90):+.2f}  p99 {np.percentile(fz, 99):+.2f} ft")
    print(f"  within +/-0.5 ft: {100 * np.mean(np.abs(fz) <= 0.5):.1f}%   "
          f"within +/-1.0 ft: {100 * np.mean(np.abs(fz) <= 1.0):.1f}%")

    print("\n[DTM: SMRF ground vs delivered ground, 3 ft cells]")
    ours = dtm.dtm_grid(points["x"][predicted], points["y"][predicted],
                        points["z"][predicted], cell=3.0, max_fill=0)[0]
    theirs = dtm.dtm_grid(points["x"][delivered], points["y"][delivered],
                          points["z"][delivered], cell=3.0, max_fill=0)[0]
    nx = min(ours.shape[0], theirs.shape[0])
    ny = min(ours.shape[1], theirs.shape[1])
    both = np.isfinite(ours[:nx, :ny]) & np.isfinite(theirs[:nx, :ny])
    diff = (ours[:nx, :ny] - theirs[:nx, :ny])[both]
    med = np.median(diff)
    print(f"  common cells {diff.size:,}: median {med:+.3f} ft, "
          f"nmad {1.4826 * np.median(np.abs(diff - med)):.3f}, "
          f"p95|d| {np.percentile(np.abs(diff), 95):.3f}")

    print("\n[control vs SMRF ground, 3 ft local median]")
    ids, ce, cn, cz = read_control()
    gxyz = np.column_stack([points["x"][predicted], points["y"][predicted],
                            points["z"][predicted]])
    cmp_ = checkpoints.local_median_residuals(
        gxyz, ids, np.column_stack([ce, cn, cz]))
    stats = checkpoints.robust_summary(cmp_.values())
    print(f"  n {stats['n']}  median {stats['median']:+.3f}  "
          f"nmad {stats['nmad']:.3f} ft  "
          f"(delivered ground gave +0.146 / 0.148 on 6 marks)")


if __name__ == "__main__":
    main()
