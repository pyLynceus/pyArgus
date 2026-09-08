# HANDOFF

Updated 2026-09-08: Phase 6 delivered — TIN with soft breaklines,
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

## Next step, with reasoning

**Phase 5 (above-ground classification)** is the one roadmap phase
left: random forest on geometric features (height above ground,
eigenvalue descriptors, return ratios), scikit-learn enters, and the
delivered classes 3/4/5/6 are the answer key -- same pattern that
worked for ground. Also open from the original roadmap: RGB
colorization from pyLynceus EO (the TerraPhoto bridge), and the
standing Phase-4 wishes (time-dependent trajectory corrections; a
real vendor-stated miscalibration dataset as the final alignment
acceptance -- archive one if it ever comes through the shop).

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
