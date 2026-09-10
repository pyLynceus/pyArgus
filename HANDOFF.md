# HANDOFF

## 2026-09-10: multi-file projects

`pyargus/project.py` adds saved JSON project references, streamed inventory,
LAS CRS/clock validation, and matching by timestamps plus native TRJ line IDs.
File bindings disambiguate overlapping trajectories. No interpolation across
files or configured internal outages. Shared flights across tiles are combined
for analysis; reused line IDs on distinct trajectories stay separate. Original
LAS point_source_id values and all non-coordinate dimensions survive export.

`project_gui.py` is a separate window from Data > Multi-file project, using the
main job runner/timer/cancellation and preview. Add files/folders, settings,
matching results, save/load project, project QA and alignment are implemented.
Existing single-cloud classification and surface tabs remain single-cloud.
`project_cli.py` registers project-info, project-qa and project-align; no existing
command signatures were changed. Outputs publish to a new folder only after
success, with per-source clouds and before/after QA from exported coordinates.

QA/alignment require complete unique matching when trajectories are supplied;
inventory can diagnose incomplete/ambiguous selections. Without trajectories,
repeated IDs need an explicit shared-flight namespace declaration. The importer
requires common XYZ units and vertical datum; untagged CRS must be declared.
No new sensor conventions have been proven. The array-based analysis has a
configurable 25M-point default limit; inventory is chunked. Latest desktop build:
dist-project-release/pyArgus/pyArgus.exe.

Tests: 246 full-suite tests passed, then 24 project tests passed after the final
guards. Real-data acceptance: two temporary Summerville LAS line samples and two
SBET intervals, 50,000/50,000 returns matched uniquely. No Z: source or pyLynceus
code was modified. Concurrent imagery work was not changed by this task.


## 2026-09-09: native TerraScan trajectory import

Native TSCANTRJ 20010715 reader added in `formats/trj.py`; format dispatch
and explicit clock/geometry settings live in `formats/trajectory.py`.
GUI Data panel accepts `.trj` and `.out`; Inspect trajectory runs through
the existing background job/timer and writes metadata/ranges to the log.
QA supports same stored timestamps or the existing LAS-adjusted-to-GPS-week
join. Alignment and correction both receive the selected clock. Native
positions bypass SBET geographic/geoid transforms. Alignment requires an
explicit confirmation of matching LAS XYZ frame, units and vertical datum,
grid-north clockwise heading, right-wing-down roll and nose-up pitch.
Those conventions are NOT established by the TRJ format or by reading it.
No automatic sign guessing or date/CRS inference was added.

Read-only sample verification: Connector_SR17_SR30/traj/20250708_154503.trj
is line 12, 43,001 records, 200 Hz, 215 seconds, stored times
436024721..436024936. Native parsing verified; no real Connector lidar
adjustment or convention validation performed. One trajectory per job;
folder merge/multi-flight import remains outside this change.
Existing pyLynceus code and Z source files were not modified.
Tests: 193 passed; after moving inspection to the background, the 34
affected GUI/trajectory tests passed. Latest build: dist-trj-final/pyArgus.


Updated 2026-09-08: Phase 5 delivered -- the roadmap's eight phases
are complete (0 through 7). Earlier the same day: Phase 6 delivered — TIN with soft breaklines,
marching-squares contours out to DXF/GeoJSON, and DSM/ESRI-ASCII
export; 1-ft Summerville contours (2,152 lines) generated in 3 s with
every vertex on its level. Phases 0, 2, 3, 4 and 4.5 landed the same
day.

## Where this stands

The repo is a Phase-0/1 scaffold following the roadmap
(https://claude.ai/code/artifact/3da82b18-88cf-4da3-8ae7-04f4aadd4798):
eight phases, QA value first, the custom least-squares strip-adjustment
core (Phase 4) as the reason the suite exists.

What is real and tested, against synthetic data with constructed truth:

* `core.units` -- both feet, exact definitions.
* `core.rotation` -- Rz*Ry*Rx convention, scalar and vectorized, with
  round-trip and gimbal-pole tests.
* `core.georef` -- the direct-georeferencing forward model the Phase-4
  solver will linearize.
* `formats.sbet` -- full SBET reader (17-double records) with
  refuse-on-malformed and wrap-safe attitude interpolation.
* `formats.las` -- laspy wrapper returning plain arrays; strip split on
  point_source_id.
* `qa.density`, `qa.overlap`, `qa.checkpoints` -- density grids,
  strip-dZ maps (median-per-cell, sign = b minus a), TIN checkpoint
  residuals and ASPRS 2014 vertical statistics.
* CLI: `pyargus sbet-info` and `pyargus density` work; nothing else is
  wired on purpose.

## The reference dataset: Summerville

`Z:\Users\BJordan\Summerville_SS` -- the same real TrueView 660
delivery pyLynceus validates its imagery against. **Everything on Z: is
read-only, always**: pyLynceus depends on those files as its transfer
standard, and pyArgus never writes there, copies nothing into this
repo, and the pytest suite never touches Z: at all (run it with the
drive unplugged and it must still pass). Reference checks live in
`reference/summerville.py`, run by hand; measured numbers are in
`reference/RESULTS.md`.

The files that matter, learned 2026-09-08:

* `Summerville_SS.las` -- THE cloud: 15.28M points, four strips in
  point_source_id (a chain: 1-2, 2-3, 3-4 overlap), classified, ground
  = class 2 (1.01M points). Georgia West ftUS, x is easting.
* `pointcloud.laz` (345M pts) looks richer and is useless: psid 0 and
  class 0 throughout. `UAS Flight Mission.PointCloud25D.las` (9 GB) is
  a live LP360 job product -- leave it alone.
* SBET: `Area_/Cycle_250926_134000_122SN030/POS/sbet_NAD83(2011)[2010.0].out`,
  122,924 records, 200 Hz. The second cycle folder has no POS of its
  own.
* Control: `1-4,200-207.csv` + `205.csv`, columns are **P,N,E,Z,D** --
  column 2 is northing; swap on read.

## Phase-0 acceptance: passed

1. `sbet-info` reads the real SBET sensibly (200 Hz, 614 s, altitudes
   consistent with ~100 m AGL).
2. Time bases join: LAS Adjusted Standard GPS + 1e9 - week 2385 *
   604800 puts 100.00% of returns inside the SBET window.
3. **The control comparison reproduces pyLynceus exactly**: median of
   ground returns within 3 ft of each mark, lidar - control, gives
   +0.146 ft / nmad 0.148 over the same six marks pyLynceus recorded
   as +0.146 / 0.150. Two codebases, one number, real data.

## What is NOT yet validated

`core.georef` frame/sign conventions have still touched nothing real:
Summerville's cloud is already georeferenced, so the forward model is
only exercised when Phase 4 re-derives geometry from the SBET. Treat
that boundary as the standing risk. Also note Summerville is already
well aligned (strip-dZ medians <= 0.03 ft): it can referee Phase-4
regressions but cannot demonstrate a fix -- Phase 4 will need a
deliberately mis-adjusted copy or synthetic misalignment injected
through `core.georef`.

## Phase 2: the QA report, delivered

`pyargus qa-report cloud.las --out dir [--control csv --control-order
pnez|penz] [--sbet path]` writes `report.html` (self-contained, maps
embedded) plus `density.png` and `dz_<a>-<b>.png`, each with a `.pgw`
world file so they drop into QGIS/LP360 beside the delivery. Design
decisions that should survive:

* Rasters are stdlib-zlib RGBA PNGs + world files (`qa/raster.py`),
  keeping GDAL out of the dependency tree until Phase 3 needs it.
  `grid_to_image` is the ONE place [ix, iy] grids become north-up
  image rows; nothing else reorients rasters.
* The control number quoted is the local-median measure
  (`qa.checkpoints.local_median_residuals`, the pyLynceus-equivalent
  method); the TIN measure stays for dense surfaces. Column order for
  control CSVs is a required argument, never guessed.
* `formats.sbet.week_alignment` joins LAS Adjusted Standard GPS Time
  to an SBET and refuses seconds-of-week input.
* `report.generate` returns its numbers as a dict; tests and the
  reference run assert on data, not scraped HTML.

The acceptance command and its expected numbers are at the top of
`reference/RESULTS.md`. Rerun after any QA change.

## Phase 3: ground classification + DTM, delivered

**PDAL did not enter.** python-pdal has no Windows wheel (pip build
demands the C++ SDK and a compiler; measured, not assumed), and conda
would fork the environment story for one filter. Instead SMRF (Pingel
et al. 2013 -- the same algorithm as PDAL's filters.smrf) lives in the
math core as ~150 lines of numpy/scipy: `classify.ground.smrf`, 10 s
on Summerville's 12.78M last returns. `surfaces.dtm` grids ground to
a DTM and writes ESRI ASCII (.asc -- plain text, GIS-ready, still no
GDAL). CLI: `classify-ground` (writes a NEW file, never in place,
last returns as candidates) and `dtm`.

Accepted against Summerville's delivered classification
(`python -m reference.summerville_ground`, numbers in
reference/RESULTS.md): recall 0.9992 of delivered ground, extra points
hug the surface (96.2% within 1 ft of the delivered-ground DTM), DTMs
agree to +0.111 ft median / 0.126 nmad. Point precision against the
delivery is 0.22 and that is a labeling convention, not an error --
the delivery keeps a thin ground class; judge by surface metrics.

Findings that cost time, in classify/ground.py's docstring and
RESULTS.md: **cell-level low-outlier cutting destroys under-canopy
ground** (the min-surface is salt-and-pepper in forest; 144k
Summerville cells flagged, DEM in the canopy, false ground 39 ft up).
Three designs were measured before the cause was understood. low_cut
exists for open-terrain clouds with clustered low blunders and
defaults off.

## Phase 4: strip alignment, delivered

The custom core exists and is proven: `align.StripBundle` (points +
per-point map-frame navigation state), `align.patches` (planar-patch
point-to-plane observations with the Jacobian derived per patch), and
`align.solve_alignment` (robust Gauss-Newton for three shared
boresight angles + per-strip offsets, gauge on strip 0, Huber
reweighting). Proven two ways, both by injecting errors through the
georef forward model exactly as reality produces them:

* tests/test_align.py -- small scenes: recovery across seeds, aligned
  strips give ~zero corrections, outliers are downweighted, and
  degenerate geometry (parallel same-heading lines on flat ground) is
  REFUSED via the column-scaled condition gate rather than answered.
* reference/alignment_proof.py -- Summerville scale: boresight to
  ~1 arcsec, offsets to 0.0005 ft, strip-dZ referee collapses 0.098 ->
  0.007 ft. Numbers in reference/RESULTS.md.

Design decisions that should survive: corrections re-run the forward
model on the ORIGINAL body vectors (cached in the bundle), never
re-derive them from corrected coordinates; the observability gate uses
column-SCALED conditioning because raw conditioning hides degeneracy
behind the radians-vs-feet unit disparity; the solver's own rms is
recorded but the referee is qa.overlap.strip_dz plus control.

## Phase 4.5: the map-frame trajectory plumbing, delivered

pyproj entered as the `crs` optional extra. The pieces:

* `formats/crs.py` -- `sbet_to_map`: SBET geographic -> delivery CRS.
  The vertical story is ALWAYS explicit: a vertical CRS composed with
  the horizontal ("EPSG:6360" for NAVD88 ftUS; PROJ fetches the geoid
  grid with allow_network and caches it), or a constant geoid shift in
  meters. A horizontal-only target (Summerville's LAS declares no
  vertical CRS!) REFUSES rather than silently passing ellipsoidal
  meters through as z -- pyproj does exactly that if you let it.
* `align/attach.py` -- `bundles_from_cloud`: week join, attitude
  interpolation (wrap-safe heading), the NED->ours mapping
  (roll, -pitch, pi/2 - heading; re-derived numerically in
  tests/test_attach.py), and three refusal checks that each caught a
  real class of error in development: heading-vs-flight-track (settles
  the heading/wander question empirically and screens axis mix-ups),
  AGL-positive (catches the missing-geoid trap by name), and the
  inside-trajectory fraction. `apply_corrections` applies a solved
  result to a full cloud in chunks.
* CLI: `pyargus align cloud.las --sbet traj.out [--vertical EPSG:6360
  --proj-network | --vertical=-29.077] [--write fixed.las]` -- solves
  on the ground class, prints diagnostics + corrections + the dZ
  referee, optionally writes a corrected NEW cloud.

Acceptance (reference/RESULTS.md): real strips + real SBET attach with
heading agreeing with track to 0.53 deg and AGL 331.9 ft; baseline
solve leaves the aligned delivery alone; injected boresight recovered
through the real geometry to ~4 arcsec / 0.001 ft.

The remaining honest caveat: the boresight ANGLES are self-consistent
within this suite's convention. Corrections applied by this suite are
valid regardless; quoting the angles to a POSPac/vendor calibration
report as-is is not yet validated -- that needs a dataset with a known
vendor-stated miscalibration.

## Phase 6: surfaces and deliverables, delivered

The chain now runs classified LAZ -> DTM/DSM -> contours entirely
in-suite, still with no heavy dependency:

* `surfaces/tin.py` -- Delaunay TIN with SOFT breaklines (densified
  3D vertices join the point set; documented as not a constrained
  Delaunay). Breaklines arrive as 3D LineString GeoJSON; 2D lines are
  refused -- a breakline's z is surveyed truth, never draped.
* `surfaces/contours.py` -- marching squares over cell-centered
  grids, saddle resolution by the cell-average rule, chains joined,
  Chaikin smoothing opt-in (it moves vertices off the measured
  surface and the CLI says so).
* `formats/dxf.py` (R12 3D POLYLINE, CONTOUR_INDEX/_INTERMEDIATE
  layers, ezdxf-strict clean) and `formats/geojson.py`;
  `surfaces/dtm.py` grew `dsm_grid`.
* CLI: `pyargus contours` (DXF/GeoJSON by extension, --breaklines
  switches to the TIN, --max-fill governs voids on BOTH paths) and
  `pyargus dtm --dsm`.

Acceptance and the review round are in reference/RESULTS.md: 40
levels / 181,335 ft of Summerville linework with vertex-vs-DTM error
0.000 ft; a 33-agent adversarial panel confirmed 5 findings (the DSM
referee's unaligned grid crop, TIN contours invented across voids,
and three mutation-unpinned branches), all fixed and test-pinned.

## Phase 7: the desktop application, delivered

`pyargus gui` (and the branded exe) is pyLynceus's GUI idiom
transplanted: guarded tkinter import, stage classes with the
prepare()/work(runner) seam (prepare reads every widget on the UI
thread; work touches none), StageRunner with a queue as the only
bridge back, completion via an explicit flag (the Tcl_Obj lesson,
kept), and launcher trios BOTH ways -- the pyArgus window has a
pyLynceus button and pyLynceus grew a pyArgus button (its 327 tests
stay green; the bridge mirrors the Plumbline one exactly, marker
pyargus/gui.py, module `-m pyargus gui`, handoff env PYARGUS_DATA_DIR
seeds the file pickers). Five stages call the same library functions
as the CLI: Strip QA (density preview on the canvas), Classify (its
product auto-fills empty downstream fields), DTM/DSM, Contours,
Align. Packaging mirrors pyLynceus: packaging/pyArgus.spec (onedir;
only the dist copy runs -- delete build/ after), windows/pyArgus.iss
(fresh GUID, per-user), make_logo.py DRAWS the mark (peacock-eye on
pine, regenerates from code). PyInstaller and Pillow live in the venv
ad hoc, not in pyproject.

A 39-agent adversarial panel confirmed 5 findings, all fixed and
test-pinned: the preview gate never drew on real-size clouds (draw is
now keyed on report identity, never on log traffic); four stages
ignored Stop and wrote files anyway (one shared cancelled_before gate
now guards every write and the products handoff); Align solved with
min_points=5 vs the CLI's 6 (constants now pinned against
cli.build_parser); the CLI's exists-refusal was dropped (restored for
classify and align outputs); the installer lacked
ignoreversion/createallsubdirs (mixed-version upgrades).

## Phase 5: above-ground classification, delivered

The roadmap's last phase. `classify/features.py` (8 handcrafted
features: HAG against the ground DTM, two-pass cell-covariance
eigenshape -- one-pass cancelled catastrophically at state-plane
magnitudes, panel-caught -- HAG span, return structure; noise excluded
via ignore_mask because it poisons neighbours' cells) and
`classify/above.py` (RandomForest behind the [ml] extra, joblib
persistence with schema/version/feature guards and a pickle warning).
CLI: `train-above` (a delivered classification is the answer key) and
`classify-above` (ground-classified cloud in, full classes out, noise
untouched). Acceptance in reference/RESULTS.md: spatial holdout
agreement 0.9972 / kappa 0.988, deployment-conditions delta behind
SMRF ground only -0.0026, building precision 0.558 quoted with its
0.06%-of-points context. A model is one site's forest: the provenance
note travels in the file, the numbers live in RESULTS.md.

## Post-roadmap round one: harness, control-solve, control-by-strip

Three improvements, each adversarially reviewed (sixth panel, 10
confirmed findings, all fixed):

* **The regression gate**: `python -m reference.run_all` reruns the
  whole Summerville acceptance battery and diffs 41 recorded metrics.
  Each reference script's main() RETURNS its results dict. Panel
  lesson baked in: a script returning None is a FAILURE, and a partial
  gate refuses to pass -- a harness must be able to fail.
* **Control observations in the solver**: `solve_alignment(control=
  (M,3) marks)` lifts the strip-0 gauge, gives every strip an offset
  unknown, and anchors the ABSOLUTE datum (strips without marks
  inherit it through patches; control rows carry control_weight).
  Recovers strip 0's own error -- the thing strip-to-strip adjustment
  can never see. On curved terrain keep control_radius TIGHT (plane
  sagitta biases the datum; measured in the test).
* **control-by-strip**: the SH 151 decomposition as a command
  (`pyargus control-by-strip strips/*.las --control csv`) and a
  qa-report section. Streaming gather (chunk-bbox culled), per-strip
  bias vs POSITION-LOCKED per-mark readings, grade-corrected plane
  dz. Panel lessons: a file holding several psids ALWAYS splits
  (file-count labeling read pure misalignment as position-locked);
  big spread alone is the strip-dependent signature (symmetric
  disagreement has zero mean); the robust plane refits on survivors
  whenever a plane is still determined.

## Time-dependent (drift) corrections

`align/drift.py` + drift mode in `solve_alignment(drift_spacing=,
drift_stiffness=)`: per-strip piecewise-linear VERTICAL corrections
in time (TerraMatch's "fluctuating" idea) replacing the constant
offsets; per-point times ride StripBundle.times (attach supplies sow;
synthetic strips derive them from the along-track sweep).
Observability is judged on the NESTED CONSTANT system (equal nodes =
a constant) because stiffness regularizes the drift system itself and
no safe gate exists there -- measured, in solve.py's docstring. CLI:
`pyargus align --drift-spacing S [--drift-stiffness K]`; --write
interpolates each point's correction at its own time (drift_by_sid in
attach.apply_corrections; the per-strip means are deliberately
ignored to avoid double-correction).

Know these three measured truths before using it (all in
reference/RESULTS.md, all pinned in run_all):

* **A wandering block is not calibration data.** Calibrate boresight
  on clean lines, hold it, then solve drift with --no-boresight. The
  harness measures all three ways: constants-on-wander errs pitch
  1.05e-3 rad, together-mode 1.24e-3 -- both worse than the injected
  pitch; calibrate-then-drift recovers the wander to 0.033 ft.
* **Without control, drift is relative all the way down**: patches
  see only curve DIFFERENCES, and the stiffness prior splits a
  one-strip wander half-and-half between overlapping strips. Put
  marks in the solve when it matters which strip actually moved.
* **The stiffness prior is a true curve penalty** (seventh panel's
  headline: rhs used to be zero, so the prior washed out per
  iteration -- iterated Tikhonov; now the rhs carries the penalty
  residual, results are independent of max_iterations, and solves
  actually converge). Weight is spacing-invariant (~1/sqrt(step));
  spacing/stiffness <= 0 and node explosions REFUSE by name.

Seventh adversarial panel (92 agents): the Tikhonov defect, the
refusal holes, the guard that algebraically could not fire, and six
test gaps -- all fixed, everything re-measured; details in
RESULTS.md's drift review round.

## RGB colorization: the pyLynceus EO bridge

`pyargus colorize cloud.las --eo eo_Photos.csv --images Flight_dir
--out rgb.las` paints a cloud from oriented aerial imagery.
`formats/eo.py` reads the LP360-style EO CSV (which pyLynceus's
adjusted_eo.csv also is), `imagery/camera.py` is a calibrated frame
camera, `imagery/colorize.py` assigns, checks occlusion and samples.
Needs the `[imagery]` extra (Pillow). Measured on Summerville:
70.9% of 15.28M points colored from 1,019 of 1,083 photos in 235 s.

Four things to know before touching it:

* **The lens model lives in the STORED IMAGE's grid**, in Agisoft's
  own equations and units, because that is what the `.cal` sidecar
  beside every frame is. Do not "convert" it into a millimetre photo
  frame: the first version did, and since the radial terms are
  rotation-invariant while CX/CY and P1/P2 are not, it carried a
  ~27 px systematic at the shipped `quarter_turns=3` that a suite
  testing distortion only at turns=0 could not see. The equivalence
  test now covers all four turns.
* **Rotation comes from Direction/Up**, never an angle column.
* **Occlusion is refereed by the cloud**, and its limits are real and
  pinned: the depth grid holds only the points a photo was assigned,
  so paint-through survives where the occluder belongs to another
  photo; a one-cell halo at each depth edge is falsely occluded. Both
  have tests asserting the CURRENT behavior, so improving them will
  fail those tests -- update the tests and RESULTS.md together.
* **Coverage is the datum gate**: overlap and AGL catch a mismatch
  that separates EO from cloud, not one that scales it (metres over
  survey feet keeps both happy), so `--min-coverage` refuses below 5%
  and under half prints a caution.

The eighth adversarial panel (four lenses, 38 findings) drove most of
that; it ran out of quota mid-verify, so one finding carries a full
three-refuter quorum and the rest were triaged by hand against the
code. Details and the honest-gaps list are in RESULTS.md.

## Next step, with reasoning

**The roadmap is complete.** What remains open, by value: (1) THE
REAL PROJECT (SH 151, set aside pending the vendor's LCP2 list): the
lidar block is internally rigid and the misses are position-locked;
when the vendor responds, re-occupy the worst marks and decide
between control-net vs lidar-datum error -- reference/sh151_* holds
the case. (2) A better occlusion test for colorize -- a per-photo
depth grid built from every candidate point rather than only the
assigned ones, which is what would end paint-through. (3)
COPC/streaming reads for clouds beyond memory. (4) Archive any
vendor-stated miscalibrated flight as the final alignment
acceptance.

## Findings so far

* OneDrive refuses uv's hardlinks (os error 396). Rebuild the
  environment with `UV_LINK_MODE=copy uv pip install -e ".[dev]"` or
  the install dies mid-wheel.
* The Summerville control CSVs are **northing-first** (P,N,E,Z,D).
  Read them as E-first and every mark lands ~1,900 miles from the
  cloud. pyLynceus's control reader refuses to guess column order for
  exactly this reason.
* TIN-interpolated checkpoint residuals and local-median residuals
  disagree on the same data (-0.011 vs +0.146 ft mean/median) because
  the TIN admits marks with no nearby ground returns and spans kerbs.
  Quote the local measure; `qa.checkpoints.vertical_residuals` is for
  surfaces dense at the mark, and a local-median mode should join it
  in Phase 2.
* laspy's `header.parse_crs()` needs pyproj, which is not a
  dependency yet. Read extents and judge CRS by magnitude until it is.

TRJ release verification: all 46 reference checks passed (0 failures); dist-trj-final packaged self-test exited 0. Unrelated concurrent imagery/EO files were left alone.

Importer isolation check: all 248 unit tests passed in C:/Users/bjordan/Desktop/ClaudeCodeFAA/project-validation-20260910 (committed baseline plus importer changes). The active working tree's reference run passed all 46 non-colorization checks and 3 colorization checks; 3 recorded colorization expectations differed with the separate uncommitted imagery work. Those files and expectations were left untouched.

Final importer guard: SBET vertical CRS units must match the LAS XYZ unit; a mismatch refuses before attachment. Alignment manifests now record solver cell/minimum-points/boresight settings. An unavailable optional PNG preview does not turn completed output into a failed job. All 24 project tests passed after these refinements.

Final release: isolated reference battery passed all 52 checks (0 failures), in project-validation-20260910/isolated-project-reference.log. Final dist-project-release packaged self-test exited 0. This isolates the earlier active-worktree colorization expectation differences from the importer. All 24 current project tests pass, including the SBET vertical-unit refusal; 248 full-suite tests passed before that final added case.


## 2026-09-10: true 3D viewer

`viewer3d.py` adds a Tk/Pillow/numpy orthographic point renderer, streamed
150k-point sampling, orbit/pan/zoom, camera presets, file visibility, three
color modes and native TRJ/SBET overlays. Both Data and Project windows launch
it. No core, formats, alignment or imagery code was changed. Rendering subtracts
a double-precision local origin first and resolves depth per pixel. Trajectories
are explicitly drawn on top; no trajectory time/attitude validation is implied.
Fixed sample, no progressive detail or cross-sections yet. Uses existing deps.

Summerville read-only check: 149,847 displayed / 15,284,332 source points,
7.17s load, 0.11s rendered frame on this machine. Render inspected visually.
Full suite passed 252 tests before the additional background-completion test.
Desktop build: dist-3d/pyArgus/pyArgus.exe. Concurrent imagery changes left alone.
`nFinal 3D checks: all 4 viewer tests passed, including background load to Finished; packaged dist-3d --self-test exited 0 with actual 3D rendering.
