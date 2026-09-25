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

  *2026-09-23:* that 1,622 is the bare SMRF core, which this script
  calls directly with every last return. The COMMANDS no longer do
  that: `classify-ground` keeps points already flagged 7 or 18 out of
  the surface and carries their class through, so on the same cloud
  both commands now label **0** of the 4,951 (measured in the tiled
  acceptance below). The core's own behaviour is unchanged and so is
  this number; it measures what SMRF does when noise is handed to it,
  which is why `noise-cut` exists.

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

## Phase 5: above-ground classification vs the delivered classes

Measured 2026-09-08 by `python -m reference.summerville_above` --
random forest on 8 handcrafted features, SPATIAL holdout (train west,
evaluate east; 7.9M eval points), 31 s end to end on 14.3M points.

* **Agreement 0.9972, kappa 0.9881** against delivered classes
  3/4/5/6. Vegetation tiers: recalls 0.983-0.998, precisions
  0.955-1.000 -- HAG dominates (importance 0.62), confirming the
  roadmap's explainable-features bet.
* **Building recall 0.918, precision 0.558** -- quote WITH its
  context: buildings are 0.06% of the eval half (4,814 points), so a
  whisper of canopy confusion swamps precision on this rural site.
  The number travels with the site, not the method.
* **Deployment conditions** (the panel's honesty demand): the same
  forest scored behind SMRF ground instead of delivered ground drops
  only -0.0026 to 0.9946; 394k delivered class-3 points are absorbed
  into SMRF's thicker ground and leave the universe (recorded, not
  hidden). The train/deploy ground shift is real, measured, small.
* Delivered class-1 (unlabeled) points split 46/53 into low/high
  vegetation -- the delivery just never labeled them.

### Phase-5 adversarial review round (same day)

A 39-agent panel confirmed 8 findings; all fixed, suite at 146 tests:

* **One-pass covariance cancelled catastrophically at state-plane
  magnitudes** -- the shape features were translation-VARIANT
  (sphericity halved moving the same cell to Summerville
  coordinates). Two-pass deviations now; pinned by an invariance
  test at 2.26e6 ft offsets.
* **Class-7 noise poisoned its neighbours' cell features** (three
  injected low-noise points flipped 249 building points). Noise is
  now EXCLUDED from the feature computation via ignore_mask, never
  merely relabeled after; pinned by an injected-noise CLI test.
* The acceptance was scored only behind delivered ground
  (train/deploy shift unmeasured) -- the SMRF-ground section above is
  the fix. The module docstring promised acceptance metrics travel in
  the model file; softened to match reality (notes travel, numbers
  live here). --classes crashed raw on a trailing comma (now a named
  SystemExit, trailing commas tolerated); load() crashed raw on
  non-model joblib files (now a schema guard + a pickle warning).

## Time-dependent (drift) corrections

Measured 2026-09-09 by the drift configuration of
`python -m reference.alignment_proof`: the crossing-line block again,
staggered strip start times, and a sinusoidal GNSS wander injected
into strip 1 (0.10 ft amplitude, 25 s period -- on top of its 0.12 ft
constant and the usual boresight), solved as piecewise-linear vertical
corrections in time (5-s nodes, `--drift-spacing`).

The workflow measured is the one reality requires --
**calibrate-then-drift**:

* Boresight comes from the CLEAN block (recovered there to 6e-6 rad)
  and is HELD during the drift solve. Calibrating on the wandering
  block instead errs pitch by **1.05e-3 rad** -- worse than the
  injected pitch -- and solving boresight+drift together is no better
  (**1.24e-3 rad**, also measured and pinned): over smooth terrain,
  pitch's along-track dz signature is a slow function of time that
  each strip's free drift curve can absorb, with only stiffness
  resisting. Both contamination numbers are pinned in run_all as
  documentation: a block that needs drift corrections is not
  calibration data.
* With the calibration held, the recovered curve spans -0.210..-0.015
  ft against the injected -0.22..-0.02, and matches the injected
  sinusoid's shape to **0.033 ft max** at interior nodes
  (mean-removed; ~0.02 of that is the chord error inherent to 5-s
  linear segments on a 25-s sine).
* Strip dZ (the referee): rmse 0.124 -> **0.081 ft**, the clean
  block's own floor -- the wander is scrubbed from the surface.
* Observability in drift mode is judged on the NESTED CONSTANT system
  (equal nodes = a constant), because the stiffness rows regularize
  the drift system itself and drag degenerate geometry's conditioning
  toward healthy (measured: 1.1e5 vs 2.6e5, no safe gate there; the
  constant system separates 5 vs 2.4e3 at the proven 200 gate).
* Full-cloud application (`--write`) interpolates each point's
  correction at its own GPS time, the same clamped piecewise-linear
  model the solver fits; drift mode ignores the per-strip means to
  avoid double-correcting.

### Drift adversarial review round (same day)

A 92-agent panel (four lenses, two finders each, three refuters per
finding) confirmed one headline defect and a set of refusal and test
gaps; all fixed, suite at 175 tests, every number above re-measured
after the fixes:

* **The stiffness prior silently washed out (iterated Tikhonov)**:
  stiffness and gauge pseudo-observations carried rhs 0 on every
  Gauss-Newton iteration while updates accumulated, so the penalty
  constrained each iteration's INCREMENT, not the curve -- the solved
  drift depended on max_iterations (panel measured the recovered
  amplitude climbing 0.0165 -> 0.0737 as iterations rose) and the
  tolerance stop never fired. Fixed: the rhs carries the current
  penalty residual. Node values are now identical at max_iterations 8
  vs 24, solves converge in 6-7 iterations, and the shape error
  improved 0.039 -> 0.033 ft. Pinned by an iteration-count-invariance
  test.
* **Stiffness became spacing-invariant** (row weight ~ 1/sqrt(node
  step), approximating a rate-of-change integral): refining
  drift_spacing no longer dilutes the smoothing.
* **Refusals grew teeth**: drift_spacing <= 0 was a raw
  ZeroDivisionError (0) or a silent 2-node ramp (negative);
  drift_stiffness <= 0 returned ~0.65 ft of invented drift on
  perfectly aligned strips with both observability gates green; and
  the observation-count guard credited stiffness rows, which cancels
  the node count algebraically -- no spacing, however absurd, could
  ever refuse (a --drift-spacing typo was a memory blowout). All
  three are named refusals now; a node explosion says "widen
  drift_spacing".
* The linearized solve now runs in the COLUMN-SCALED space the
  condition gate actually measures, instead of gating one matrix and
  inverting another.
* **Relative-only drift documented and measured**: patches observe
  only DIFFERENCES of drift curves, so without control the stiffness
  prior SPLITS a one-strip wander between overlapping strips
  (measured: half and half on a two-strip block; the strip dZ
  collapses either way). The CLI round-trip test injects a wander on
  one strip, pins the common mode with 27 surveyed marks, and demands
  the right strip move (max 0.036 ft residual against pre-wander
  truth; the untouched strip stays within 0.016).
* Test gaps closed: bracket() pinned against np.interp including
  end-clamping (the old test discarded its outputs); drift mode now
  proves it REFUSES degenerate geometry (deleting the nested-constant
  gate previously survived all tests); drift+control absolute datum
  covered (shared 0.30 bias pulled to truth through the drift solve);
  the strip-0 zero-mean gauge convention asserted. The Huber
  exemption of stiffness/gauge rows stays pinned by documentation
  only -- measured: on clean synthetics the mutation is
  outcome-invisible; its value is robustness policy under
  contamination.
* The "1.24e-3 together-mode" figure the docstrings quoted is now
  actually produced by this harness and pinned (it previously lived
  nowhere in committed code -- an unhonored claim).

## Colorization: the cloud through the imagery

Measured 2026-09-10 by `python -m reference.summerville_colorize`
(`pyargus colorize` is the command form): Summerville_SS.las painted
from the delivered TrueView 660 imagery -- 1083 JPEGs across
Nadir/Port/Starboard, the LP360 EO CSV, per-camera `.cal` sidecars,
quarter_turns 3. 15.28M points in 275 s.

* **95.3% colored** from 1,033 of 1,083 photos; 496 points are seen by
  no nearby photo. The most-centred view is blocked for **31.5%** of
  the cloud -- 42 ft median canopy at this site -- and a next-best
  view rescues 4.10M of those 4.82M points, leaving **4.7% hidden in
  every candidate frame**. Those stay uncolored, which is the honest
  answer: paint-through would color ground under a tree with the tree.
  (The first version of this feature had no fallback and built each
  photo's depth grid only from the points it had been assigned; it
  colored 70.9%. See the occlusion note below.)
* **Cross-camera referee, with its scale measured**: 300k
  nadir-colored points recolored through the OBLIQUE cameras only
  agree to **median |dRGB| (26, 25, 23) of 255**. The anchors that
  make that number mean something are measured by
  `reference/colorize_referee_scale.py` on a common 100k sample:
  recoloring through OTHER NADIR frames -- same lens, same look
  angle, so whatever it measures is frame-to-frame radiometry, not
  geometry -- gives **19**, and mis-stating the oblique
  `quarter_turns` gives **38**. Healthy sits 7 above the radiometric
  floor and 12 below the geometric fault. Pinned below 30.

  All three numbers rose by about 2 when the occlusion fallback
  landed, INCLUDING the floor, which is the control: at 95% coverage
  the sample carries far more points seen only at steep obliquity, so
  every configuration compares harder geometry than it did at 71%.
  The referee's position BETWEEN its anchors is what carries meaning,
  and that barely moved.
* **Vegetation greener than ground**: mean G-R is +20.3 over the
  delivered vegetation classes vs +9.0 over class-2 ground
  (margin +11.3 of 255) -- colors land on the right objects.
* Intensity-vs-luminance was tried as a referee and measured
  UNINFORMATIVE (r = -0.08 on ground): lidar NIR amplitude and
  visible brightness legitimately decorrelate across grass vs
  asphalt. Recorded so nobody retries it.

### The convention layer, and what the review panel changed

Colorization is won or lost in the conventions, and every choice is
pinned by tests that re-derive the answer independently (similar
triangles, np.rot90 index algebra, Agisoft's own normalised
polynomial).

* Rotation comes from the EO CSV's **Direction/Up vectors**, never
  from any angle column (LP360's OPK columns disagree with its
  platform angles by up to 79 deg; pyLynceus's adjusted_eo.csv has no
  angle columns at all). One reader covers both producers.
* **The lens model is evaluated in the STORED IMAGE's own grid** --
  Agisoft's equations in Agisoft's units, transplanted nowhere. The
  first version worked in a millimetre y-up "photo frame" and rotated
  the result into the stored grid afterwards. Radial terms survive
  that; CX/CY and P1/P2 do not, and the shipped TrueView default is
  `quarter_turns=3`. The eighth review panel measured a **~27 px
  systematic on exactly the production path**, invisible to a suite
  that only ever combined distortion with `quarter_turns=0`. Fixing
  it moved the cross-camera referee from 26 to 23 against an
  unchanged 37 for the deliberate fault and a 17-18 radiometric
  floor: three different lenses agreeing better with each other is
  independent evidence the fix was real.
* **A field-of-view guard**, because Brown-Conrady says nothing
  outside the field it was fitted in. Extrapolated far off-axis a
  barrel lens folds back: the panel reproduced a point 62 deg
  off-axis landing on an ordinary pixel -- sometimes the exact image
  center -- and then WINNING the most-centered contest. Each camera
  now computes where its own model folds, refuses a calibration that
  folds before reaching its own frame corner, and masks points beyond
  the fold.
* **The selection score is an off-axis ANGLE**, not a pixel count:
  pixel distance is f*tan(angle), so across cameras of different
  focal length the shorter lens would win every contest at equal
  geometry.
* **Refusals the panel earned**: a present-but-unreadable calibration
  key (silently zeroing K1 alone is ~70 px at the corner); a sidecar
  holding several cameras; an image whose size contradicts its
  calibration (checked from JPEG headers UP FRONT, not as a traceback
  at image 900); two different files sharing one basename (every EO
  row for that name would sample one exposure through the other's
  pose); an up vector inside the noise band where roll is decided by
  the export's 9th decimal; a non-integer `quarter_turns`.
* **Coverage is the datum gate.** The overlap and AGL checks catch a
  frame mismatch that SEPARATES the two datasets, but one that merely
  scales them -- metres written over survey feet, the exact lie the
  LP360 header tells -- keeps the boxes overlapping and the AGL
  positive. What it does change is how much of the cloud gets a
  color, so `--min-coverage` refuses below 5% and anything under half
  prints a caution naming the cause.
* LAS RGB is 16-bit: 8-bit samples ship shifted left 8 bits, and a
  point-format-6 input is converted to 7 with an announcement.

### Occlusion: what the second pass changed

The first version built each photo's depth grid from the points
ASSIGNED to that photo, because the planner was point-major and that
is the only per-photo set such a pass has in hand. It left a real
hole -- an occluder whose own best photo was a different one entered
no grid and shadowed nothing -- and the guarantee was "occlusion by
what this photo colored" rather than "by the cloud". Since a point's
occluder sits a few feet from it horizontally, which is exactly the
neighbourhood its OTHER candidate photos own, the hole opened along
every footprint boundary.

The planner is photo-major now: candidate (point, photo) pairs are
collected for a BATCH of photos, each photo renders its grid from all
of them, and the contest runs over the survivors. Batching keeps it
affordable -- the candidate set is ~122M pairs at Summerville, a
per-photo grid ~1.2 MB, and `memory_budget_mb` fixes how many photos
share one pass over the cloud. A point whose best view is blocked
falls back to its next-best unblocked view. Coverage went 70.9% ->
95.3% and runtime 235 -> 275 s.

Pinned by two tests that assert WHICH photo did the colouring: a
blocked best view must be rescued by the oblique, and a point hidden
in every frame must stay uncolored. The test they replace asserted
only that the hidden point ended up colored -- which the fallback
also satisfies, so it passed unchanged against the fixed code while
its docstring still described the bug. A test that cannot tell the
fix from the defect is not a pin.

### Honest gaps (pinned by tests so they cannot drift)

* **A one-cell halo of visible ground is marked occluded** at every
  depth edge, because an `occlusion_grid` cell straddling a
  discontinuity mixes occluder and background (~0.7 ft on the ground
  at Summerville). The fallback softens the cost: such a point is
  usually visible in another candidate frame and is colored from
  there rather than lost.
* The candidate set is the k nearest footprint centers, computed
  against a single plane at the cloud's median z, so `n_unseen` means
  "no nearby photo saw it", not "outside every frame" -- on strong
  relief a distant frame that does contain the point is never asked.
* The cross-camera referee's oblique recolor spreads its sample over
  ~700 frames, so occlusion barely fires inside the referee itself:
  a few of its counts are genuinely oblique-hidden ground rather than
  radiometry.

## Streaming reads, and COPC

Measured 2026-09-10 by `python -m reference.summerville_streaming`.
The suite read whole clouds into memory, which put a ceiling on what
it could open at all: at ~39 bytes per point for the default fields,
before laspy's own packed record, a 350M-point delivery needs about
13.6 GB of arrays. Two of the files on this project's own reference
drive are past that line.

* **Equality first.** On Summerville_SS.las (15.28M points, pf7,
  three extra dimensions, a real CRS) a streamed pass and a
  whole-file read return **identical arrays for all seven fields**,
  and the streamed density grid is **identical to the whole-cloud
  grid** -- same edges, same counts. A faster path that answers
  differently is a second program wearing the first one's name, so
  this is the check that licenses the rest.
* **Then scale.** `UAS Flight Mission.PointCloud25D.las` --
  349,794,884 points, 9.09 GB, the dense image-matching product
  beside the lidar -- streams a 3-ft density grid in **124 s at a
  peak of 138 MB** for the whole process (27 MB of that is the bare
  interpreter). Against ~13,642 MB for the whole-file path: the file
  went from unopenable to routine.
* `pyargus info` answers from the header alone -- 349.79M points,
  extent, scales, CRS, extra dimensions, and an estimate of what a
  whole read would cost -- in **0.6 s on a 9.09 GB file**, without
  touching a point.
* `density`, `align --write` and `colorize --out` now stream. The
  latter two used to read the entire file TWICE: once for the maths
  and again to write the result. The write is a chunked copy that
  carries the point format, extra bytes, scales, offsets and CRS VLRs
  across untouched, because the output header IS the input header.

### COPC

`pyargus copc cloud.las --out cloud.copc.laz` rewrites a cloud with
an octree index, so a reader can ask for a bounding box or a
resolution instead of a whole file. laspy READS COPC and cannot write
it -- no header care can add an octree to a file that has none -- so
this shells out to pdal, and is deliberate about it: it probes PATH,
`PDAL_EXE`, then the QGIS/OSGeo4W installs where pdal usually hides,
and REFUSES by name with the alternatives when none is found.

Two traps the recon measured, both now closed:

* pdal's COPC writer **drops extra dimensions in silence** unless
  `--writers.copc.extra_dims=all` is passed. Summerville's
  Amplitude/Reflectance/Deviation would vanish with no error at all.
  Both that and `--writers.copc.forward=all` are passed on every
  call, never optional, and the output is REOPENED and checked
  against the source for point count, extra dimensions and its COPC
  VLR before the command reports success.
* `resolution` is not a sampling fraction: it maps to a set of octree
  LEVELS, so a shallow tree offers few distinct answers and several
  different resolutions return exactly the same points (measured:
  50, 20 and 10 all returned 57% of a 120k-point tile). Pinned as
  monotonic rather than proportional.

### Streaming adversarial review round (same day)

A 179-agent panel (four lenses, three refuters per finding) confirmed
eight defects in a layer that sits under every command in the suite.
All fixed, each pinned by a test that fails against the old
behaviour; the real-data numbers above were re-measured afterwards
and did not move.

* **A stale LAS header silently truncated the density.** The streamed
  grid fixed its bins from the header while `density_grid` derives
  them from the points, and `np.histogram2d` DISCARDS samples outside
  explicit bins. On a file whose header no longer describes its own
  points -- a clip or a reprojection that never rewrote min/max --
  `pyargus density` printed a believable number computed from a
  subset. Reproduced: 14,977 of 20,000 points dropped in silence.
  Now every outside point is counted and REFUSED by name, with
  `--rescan` offering a first pass that takes the extent from the
  points. The equality test could not have caught this: its fixture
  is written by laspy, which always writes a correct header.
* **`stream_update` dropped every EVLR**, and LAS 1.4 permits the OGC
  WKT there -- so `align --write` and `colorize --out` could hand
  back a delivery with its georeferencing stripped and no error.
* **A COPC source could not be streamed at all**: laspy refuses to
  write a header still claiming an octree, so the files `pyargus
  copc` produces aborted the rest of the suite with a raw
  NotImplementedError and a 0-byte output. The output header now
  drops the COPC VLRs, because a point-by-point copy is a plain LAZ.
* **`stream_update(src, src)` destroyed the cloud** it was reading and
  reported success. Refused.
* **An oversized COPC bounding box returned ZERO points.** laspy casts
  the request into the file's scaled integer system unchecked, so a
  box merely larger than the cloud overflowed int32. Bounds are
  clamped to the file's extent first, and a box that misses entirely
  refuses rather than returning nothing.
* **A failure partway through a write left a truncated cloud** at the
  destination -- valid, openable, quietly missing its tail. The write
  now goes to a temporary beside the target and is renamed into place
  only after the last chunk.
* A zero-point file accepted any field name (the per-record check
  never ran), and ignored a requested point format. Both now resolve
  from the header before the first chunk.
* An update returning a length-1 array broadcast silently over a
  whole chunk; lengths are checked.

Twenty-nine further claims were killed by their refuters, including
several about `find_pdal`'s version sorting and about RESULTS.md
numbers being unreproducible.

### The desktop stage

`pyargus gui` grew a Colorize stage. It and the CLI are thin callers
of one function, `imagery.job.colorize_cloud`, so the two front ends
cannot drift; the stage's numeric defaults are read from
`cli.build_parser()` rather than retyped, and a test pins them. That
is the Phase-7 lesson applied in advance: the GUI's alignment
defaults had drifted from the CLI's once already, and nothing noticed
until a panel went looking.

### Honest gaps

* **A COPC query's memory tracks the octree nodes it touches, not the
  points it returns.** The coarse levels span the whole tile and are
  always touched, so a small box is not a small read -- measured on a
  5M-point file, a query over 1% of the area decompressed 4.07M
  points to hand back 50k. Use `resolution` when full density is not
  needed.
* `read_points` still exists and is still the right call for anything
  needing global state -- the TIN, the alignment solve. Those remain
  whole-cloud operations. SMRF ground classification now tiles with a
  halo; see the next section.
* No COPC file exists anywhere on the reference drive yet; the
  vendors deliver LAS and LAZ. The COPC path is tested end to end
  against files this suite writes itself.
* A COPC copy made by `stream_update` comes back a PLAIN LAZ: an
  octree cannot survive a point-by-point rewrite, and claiming one it
  no longer has would be worse. Re-run `pyargus copc` on the result
  to rebuild the index.
* pdal lives inside a QGIS install here, not on PATH. That is a
  dependency on software which could move or be uninstalled, which
  is why the probe reports what it found and the refusal names the
  alternatives.

## Tiled ground classification

Measured 2026-09-11 by `python -m reference.summerville_tiled` and
`python -m reference.sh151_tiled_strip` (`pyargus classify-ground
--tiled`). SMRF was the last consumer in the suite that wanted a whole
cloud at once, which put SH 151's 917M points across 22 strips out of
reach however well the reads streamed.

The way past it is the shape of the algorithm. Its expensive half
produces a RASTER -- a DEM, its slope and two masks -- and a raster is
small whatever the point count: **24 MB for a 10,569 ft SH 151 strip
of 41.4M points** (1.32M cells). Its cheap half judges each point
against that raster with one bilinear sample, which streams perfectly.
So the surface is built tile by tile, assembled once, and applied in a
streaming pass.

The claim is EQUALITY with the plain command, so that is what is
measured: `classify-ground` with and without `--tiled` -- the two
drivers in `classify/job.py`, which share one lattice, one candidate
policy and one labeling rule -- on the same file, their written
classifications compared row by row. Seams have to be real to mean
anything, because a tile whose halo box spans the project IS the
whole-cloud run; so both acceptances refuse to report unless every
tile's box stops short of the project.

* **Summerville, in the gate** (cell 3, window 30: halo 330 ft, SMRF's
  own reach; 600 ft cores). 12 tiles, every one with a real seam, the
  largest box 51% of the project area. **0 of 15,284,332
  classifications differ** from the plain command; 4,517,490 ground
  either way, and 0 of the 2,504,042 non-last returns labeled ground
  by either. 16 s whole, 20 s tiled. Window 30 rather than 60 because
  at 60 the halo is 1,260 ft and swallows most of a 1,841 ft project:
  no tile there can have a seam.
* **An SH 151 strip, at the survey-feet defaults, by hand** (cell 3,
  window 60: the DEFAULT halo of 1,260 ft; 1,500 ft cores).
  `0003_F1_328_B04_LCP2_s.las`, 41,366,226 points over 10,569 x 1,121
  ft. 8 tiles, every one with a real seam, the largest box 38% of the
  strip. **0 of 41,366,226 classifications differ**; 17,612,866 ground
  either way. 51 s whole, 109 s tiled (9 passes, no index). Not in the
  gate: it reads client data and holds the whole strip to compare.

### Noise classes, and what they changed here (2026-09-23)

Summerville's delivery carries 4,951 class-7 points, so this acceptance
also measures the noise policy on real data. `candidates()` no longer
admits a point flagged 7 or 18 and `labels()` carries its class
through, in both drivers:

* **0 of the 4,951 are labeled ground** by either command, and all
  4,951 come out carrying their own class. Before the change the two
  commands labeled **1,556** of them ground -- the whole-cloud ground
  count moved 4,519,046 -> 4,517,490 (fraction 0.29566 -> 0.29556),
  which is the entire recorded difference.
* `max_tile_points` moved 11,054,341 -> **11,050,836**: the 3,505
  class-7 last returns inside the largest halo box are no longer read
  into that tile's surface. The equality claim is untouched (0
  mismatches), and so is every other recorded number in the battery.
* Five checks were added to the gate (`delivered_noise`,
  `noise_as_ground`, `noise_kept`, `whole_noise`, `tiled_noise`), so
  the policy is pinned on a real delivery rather than on synthetic
  clouds alone: 78 checks.

What made this necessary was measured on a real two-line client
delivery (the script that re-runs that measurement is kept with the
job's private records): its lines, classified straight from the vendor
export, carry **over a hundred gross outliers**, nearly all of them
low, **more than half of them labeled ground**, and at more than a
dozen pits the classified cloud puts ground **up to tens of feet above** the
vendor's own class-2 surface within one 6-ft cell -- canopy and roofs
pulled into class 2 by the pit the opening cannot remove.

This section was rewritten after its adversarial review (below): the
first version's "0 of 15,284,332" compared the tiled run with a mask it
built for itself under a rule the plain command does not use, and its
tiles' boxes covered the whole project, so it measured neither the
command nor a seam.

### The halo is the whole problem

SMRF's progressive opening is ITERATIVE: each round opens the previous
round's output, so influence accumulates. One opening of radius r
reaches 2r cells, and the cascade r = 1..R reaches R(R+1) -- at the
survey-feet defaults (cell 3, window 60) that is 420 cells, **1,260
ft**. Measured on a hard synthetic scene with a building straddling
the seam (cell 3, window 30, bound 330):

| halo | result |
|------|--------|
| 0    | DEM wrong by 30.7 units, 197 points misclassified |
| 12   | DEM exact, 8 points still differ (the slope raster) |
| 60   | exact: identical DEM and identical ground mask |
| 330  | exact |

So twice the window sufficed there, a quarter of the bound. The
DEFAULT is the bound anyway, because "openings usually converge" is
not a guarantee and a seam that silently classifies differently from a
whole-cloud run is the defect this suite exists to refuse. A halo
under 2 * window refuses by name: a single opening already reaches
that far. The test suite pins both the equality AND the failure --
one test assembles a no-halo surface by hand to show the 30-unit seam
error the guard prevents, because a guard nothing demonstrates is
decoration.

### Honest gaps

* **What one tile holds is set by its halo box, not the raster.** The
  box is the core grown by the halo on every side, and the halo is
  fixed by SMRF's reach, so it can never be much smaller than 2 * halo
  across: 2,520 ft at the survey-feet defaults. Measured: the largest
  Summerville tile held 11,050,836 points (11,054,341 before class-7
  points were kept out of the surface on 2026-09-23; 51% of the AREA,
  86% of the last returns either way -- density is not even), and the largest strip tile
  8,610,889. At the DEFAULT tile size (six halos) the strip plans as 2
  tiles, the larger box 83% of the strip, and Summerville as one tile
  holding everything. Tiling bounds memory only when `--tile-size` is
  set smaller, and then the boxes overlap more: the job logs the plan's
  cost (how many times the boxes cover the project; the largest box)
  before it runs, and the most points one tile held after.
* **Without a COPC index every tile is a full pass over the file**,
  plus one to write (plus one with `--rescan`); the job counts them.
  An index removes the passes but not the overlap -- and a small COPC
  box still decompresses the coarse octree levels, which span the
  whole file (a 1% box cost 77% of a full read in review).
* **A COPC copy REORDERS its points.** Row *i* of a COPC file is not
  row *i* of its source, so anything pairing them by index is wrong.
  This cost an afternoon here: a tiled-classification check read as
  4,330 mismatches until the orders were matched, at which point it
  was exact. `pyargus copc` now prints the warning.
* **The grid comes from the LAS header** in both commands, so that
  they share one lattice. A header short of its points (a crop, merge
  or append that did not update it) now REFUSES in both, and
  `--rescan` takes the extent from the points instead. It used to be
  silent: the tiled grid simply did not reach the points past the
  header, and they were judged against the surface's edge.

### Tiled-ground adversarial review round (same day)

A 150-agent panel (three lenses, two finders each, three refuters per
finding) raised 48
findings and confirmed 25 -- about ten distinct defects once the
duplicates fold, four of them the same headline found independently
six times. All fixed; each fix is pinned by a test that FAILS against
the old code (checked in a separate checkout: 8 of the new tests fail
there) or, where the old code had no such function, by a mutant the
test kills (six mutants, six killed).

* **The two commands labeled differently.** The plain command lets
  only last returns be ground; the tiled driver labeled every point
  within the threshold of the DEM, so every non-last return near the
  ground diverged -- 9.5% to 19% of a multi-return cloud in review,
  23,886 of about 200,000 in the new test. The equality test and the
  Summerville script were both structurally blind: the test's cloud
  had one return per pulse, and the script built its own comparison
  mask under the tiled rule. Now ONE policy (`candidates`) and ONE
  rule (`labels`) serve both drivers and the desktop Classify stage,
  and `--any-return` -- which the plain command silently ignored -- is
  honoured by both.
* **The acceptance exercised no seam**: at halo 1,260 on a 1,841 ft
  project, 9 of its 12 boxes WERE the whole project and the tiles read
  11.1x its area -- which, not the missing index, was most of the "90 s
  against 9 s". It now refuses unless every box stops short.
* **A stale header silently misclassified** everything past it
  (2.8% of a cloud in review). Refused now, with `--rescan`.
* **The halo box was read inclusive on its upper edge**, folding a
  point exactly on an interior edge -- routine for quantized survey
  coordinates -- into the wrong cell. Latent at the default halo, but
  the margin was zero. Windows are half-open now (`window_points`).
* **The memory claim was false** ("bounded by the raster"), the
  reader's non-COPC path peaked at twice a tile's points (now 4/3),
  the pass count was one short, the COPC message claimed "one read",
  and "11 MB" counted one of the four grids. All corrected above and
  in the job's own messages.
* **Test gaps**: no test ran the DEFAULT halo or tile size (a one-cell
  default survived the suite), and every scene was square, so a
  transposed lattice survived too. The new scene is a 2,400 x 600
  multi-return corridor, run at the default halo.
* `--tile-size` and `--halo` without `--tiled` now refuse by name.

## September 24, 2026: exclude known noise before ground fitting

Both production classification drivers now exclude and preserve classes 7/18.
Summerville's 4,951 noise returns remain noise. The maximum eligible tile
count changes from 11,054,341 to 11,050,836 (3,505 fewer); this is an intentional
candidate-mask change, not relaxed numerical tolerance. Whole and tiled
outputs still agree at all 15,284,332 points; both label 4,517,490 ground.
The full battery passed 72 checks and failed only the old exact tile count.
The pure SMRF diagnostic in summerville_ground still bypasses production
noise filtering; its historical noise_as_ground value is not a production
classifier result and its expectation is unchanged.

Independent repeat: all 13 tiled reference checks passed with the updated exact count; zero whole/tiled classification mismatches.
