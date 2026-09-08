# HANDOFF

Updated 2026-09-08: Phase 0 complete — Summerville is the reference
dataset and the acceptance checks passed.

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

## Next step, with reasoning

**Phase 2 proper: make the QA a product.** The machinery just proved
itself; what is missing is the deliverable -- a strip-QA report (dZ
rasters written to GeoTIFF or rendered, density map, the control table)
produced by one CLI command against a project folder. Build it against
Summerville, compare its numbers to `reference/RESULTS.md` every time.
PDAL still arrives with Phase 3, not now.

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
