# Summerville reference results

2026-09-08, Phase 2: `pyargus qa-report` reproduces every number below
in one command (same density stats, same three dZ pairs, same
+0.146 / nmad 0.148 over six marks with seven skipped, week 2385 at
100.00%). Rerun it after any QA change:

    pyargus qa-report Z:/Users/BJordan/Summerville_SS/Summerville_SS.las \
      --out reference/reports/summerville --control-order pnez \
      --control "Z:/Users/BJordan/Summerville_SS/1-4,200-207.csv" \
      --control "Z:/Users/BJordan/Summerville_SS/205.csv" \
      --sbet "Z:/Users/BJordan/Summerville_SS/Area_/Cycle_250926_134000_122SN030/POS/sbet_NAD83(2011)[2010.0].out"

Measured 2026-09-08 by `reference/summerville.py` against
`Z:\Users\BJordan\Summerville_SS\Summerville_SS.las` (15,284,332 points,
four strips, classified) and the surveyed control (13 marks, P,N,E,Z
CSVs). Everything on Z: read-only. Units are US survey feet unless
marked.

## Time base

LAS gps_time is Adjusted Standard GPS; with week 2385,
`sow = gps_time + 1e9 - 2385*604800` puts 100.00% of returns inside the
SBET window (481638..482252 s, 200 Hz, 614 s flight). Validates the
SBET reader and the week arithmetic against real POSPac output.

## Density

3-ft cells: median 8.33 pts/ft² (89.7 pts/m²), p5 0.44, p95 22.89.
The p5/p95 spread is overlap structure, not a defect: multi-strip
coverage in the middle, single-strip at the edges.

## Strip-to-strip dZ (ground returns, 6-ft cells, b − a)

| pair | median | rmse | p95 abs dz | cells |
|------|--------|------|------------|-------|
| 1–2  | +0.000 | 0.210 | 0.380 | 2113 |
| 2–3  | −0.005 | 0.230 | 0.480 | 3450 |
| 3–4  | +0.030 | 0.217 | 0.448 |  864 |

Strips form a chain (1–3, 1–4, 2–4 do not overlap). Medians ≤ 0.03 ft:
this delivery is already well aligned, so Summerville validates the QA
machinery but is NOT a "before" case for Phase-4 alignment — a
deliberately mis-adjusted copy (or synthetic misalignment injected via
the georef model) will be needed to prove the solver moves things the
right way.

## Control comparison — the acceptance test

Local measure (median of ground returns within 3 ft of each mark,
lidar − control, the pyLynceus `compare_to_control` method):

| mark | dz (ft) | neighbours |
|------|---------|------------|
| 1    | +0.361  | 53  |
| 2    | +0.188  | 107 |
| 3    | −0.109  | 86  |
| 4    | +0.120  | 64  |
| 202  | +0.171  | 43  |
| 203  | −0.011  | 12  |

n 6, median **+0.146**, nmad **0.148** — reproducing pyLynceus's
recorded +0.146 ft (robust sd 0.150) exactly, same six marks. This
cross-validates the entire pyArgus LAS path, control parsing, and
ground-class handling against an independent codebase on real data.

Marks 200, 201, 208 have no ground return within 3 ft (road-edge
situations); 204–207 lie outside ground coverage entirely (204, 206,
207 are north of the cloud's extent).

TIN measure (`qa.checkpoints`, 60-ft gather) over the 9 in-coverage
marks: mean −0.011, median −0.020, rmse 0.247, NVA 0.483, nmad 0.153.
It disagrees with the local measure by design: interpolation admits
marks without local ground returns and spans kerbs and ditches. Quote
the local measure; use the TIN measure only where its assumptions are
stated.

## Phase 3: SMRF ground classification vs the delivered ground

Measured 2026-09-08 by `reference/summerville_ground.py` (in-core SMRF,
`python -m reference.summerville_ground`). Parameters: cell 3, slope
0.15, window 60, threshold 1.5, scalar 1.25, low_cut OFF (see below).
Runtime 10 s on the 12.78M last returns.

The delivered classification labels a deliberately thin ground class,
so raw point precision against it measures a labeling convention, not
surface error. The acceptance numbers:

* **Recall 0.9992** -- essentially every delivered ground point is
  SMRF ground.
* **FP height above the delivered-ground DTM**: median +0.15 ft,
  96.2% within +/-1.0 ft, p99 +1.31 ft. The 3.5M extra points hug the
  surface (delivered class 1/3, near-ground returns).
* **DTM vs DTM** over 109,525 common 3-ft cells: median +0.111 ft,
  nmad 0.126, p95 0.567.
* **Control** (3-ft local median on SMRF ground): n 6, median
  +0.193 ft, nmad 0.133 -- beside the delivered ground's +0.146/0.148,
  the +0.05 shift consistent with SMRF's slightly thicker ground.
* Context: point confusion agreement 0.771, precision 0.224,
  kappa 0.289. Recorded, not the acceptance.

Honest gaps: 1,622 of 4,951 delivered-noise (class 7) points classify
as ground (they anchor min-cells; a point-level low filter at this
density is the fix if it matters); the FP tail to +1.31 ft is
near-ground vegetation inherent to a one-surface filter.

**low_cut must stay OFF under canopy**: cell-level low cutting flagged
144k cells -- the under-canopy ground penetrations themselves -- and
pushed the DEM into the canopy (FP p90 +39 ft). Measured twice with
two designs before the cause was understood; details in
`classify/ground.py`'s docstring.
