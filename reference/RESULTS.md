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

## Phase 4: strip alignment recovers injected truth

Measured 2026-09-08 by `python -m reference.alignment_proof` -- a
Summerville-scale synthetic block (survey feet, 330 ft AGL, four
1500-ft strips in an alternating-heading chain, 220-ft swaths, 250k
points each, 0.10 ft noise, rolling terrain), with boresight
(+5e-4, -8e-4, +1.5e-3 rad) and per-strip vertical offsets (0.12,
-0.08, 0.05 ft) injected through the georef forward model. Real-SBET
application waits on Phase 4.5 (map-frame trajectory: projection +
geoid).

* Boresight recovered to within **6e-6 rad (~1.2 arcsec)** with a
  crossing line; within 1.2e-5 rad parallel-only.
* Per-strip offsets recovered to within **0.0005 ft**.
* Strip dZ (the referee): median +0.098 -> -0.007 ft, rmse 0.130 ->
  0.081 (the floor is measurement noise).
* 17,266 patch observations, 8 Gauss-Newton iterations, 32 s for
  1.25M points.

Parallel-only yaw succeeded HERE because the rolling terrain gives it
leverage; on flat terrain the same geometry is indeterminate and the
solver refuses (tests/test_align.py proves both). The observability
gate is the column-scaled normal-matrix condition (healthy blocks ~5,
degenerate ~2.4e3, gate at 200) -- raw conditioning hides degeneracy
behind the radians-vs-feet unit disparity.

## Phase 4.5: the real cloud through the real trajectory

Measured 2026-09-08 by `python -m reference.summerville_align` (real
Summerville ground strips, real SBET transformed via EPSG:6447 +
NAVD88/EPSG:6360 with the GEOID18 grid; PROJ network fetched and
cached the grid; implied N at the site: -29.08 m).

Attach diagnostics (the convention checks, all passed):

* Heading source settled EMPIRICALLY: the SBET `heading` field agrees
  with the flight track to 0.53 deg median; heading+wander is worse
  (1.55 deg). The mapping roll->roll, pitch->-pitch, yaw=pi/2-heading
  is re-derived numerically by tests/test_attach.py on every run.
* AGL median 331.9 ft (the ~100 m mission), nadir median 31.2 deg.

Baseline solve on the delivered (aligned) strips: boresight
(-1.4e-4, -5.2e-4, -8.7e-4) rad -- all under 0.05 deg -- and offsets
(+0.003, +0.025, -0.023) ft, consistent with the known dZ medians
<= 0.03 ft. The solver does not invent structure on aligned data.
Patch rms 0.180 -> 0.176 ft (surface-texture floor). 5,896
observations from 1.01M ground points, 12 s.

**Injection through the real geometry** (beta = +8e-4/-1.2e-3/+2e-3
rad, dz = 0.10/-0.07/+0.05 ft on strips 2-4): recovered relative to
baseline with boresight error <= 1.9e-5 rad (~4 arcsec) and offset
error <= 0.001 ft; dz 1-2 median +0.187 -> -0.003 ft. This exercises
the ENTIRE chain -- projection, geoid, time base, attitude mapping,
Jacobians -- and any break would destroy the recovery.

### Phase-4.5 adversarial review round (same day)

A 37-agent review panel (four lenses, three refuters per finding,
majority kill) confirmed 10 findings; all fixed and re-verified:

* **PROJ's silent "ballpark vertical transformation"**: with the geoid
  grid missing, the compound transform returned FINITE heights still
  ellipsoidal (~95 ft wrong) and the finiteness guard never fired --
  the exact trap crs.py's docstring promised to refuse. Fixed with
  allow_ballpark=False (+ only_best); measured that only_best ALONE
  does not stop it. Pinned by a test that accepts either the true
  geoid height or a refusal, never the ballpark value.
* Compound-CRS float-vertical used the horizontal unit for heights;
  now uses the vertical component's unit (metric-horizontal + ftUS
  heights is a real DOT convention). Pinned both directions.
* speed_floor was 5.0 "map units/s" -- different physics per CRS unit,
  and a hard refusal for metric slow-UAS flights. Now defaults to
  0.25 x p95 speed (unit-free), with --speed-floor to override.
* Four mutation-testing findings: every attitude-sign and einsum in
  attach could flip and the suite stayed green, because all scenes had
  R_nav = identity. Now pinned by a banked southbound scene (nonzero
  roll/pitch/yaw) asserting body vectors land where constructed, an
  apply_corrections-vs-corrected_xyz equivalence test with nonzero
  boresight, and an "AGL 300" assertion in the CLI test that catches a
  mishandled --vertical.
* Recorded, not fully fixable: a constant vertical bias below the
  flying height (wrong-sign user-supplied N) passes the AGL gate; a
  new nadir-fan gate (>60 deg refuses) catches the gross cases, and
  the docstrings say the sign is the caller's to get right.

After the fixes: 98 tests green, and the real-Summerville acceptance
reproduces identically (boresight recovery <= 1.9e-5 rad, offsets
<= 0.001 ft, dz 0.187 -> -0.003).

## Phase 6: contours and DSM from the real cloud

Measured 2026-09-08 by `python -m reference.summerville_contours`
(1-ft contours from the delivered class-2 DTM at 3-ft cells; DSM from
all returns).

* 2,152 contour lines over 40 levels (627..666 ft), 181,335 ft of
  linework, 4 s. Written as DXF (R12 3D polylines, CONTOUR_INDEX /
  CONTOUR_INTERMEDIATE layers) and GeoJSON.
* Referee 1 -- vertex consistency: all 81,190 contour vertices sit on
  their level against the DTM to 0.000 ft (median, p95 AND max). This
  is exact by construction on a shared linear surface, so it referees
  the plumbing (indexing, coordinates, joining), not the terrain; the
  analytic plane/cone tests carry the geometric correctness.
* Referee 2 -- DSM >= DTM: median canopy height 42.6 ft (a vegetated
  site), p95 87.3 ft. 33 of 209,014 cells dip below the DTM by more
  than 0.5 ft: inpaint-boundary artifacts where the DTM filled across
  a gap from higher ground while the DSM has real low returns there.
  Known, small, and at fill edges only.

### Phase-6 adversarial review round (same day)

A 33-agent panel (three lenses, three refuters per finding) confirmed
5 findings; all fixed, suite at 120 tests:

* **The DSM referee itself was flawed**: it cropped both grids from
  index zero without aligning origins (grid_edges floors each
  dataset's OWN min), which the panel proved can both fabricate and
  mask below-DTM violations on sloped data. Fixed with a world-aligned
  window; on the real Summerville cloud the origins happened to
  coincide, so the recorded numbers stand unchanged -- but the flaw
  was real and is why the referee now asserts alignment.
* **The --breaklines path invented terrain across voids**: a TIN
  interpolates every interior hole, so adding one breakline silently
  turned lakes into contoured terrain and --max-fill did nothing.
  Fixed with gridding.coverage_mask (TIN grid masked back to data
  coverage, --max-fill meaning restored); pinned by a holed-scene CLI
  test.
* Saddle cases 5/10 and the closed-ring Chaikin branch were
  mutation-unpinned (zero saddle squares in the plane/cone fixtures).
  Now pinned by explicit single-square saddle tests in both
  center-above/-below orientations and a closed-ring smoothing test.
* Killed by the panel (1/3 confirms): a strict-AutoCAD LTYPE-table
  concern -- ezdxf strict + recover-audit accept the DXF with zero
  errors.
