# Current handoff — September 25, 2026 (Claude)

Two checkouts of one repository, same history, different branches:

* `C:/Users/bjordan/OneDrive - Platinum Geomatics/Desktop/pyArgus` —
  branch `main`, Claude's working checkout (own `.venv`, has pip).
* `C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex` — a
  git worktree on `codex/isolated-improvements`, Codex's checkout.

On 2026-09-25 `codex/isolated-improvements` at e4b7b0e (noise
screening and batch classify, section cache, section stepping, the
profiling baseline; e4b7b0e itself is docs only, after 8e36ca5) was
merged into `main` through the branch `merge/codex-reconcile`. `main`
now holds both lines of work. `main` has not been pushed:
`origin/main` is still 82983da. The Codex branch HAS been pushed, to
`origin/codex/isolated-improvements` at e4b7b0e, so the Codex release
entries below that say "not pushed" are superseded on that point. The
released executable (below, 2026-09-25-8e36ca5) was built from the
Codex branch BEFORE the merge, so it has none of `noise-cut`, `merge`,
`dtm --add-points` or the stereo modules; the next build from `main`
is the first to carry both.

## 2026-09-25: two noise routes, reconciled

Both lines built "classes 7/18 are a statement SMRF may not overturn"
independently, and both land on the same two codes:

* `pyargus noise-cut` (Claude) flags once, in a recorded step that
  writes a new cloud and refuses a window that would catch the site.
* `noise_min`/`noise_max` on the classifiers (Codex; `classify-ground
  --noise-min/--noise-max`, the desktop Classify stage, batch runs)
  screens on the fly during classification.

`classify/job.py`'s `noise_codes` is now the ONE place that decides
which points are noise; `candidates`, `labels` and every count read it.
Git merged most of this silently, and two of the silent merges were
wrong: the tiled driver's label pass kept one noise-count line from
each side and counted every already-flagged point twice, and the
whole-cloud driver's result dict referenced a variable one side had
removed. Both drivers now report the two routes separately
(`noise_already`, `noise_screened`, and `noise` for their total) and
log one line per route.

Screening then got `noise-cut`'s guard (Bryon's call, 2026-09-25): a
window outside the header's z range refuses before a point is read,
and one that would flag more than `noise_max_fraction` of the cloud
(default 0.001, `--noise-max-fraction`, **Noise max fraction** in the
desktop stage and batch) refuses before anything is classified. The
refusal text and the budget, `int(fraction x points)`, are shared with
`noise-cut` (`classify.noise.refuse_outside_header` and `too_many`).
The tiled driver pays one extra streaming pass for the count, taken
first so it can refuse on the running count -- after the plan's own
refusals, which read nothing. While screening, both drivers refuse a
cloud whose record count differs from its header's (the budget is a
share of that count; a truncated file had split the drivers). The
workspace does not call earlier classifications outdated over the new
field: without a noise window it is ignored, and with one a job
recorded before the field existed (which ran with no guard at all) is
compared at the default by choice. A workspace saved before the field
existed restores it to the default. A review panel found the last four
behaviours missing from the first version; all are pinned.

## 2026-09-24: fill decision, and stereo measurement

Bryon set a client job's DTM at `--max-fill 10` (first `2`, then
reverted): no surface here is accepted without stereo QC, and field
shots routinely arrive for thick areas, so the gaps are filled first
and the operator corrects them. What matters then is that the
interpolated cells are identifiable: that job's review got a companion
grid marking them, which `pyargus dtm` does not write yet. The
reasoning is in the private job notes.

Stereo review was built toward an operator who records points at the
0.1 ft class (Bryon has anaglyph glasses and NVIDIA 3D Vision):

* `imagery/camera.py` -- `ray`/`undistort`, the pixel-to-ray inverse
  in the same frame as `project`; `read_cal` reads the INI calibration.
* `imagery/intersect.py` -- N-ray least squares with its own geometry
  refusals (`WeakGeometry`).
* `imagery/stereo.py` -- normalized (epipolar) pairs, per-half
  convergence, `choose_partner`, `measure`, `anaglyph`.
* `imagery/matching.py` -- 1-D subpixel NCC with a local affine term.
  It REFUSES every surveyed mark it was tried on along a real highway
  corridor: highway pavement is periodic, and before the
  ambiguity test was tightened it picked confident wrong periods worth
  1-6 ft. The operator is the product; the matcher refines and
  declines.
* `measurements.py` -- the measurement record (CSV the control reader
  takes, plus a JSON sidecar with the ray geometry).
* `surfaces/supplement.py`, `dtm --add-points` -- field shots and
  stereo points each OWN their cell rather than joining its returns.

Not yet done: an adversarial review of the stereo code; the viewer with
a floating mark. That job's own open items are in the private job
notes.

## 2026-09-23: noise classes, and `pyargus noise-cut`

A review of a real two-line client delivery found gross outliers
classified straight from the vendor export: SMRF's minimum surface
takes each one as its cell's ground and the slope term pulls its
neighbours up with it. Measured there (the script and its numbers are
kept with that job's private records): over a hundred outliers, nearly
all of them below the ground, more than half of them labeled ground,
and at more than a dozen pits the classified cloud put ground tens of
feet above the vendor's own class-2 surface within one cell. Two
changes -- one in `classify/job.py`'s labeling policy, one a new
command:

* `candidates()` never admits a point flagged 7 or 18, and `labels()`
  carries those flags through instead of overwriting them. Both the
  whole-cloud and tiled drivers read `classification` now. On a cloud
  with no such flags nothing changes; on Summerville, whose delivery
  carries class 7, two recorded numbers move (below, and RESULTS.md).
* `pyargus noise-cut in.las --out flagged.las --z-min A --z-max B`
  (`classify/noise.py`): class 7 below A, 18 above B, every other point
  field carried through `stream_update` (a COPC index is the exception:
  no chunked copy can carry one). It refuses before any cloud is
  written -- and in cost order: a window outside the header's own z
  range refuses before a point is read, and the `--max-fraction`
  refusal (default 0.1%) fires on the running count rather than after
  accumulating the whole cloud. It writes `<out>.noise.json` listing
  every flagged point, and a schema-1 job record that also records a
  refusal as a failed attempt. A window the operator reads off the
  site, not a detector; how far outside is the job's property, not a
  law. In-band strays need a neighbourhood test (not built).

Tests: `tests/test_noise.py` (10) -- the flagged-pit scene classifies
identically with and without the pit, the UNflagged pit demonstrably
pulls roof into ground (the defect, kept as a test so the guard is
never decoration), whole and tiled agree with flags present and under
`--any-return`, and the command's field-by-field pass-through (run
whole and at chunk sizes 1,000 and 7, because a real delivery runs to
a couple of dozen chunks and pass 2 addresses points by absolute
index), sidecar, records and every refusal. Six of the seven original
tests fail on 197482e; the seventh is the defect demonstration and
passes on both trees on purpose.

On real data (the gate, +5 checks, now 78): Summerville's delivery
carries 4,951 class-7 points. Both commands used to label **1,556** of
them ground; now **0**, all 4,951 keep their own class, equality
between the drivers is still exact, and `max_tile_points` moved
11,054,341 -> 11,050,836 (the class-7 last returns are no longer read
into the largest tile). Recorded in RESULTS.md.

Also fixed here, found by the same review: `stream_update` wrote a
`.laz` output UNCOMPRESSED -- laspy infers compression from the
extension and the temp file's was `.partial` -- so every `.laz` this
suite has written is plain LAS bytes under a `.laz` name, several times
the size it should be. One line, pinned by a test that reads the
header's compression flag back. And `classify-above`/`train-above`
treated only class 7 as noise, so a class-18 point from `noise-cut`
would have entered the forest's features and come back as vegetation;
both now use `NOISE_CLASSES` and restore each point's own code.

The client delivery above ran through `noise-cut` the same day, with
a window Bryon chose. It flagged within a handful of points of what
the vendor's own cleaning had dropped. It was reclassified with the
earlier run's exact parameters, so it is a one-variable experiment.
**None of the gross outliers is labeled ground now, and no pit pulls
ground more than 10 ft above the vendor's surface.** Every
source point, extra dimension, scale and the CRS survive; only
`classification` differs from the source. The job's numbers, and the
control questions it raised, are in the private job notes.

## 2026-09-23: `pyargus merge`, and a surface against the vendor's

`dtm`, `contours` and `qa-report` each take ONE cloud and a delivery
arrives one file per flight line, so a site surface begins with a join
-- and the join is where a delivery is quietly ruined. `merge` decides
from the headers before a byte is written: differing point format, LAS
version, scale, offset, extra dimensions or CRS each refuse by name,
and a point_source_id collision refuses too, because strip QA reads
that field and two files both numbering their points 1 become one
strip the moment they are joined, silently comparing a strip with
itself. `--psid-from-file` renumbers by file order; `--reframe`
restates every point in one frame and measures how far the worst
coordinate moved rather than assuming it did not move.

The same two-line client delivery proved the offset refusal: the vendor
gives each flight line its own coordinate offset (more than two
thousand feet apart there), so a raw record copy would have moved line
2 bodily across the site. `--reframe` joined them with the largest
coordinate moving **0.000000 ft** (both files share a scale, and the
offsets differ by exact multiples of it). `qa-report` on the merged
cloud reproduces the separate runs' strip dZ exactly, so strip
identity survived the join.

The merged cloud then went through `dtm` and `contours` (the DXF opens
in ezdxf as R12, two layers, every level exactly on a whole foot), and
the DTM was compared with the vendor's own finer DEM, averaged over our
cells so both sides answer the same question. The products and the
comparison's numbers are in the private job notes; what generalises is
that a vendor DEM built from the same returns we classified checks the
**classification, not the datum**.

A caution worth carrying: the first pass at that comparison ran as a
throwaway script, and its median differed by about 0.02 ft from the
rewritten, test-pinned version -- the two runs had registered the
grids half a coarse cell apart, which is worth about 0.015 ft. The
grid handling now lives in `reference/grid_compare.py`, pinned by
`tests/test_dtm_check_grids.py` against a planted plane that a y-flip
or a half-cell shift cannot survive; the job script that runs it is
kept privately. The script's numbers are the reproducible ones; quote
the median to two decimals and re-run rather than trusting a
remembered figure.

## 2026-09-23: what the sections showed

Cutting the same job's classified cloud into slabs and drawing them
against the vendor's class 2 (the generic geometry is
`reference/mark_profile.py`; the job script is kept privately)
answered one open question and overturned one of my own conclusions.

**A control mark had been mis-recorded, and its published elevation
corresponds to nothing in the cloud.** I got this wrong first and it
is worth keeping the mistake visible. Counting points within half a
foot of the published elevation found a few dozen and I called it a
structure top. A vertical face returns points at EVERY elevation it
spans, so any band across a sound wall holds a similar handful; the
histogram around that mark held about the same count in every one-foot
band up the height of the wall, and the only flat things there were
the ground and the wall top.

Asking instead whether the band stands out from the bands beside it:
the other marks stood out several-fold or more, and the mis-recorded
one held fewer points at its published elevation than immediately
above or below. `tests/test_mark_profiles.py` pins the distinction
against a synthetic wall; four of its six tests fail against the rule
I first wrote. A count at one elevation means nothing without its
neighbourhood.

**The spread in a DTM comparison against the vendor's surface was
fill, not the edge.** Splitting the cells by whether each holds a
class-2 point of its own, rather than by distance from the swath
boundary, put the great majority of the large disagreements in cells
`--max-fill` had interpolated; where pyArgus measured ground the two
surfaces agreed several times better. An earlier reading of that
comparison as edge-dominated was a proxy: the swath edge is where holes
concentrate, and the interior holes are under canopy. The
coverage-against-fidelity trade of `--max-fill` was measured rather
than argued. The two surfaces also differed by a small systematic
vertical offset, a fraction of a foot. The median held at every fill
setting, which says the offset has nothing to do with filling, and the
offset was present in the MEASURED cells, which makes it a real
disagreement about which returns are ground. Which surface to deliver
is Bryon's call: a design surface wants fidelity, a display surface
wants coverage.

**And the two classifications agreed about WHERE ground is**, in the
great majority of cells, with pyArgus slightly MORE inclusive than the
vendor, not less; the worry that pyArgus was missing ground under
canopy is not a pattern. Underneath it all is a labelling convention:
our class 2 held several times as many points as the vendor's, out of
the same returns. That is the reason this project judges
classification by surface metrics, not point-level precision. Whether
the convention also explains the offset is plausible and untested.

The numbers behind these findings are in the private job notes.

## 2026-09-24: the control question is answered

The same job's control question was answered; the answer and its numbers
are in the private job notes. What generalises: with only a handful of
independent marks a vertical check is a bias estimate, not a compliant
accuracy assessment (ASPRS asks for twenty checkpoints and more per
land-cover class), and a constant vertical shift is not an alignment.

## Latest executable — section stepping, September 25, 2026

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-25-8e36ca5/pyArgus/pyArgus.exe

Source commit 8e36ca5. Packaged self-test passed (exit 0), with isolated
workspace autosave. Keep the whole pyArgus folder including _internal.
Adjacent build-info.json records executable hash and validation.

QA / cross-sections now has Step distance, Step left and Step right. Each
click translates the corridor perpendicular to A->B and extracts automatically
through the existing cache/full-scan path. Length, width and source selection
are preserved. Busy clicks do not queue scans. Distance uses map units and
is session-local. See docs/SECTION_STEPPING.md for direction and cancellation.

Validation: focused navigation/cache/unified-workspace run 36 passed, one
Tk display initialization skip; that skipped cache GUI test passed in an
isolated rerun. Earlier review/navigation/cache run: 22 passed, same one skip.
Packaged smoke includes stepping geometry. Full suite and reference numerical
battery were not rerun for this navigation-only change. Source datasets,
classification and alignment algorithms are unchanged. Saved review presets
remain pending. Work committed locally, not pushed. Older release entries below
are historical.

## Latest executable — GUI section cache, September 24, 2026

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-24-f17842e/pyArgus/pyArgus.exe

Source commit f17842e. Packaged self-test passed (exit 0), including cache
build/query/clear. Keep the entire pyArgus folder with _internal. Adjacent
build-info.json records source SHA, executable SHA-256 and validation.
Full suite: 450 passed, no skips. Final GUI/store/workspace: 37 passed.
Six real managed-cache/full-scan comparisons were exact. Packaging used an
isolated workspace autosave location.

In QA / cross-sections, choose Section source and Build section cache. Keep
Use cache when available checked; extraction reports Spatial cache or Full
scan with a reason. Stop cancels. Clear all section caches reclaims only
recognized derived caches under the owned local cache folder. See
docs/SECTION_CACHE_GUI.md and docs/GUI_STATUS.md.

No source clouds, classification outputs or project input versions changed.
Viewer caching, presets, section stepping and in-app build identity remain
pending. Changes are committed locally, not pushed. Older executable paths
and pending-packaging notes below are historical.

## GUI section-cache integration — September 24, 2026

Implemented optional section caching in QA / cross-sections. Build section
cache snapshots the selected Section source(s), runs in a worker with point
progress/elapsed time and Stop, and reuses completed files. Use cache when
available defaults on but never builds automatically. Clear all section
caches removes only recognized directories under the owned local cache root.
See docs/SECTION_CACHE_GUI.md for operator steps and limitations.

The production engine is pyargus/section_cache.py; the reference module now
re-exports it. The store checks disk space, protects operations with an OS
lock, validates manifest checksums and file metadata, and falls back to the
original extractor for missing/invalid/busy caches or >35% candidate coverage.
Original GUI source-change checks still apply. The source selector is locked
while a review operation is running. Source-version changes need explicit
cache rebuilding; old versions remain until manual cleanup.

Validation: full suite 450 passed, no skips; final GUI/store/workspace tests
37 passed after message/source-selector polish. Managed-cache tests on two
real client lidar files matched the full scan exactly for six query shapes,
including a multi-million-return sampled corridor and the broad-query scan
fallback.
Evidence: C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-benchmarks/2026-09-24-section-cache-gui/report.json.
Source datasets and workspaces were not modified. Classification, alignment
and terrain algorithms were unchanged. Packaged self-test now exercises cache
build/query/clear; executable packaging is the remaining release step.

## Spatial section-cache experiment — September 24, 2026

Experiment complete; see docs/SECTION_CACHE_EXPERIMENT.md. This is not yet a
GUI feature. The local sidecar preserves original point indices and replays
reference sampling order. Production source files and workspace inputs remain
unchanged. No Rust/C++ or production algorithm change was made.

On a real two-file client delivery of tens of millions of points the cache
built in under half a minute and under 1 GiB. Short sections measured
4.9–7.6x faster, long narrow section 3.2x, broad section ~1x.
Six geometries repeated twice agreed exactly in counts and every returned
array, including sampled order. 11 focused tests passed, including oblique
large-coordinate, invalidation and interrupted-build cases. Rough build-cost
break-even is 16 queries for the tested mix, not a universal threshold.

Evidence: C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-benchmarks/2026-09-24-section-cache-oriented.
The initial bounding-box-only experiment is retained separately and documents
why corridor-oriented cell selection was necessary. Metadata-only source and
cache invalidation cannot detect deliberately preserved size/mtime changes.

Next: optional GUI integration with visible build/cancel/progress, disk-space
and cleanup policy, source-version invalidation and a full-scan fallback.
The current executable is still c747213; this prototype is reference-only.

## Performance baseline and GUI status — September 24, 2026

The first language/architecture step is complete: repeatable profiling, not
migration. See docs/PERFORMANCE_BASELINE_2026-09-24.md and
reference/profile_workflow.py. Two real client lidar sources (a vendor's
strip-adjusted export) were read-only; verified copies and benchmark-only
classified/QA outputs are kept outside the project in a local benchmark folder.
No benchmark result was promoted or accepted in a GUI workspace.

Two source/local repeats matched result counts. Warm section median about 2 s;
refinement a few seconds; disk-backed QA about two minutes. Actual full-canvas
redraws of the viewer's ~150k-point sample took under 0.1 s per frame.
Initial 1x1 redraw samples are excluded; corrected measurements and
harness hashes are preserved. Final synthetic harness smoke
passed all 14 operations with valid canvas dimensions and unchanged source.

Largest measured numerical costs are already compiled SciPy morphology,
NumPy sorting and SQLite reduction. One source scan was an outlier, over ten
seconds elapsed for under a second of CPU, so cache/access conditions matter.
These are instrumented, warmed-cache observations, not cold-network
benchmarks or accuracy checks.
Next experiment: optional cached/spatial access with exact section-count,
point-index/coordinate and invalidation checks plus measured build/query costs.
No Rust/C++ migration or production algorithm change is justified yet.

GUI rewrite remains partial: docs/GUI_STATUS.md is the delivered/pending
checklist. Presets, section stepping, compact layout, next-action guidance
and in-app build identity remain pending. Current released exe is still
2026-09-24-c747213 below; this profiling increment needs no executable rebuild.

## Latest executable — noise and batch classification, September 24

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-24-c747213/pyArgus/pyArgus.exe

GUI delivered/pending status: docs/GUI_STATUS.md.

Source commit c747213. Packaged self-test passed (exit 0). Keep the whole
pyArgus folder, including _internal. Adjacent build-info.json records the
source commit, executable SHA-256 and precise test/reference results.

Use Classify > Entire project, choose Batch output parent, and Run Classify.
Existing noise classes 7/18 are preserved and excluded from ground fitting.
Optional min/max Z screening uses LAS elevation units; leave blank unless
project limits are established. Batch outputs require individual review.
See docs/NOISE_AND_BATCH.md. No client-job reclassification was performed.
The original checkout and pyLynceus were not modified. Commits remain local.
All executable and pending-packaging notes below are historical.

## Noise and sequential batch classification — September 24, 2026

Implemented in the isolated Codex checkout: preserve/exclude classes 7/18 in
whole and tiled ground classification; optional explicit min/max elevation
screens; GUI Classify / Entire project with a batch output parent, sequential
flights, unique filenames and per-flight records/review. Stop/failure halts
the queue and retains completed results. Original clouds remain unchanged.
See docs/NOISE_AND_BATCH.md for operator steps and limitations. Spatial noise
detection and automatic batch resume are not implemented. No client-job
cloud was reclassified and its provisional outputs remain unaccepted.

Validation: full suite 432 passed, one Tk display skip; all 11 record tests
passed on retry. Final noise/batch/workspace tests passed 29, including a later
flight failure retaining the earlier successful output. Full reference run:
72/73, with only the old tile candidate count failing after intentional noise
exclusion. Expected count updated with explanation in reference/RESULTS.md;
a separate tiled reference repeat passed all 13 checks, including the updated exact count and equality.
New executable packaging is the remaining release step; older build below
remains the released executable until the new release entry is added.

## Latest executable — active cloud versions, September 23

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-23-87cb859/pyArgus/pyArgus.exe

Source commit 87cb859; packaged self-test passed. Keep _internal beside the exe.
Adjacent build-info.json contains source identity, executable hash and test
counts: full suite 426, final review/workspace/editor 42, final workspace 23.
This is the current build; older executable entries below are historical.
Automatic source/result promotion is implemented for successful Classify runs.
Noise handling, batch classification and in-app build identity remain pending.
No new client-job classification or accuracy approval was performed.
Changes remain local, not pushed.

## Current executable — per-flight tracker, September 23

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-23-fa553e6/pyArgus/pyArgus.exe

Keep _internal beside the exe. Source commit fa553e6; build-info.json includes
SHA-256 and validation. Packaged self-test passed. Full run: 421 passed;
subsequent tracker/review/editor checks: 37 passed; final tracker checks: 17
passed. The 73/73 reference gate predates these workflow-only changes.
Source/result promotion and noise handling remain pending; no new
client-job cloud was generated. Commits are local, not pushed.

## Previous executable — September 23, 2026

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-23-8f45724/pyArgus/pyArgus.exe

Keep the entire pyArgus folder, including _internal. Source commit: 8f45724.
The adjacent build-info.json records the executable SHA-256 and validation.
Packaged self-test exited 0. Reference gate: 73/73; full suite before final
review changes: 418 passed; final record/review tests: 18 passed; final
section/workspace/editor tests: 34 passed. This supersedes the September 17
executable. No client-job reclassification or accuracy acceptance is claimed.
GitHub publication and in-application build identity remain pending.

# Current handoff — September 22, 2026

Read CODEX_WORKTREE.md and docs/CAPABILITY_ACCEPTANCE.md alongside this file.
Historical entries below are not current release or production-acceptance claims.
The old SH151 vendor-cause conclusions are not established; consult the later
SH151 handoff and evidence before any adjustment.

Active checkout: C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex.
Original Desktop/pyArgus and pyLynceus remain separate and untouched.
The Codex branch now incorporates review/merge-trial 2d03090: GitHub main,
manual editor d76392a, and the unclassified-cloud QA guard bfe98b4.
This is a source integration, not a rebuilt executable or a GitHub publication.
The September 17 executable in dist/manual-classification-release predates it.

A client job's status at this point is in the private job notes. Two
things from it carry over: endpoint-complete TRJ copies matched every return by
timestamp, and physical attitude conventions remain a separate
verification from timestamp matching; and QA and viewer inputs were once
confused between raw and strip-adjusted copies of the same flight, so
inspect each job manifest rather than assuming matching basenames mean
the same source.

Implementation queue: transactional classification exports and job records;
noise-preserving classification and verified noise detection; explicit active
source/result versions and section inputs; per-file workflow tracking; batch
classification, review presets and section stepping. Preserve existing data.

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
95.3% of 15.28M points colored from 1,033 of 1,083 photos in 275 s.

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
* **Occlusion is refereed by the cloud, photo-major.** Each photo's
  depth grid is built from every CANDIDATE point landing in that
  frame, not merely the ones it colored, and a point whose
  most-centred view is blocked falls back to its next-best unblocked
  view; only a point hidden in every candidate frame stays uncolored.
  Batching under `memory_budget_mb` is what makes the candidate set
  (~122M pairs at Summerville) affordable. A one-cell halo at each
  depth edge is still falsely occluded, and the fallback is what
  keeps that cheap. Two tests assert WHICH photo colored the point --
  weaken them to "did it get a color" and they stop distinguishing
  the fix from the bug, which is exactly how the previous pin went
  stale.
* **Coverage is the datum gate**: overlap and AGL catch a mismatch
  that separates EO from cloud, not one that scales it (metres over
  survey feet keeps both happy), so `--min-coverage` refuses below 5%
  and under half prints a caution.

The eighth adversarial panel (four lenses, 38 findings) drove most of
that; it ran out of quota mid-verify, so one finding carries a full
three-refuter quorum and the rest were triaged by hand against the
code. Details and the honest-gaps list are in RESULTS.md.

## Streaming reads and COPC

`formats/las.py` is the whole point-input surface, and it now offers
three ways in, chosen by memory rather than taste:

* `read_points(path, fields)` -- the whole cloud. Right for anything
  needing global state (the TIN, the alignment solve). ~39 bytes per
  point for the default fields.
* `iter_points(path, fields, chunk_size)` -- chunks, never more than
  one held. Right for every accumulator. 1M points per chunk by
  default; below ~250k, lazrs's parallel decompressor is re-driven
  often enough that wall time rises several fold for little further
  saving.
* `copc_query(path, bounds=, resolution=)` -- a spatial or
  level-of-detail read, when the file is COPC.

Plus `cloud_info(path)` (header only, no points) and
`stream_update(src, dst, update)` (chunked read-modify-write).
`pyargus info` and `pyargus copc` are the commands.

Things worth knowing before touching it:

* **read_points COPIES on purpose.** laspy returns several fields as
  VIEWS into its packed record -- measured on pf6: gps_time,
  intensity, classification, point_source_id -- so a dict holding one
  pinned the whole 30 B/point record alive and a "39 bytes" read
  really cost 56. Do not "optimise" the copies away.
* **DecompressionSelection is not used, deliberately.** It is ~2x
  faster and does not zero what it skips: a skipped field comes back
  filled with the chunk's first point's value, so a wrong mask reads
  as plausible constant data rather than an error (measured: mean Z
  45.99 against a true 50.01).
* **The output header IS the input header** in stream_update. Hand
  building one writes a DUPLICATE ExtraBytesVlr, which laspy reads
  back happily and other software may not.
* **laspy cannot write COPC.** `formats/copc.py` shells out to pdal,
  probing PATH then PDAL_EXE then QGIS/OSGeo4W, refusing by name when
  absent. It ALWAYS passes `--writers.copc.extra_dims=all` (pdal drops
  extra dimensions silently without it) and re-opens the output to
  check point count, extra dims and the COPC VLR before reporting
  success.
* **A COPC query's memory tracks nodes touched, not points returned**;
  a small box is not a small read. Bounds are clamped to the file's
  extent first, because laspy's unchecked int32 cast made an
  oversized box return ZERO points.
* **The streamed density REFUSES when points fall outside the extent
  it was given.** LAS headers are often stale, and np.histogram2d
  drops outside samples silently -- that combination printed a
  believable density computed from a subset (14,977 of 20,000 points
  dropped, reproduced). `--rescan` takes the extent from the points
  instead, at the cost of one extra pass.
* **stream_update writes to a temporary and renames it into place**,
  so a failure leaves no output rather than a truncated cloud that
  opens fine and is quietly missing its tail. It refuses src == dst,
  and it carries EVLRs across: LAS 1.4 allows the OGC WKT there, and
  dropping them stripped the CRS off the delivery.
* **A COPC source streams to a PLAIN LAZ.** An octree cannot survive a
  point-by-point rewrite; re-run `pyargus copc` to rebuild it.

Measured: the 349.79M-point / 9.09 GB dense-matching cloud streams a
density grid in 124 s at a peak of 138 MB, against ~13.6 GB for the
whole-file path. A streamed pass returns arrays identical to a whole
read on the real 15.28M-point delivery -- that equality is what
licenses the rest, and it is pinned in the harness.

## The Colorize stage, and the shared job

`pyargus.imagery.job.colorize_cloud` is the whole colorize sequence --
resolve a camera per role tag, gate the datum, colorize, judge
coverage, stream the RGB out -- and BOTH the CLI and the desktop
Colorize stage are thin callers of it. That is deliberate: the
Phase-7 panel found the GUI's alignment defaults had quietly drifted
from the CLI's with nothing to notice. The stage's numeric defaults
are now READ from `cli.build_parser()` at construction
(`gui._cli_defaults`), and a test pins them, so a difference can only
be on purpose.

Every refusal in the job raises ValueError with the reason; the CLI
turns those into SystemExit and the GUI shows them in its log.
Neither front end invents its own wording, except that each names its
own coverage knob through `coverage_label`.

The Align stage now streams its `--write` copy as well, so the
desktop application is no longer capped at clouds that fit in memory
twice.

Two test lessons from adding the stage: `tests/test_desktop_above.py`
and `tests/test_dialog_types.py` selected stages POSITIONALLY
(`stages[-1]`), which broke the moment a stage was appended -- they
pick by type now; and a second `_FakeRunner` defined at the bottom of
`test_gui.py` silently shadowed the real one. Reuse the fixture that
is already there.

## Tiled ground classification

`pyargus classify-ground --tiled` builds the SMRF surface tile by
tile, so a cloud larger than memory can be classified. `classify/
tiles.py` holds the geometry; `classify/job.py` holds BOTH drivers --
`classify_ground_whole` (the plain command and the desktop Classify
stage) and `classify_ground_tiled` -- and the lattice, candidate
policy (`candidates`: last returns unless `--any-return`) and
labeling rule (`labels`) they share. Keep it that way: the first
tiled driver re-implemented the rule, labeled every non-last return
near the DEM as ground, and disagreed with the plain command on 9-19%
of a multi-return cloud while every test stayed green.

Why it works: SMRF's expensive half makes a RASTER (24 MB for a
10,569 ft SH 151 strip of 41.4M points) and its cheap half is one
bilinear sample per point. Build the surface tiled, apply it streamed.

* **The halo is the whole problem.** The progressive opening is
  ITERATIVE, so influence accumulates as R(R+1) cells, not R -- 1,260
  ft at cell 3 / window 60. That bound is the default. Measured: no
  halo puts a 30 ft error in the DEM where a building straddles a
  seam; 2 * window was exact on that scene; under 2 * window REFUSES.
* **Verified against the plain command, with real seams**: 0 of
  15,284,332 differ on Summerville (window 30, 12 tiles, every box
  short of the project) and 0 of 41,366,226 on an SH 151 strip at the
  DEFAULT halo (8 tiles). A seam is real only if the tile's halo box
  stops short of the project -- `plan_summary` counts them, and both
  acceptances refuse otherwise. Compare against the COMMAND, never a
  mask built for the purpose: the first acceptance did the latter and
  its 0 answered a different question.
* **Memory is set by the largest halo box**, not the raster: the box
  can never be much under 2 * halo across, and at the default tile
  size a strip plans as 2 tiles, one holding 83% of it. `--tile-size`
  trades memory for overlap; the job logs the plan's cost before it
  runs and the most points one tile held after.
* **No COPC index means one full pass per tile, plus one to write**,
  and the job counts them. An index removes passes, not overlap.
* **The grid comes from the LAS header** in both commands; a stale
  header refuses, `--rescan` takes the extent from the points.
* **COPC reorders points**: row i of a copy is not row i of the
  source. Do not pair them by index.

## Next step, with reasoning

**The roadmap is complete.** What remains open, by value: (1) THE
REAL PROJECT (SH 151, set aside pending the vendor's LCP2 list): the
lidar block is internally rigid and the misses are position-locked;
when the vendor responds, re-occupy the worst marks and decide
between control-net vs lidar-datum error -- reference/sh151_* holds
the case. (2) Archive any vendor-stated miscalibrated flight as the final
alignment acceptance.

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


Trajectory GUI follow-up: removed misleading default same display; explicit
Apply time base to ALL trajectories does not propagate attitude approval or
GPS week. Refresh preserves selections; start preflight highlights unset
trajectories and gives actionable instructions without a worker traceback.
25 project tests passed. Release path: dist-3d-timefix/pyArgus/pyArgus.exe.
Time-setting release checks: 253 passed, 1 skipped in full suite; all 25 project tests passed separately; packaged self-test exited 0.


## DXF breakline import and output-specific previews

New formats/breaklines.py dispatches GeoJSON/DXF with ezdxf>=1.4,<2 in the
cad extra and desktop bundle. Refuses unsupported or ambiguous planar geometry;
no automatic draping, units conversion or projection. GUI Contours and CLI
contours use it. Surface math unchanged: breaklines remain soft TIN constraints.
New stage_preview.py renders bounded north-up classification and vector contour
previews, legends and optional breakline overlay. Classify and Above Apply use
the produced labels; Contours uses the actual exported lines. 3D class colors
share this palette. Optional preview failure does not misreport saved outputs.
Seven tests cover DXF XYZ, OCS, closure, export/import roundtrip, refusals, depth
ordering, and actual Classify/Contours GUI work closures. Preview images
visually inspected (Summerville classes and synthetic contours). Build target:
dist-usability/pyArgus/pyArgus.exe. Unrelated imagery work remains untouched.
Final usability validation: 261 tests passed; dist-usability packaged self-test exited 0, including DXF read and contour rendering. Full reference run: 49 passed / 3 failed of 52; all 46 non-colorization checks passed. Failures match the pre-existing concurrent imagery differences exactly: pct_colored 95.3115 vs 70.86, pct_occluded 4.68528 vs 29.14, images_used 1033 vs 1019. No imagery code or expectations changed. Full log: usability-reference.log.


## Large-project disk-backed QA

`large_qa.py` and a chunk_sink seam in project.load add exact disk-backed
statistics above Project.max_points. Smaller QA and alignment remain unchanged.
SQLite cache 32MiB, external sorts, input chunks 500k; stores density cell counts
and class-2 elevations/strip identities, then exact cell medians and pair joins.
Tiles partition final cells, no per-tile median approximations or duplicate
halo counts. Uses half-open world-aligned cells including the outer edge;
legacy maximum-edge folding differs only at that edge. Source metadata and
trajectory signatures are rechecked before publication. Scratch is separate
from result publication and connections close before Windows directory cleanup.
Automatic disk allowance 160 bytes/input point; system temp also needs room.
GUI explains automatic mode. HTML, PNG/PGW tiles, full CSV cells and manifests.
Optional control local median retained; per-strip control plane decomposition
not implemented in large report and explicitly disclosed. Alignment not scaled.

Validation: 268 full-suite tests passed. Six new tests cover parity with legacy
QA, chunk/tile boundaries, matching refusal, checkpoints/no-ground, low disk,
and cancellation cleanup. Full 15,284,332-point Summerville run finished in
47.39 seconds, all points counted, 1,011,700 ground; density median 8.333333,
p95 22.888889, strip medians 0/-0.005/+0.030 ft and pair 1/2 RMSE 0.20980012,
matching recorded reference results. Outputs reference/reports/large-qa-20260910.
No full Connector 402M run yet. Desktop dist-large-qa/pyArgus/pyArgus.exe.
Final large-QA validation: all 8 focused tests passed, including SQLite interruption and a safe mocked-metadata change before publication. Packaged dist-large-qa --self-test exited 0 and exercised automatic disk-backed QA. A proposed file-mutation test was rejected by automatic approval review and was never executed; replaced by metadata simulation.


## SH151: AT-referenced correction preflight (not applied)

User wants cloud to follow AT rather than adjudicating cause. VRAT_FINAL's
8242026BundleReportControl.txt has 53 explicit Bundle Coord XYZ values, avoiding
undocumented stereo residual sign. Read every source strip (22) at these targets.
Source LAS are unclassified near targets; class-2-only gather was stopped and
replaced by unclassified surface-neighborhood sampling excluding noise codes.
Fresh caches at reference/reports/sh151_at_fit/surface_cache. No source edits.
29 targets pass >=2 enclosing, smooth, <=8% slope local planes, <=0.10ft spread;
known natural-ground/tall-grass CAL225/CAL226/CAL17 excluded.

at_fit.py implements bounded common Z correction, RBF/plane/bias candidates,
leave-one-out and five spatial blocks, plus new-file streamed export with full
point-record readback SHA256 and metadata checks. 3 new tests pass; 305 full-suite
tests passed. The selected conservative candidate: smoothing100, alpha0.25,
baseline RMS0.131796ft, fitted RMS0.120826ft, LOO0.125847ft, spatial0.128846ft.
Grid range -0.049223 to +0.030255ft. This is only marginal predictive improvement.
Report/model/grid in reference/reports/sh151_at_fit. CANDIDATE ONLY; NO corrected
LAS copies created. Await target preference / stereo-ground XYZ or ground DTM
for a meaningful local fit. Do not describe this as a completed correction.
Initial user question asked whether to use final bundle targets or a stereo
surface; no answer arrived during preflight. Final bundle used provisionally.

## September 22: safe ground classification publication

Whole and tiled ground drivers now share a staging/publication wrapper and
schema-1 job records. Partial/cancelled writes cannot be published under the
requested final name; existing destinations are refused even in a publication
race. Output is fully read and point counts checked before publishing. Input
size/mtime changes refuse publication. See docs/JOB_RECORDS.md for limits.
Full regression suite: 418 passed in 143.54 seconds. The earlier buffered
reference run was stopped without a verdict; an unbuffered current-code run
is pending. No numerical classification policy was changed, no project LAS
was reclassified, and the packaged executable has not been rebuilt.

Validation completed September 23: reference.run_all passed 73/73 checks.
Colorization accounted for 1,243 seconds of the reference runtime. Final
classification-record/review integration checks passed 18/18 after the earlier
418-test full-suite pass. This validates regression behavior, not a client
job's accuracy or acceptance of its provisional classified outputs.

## Explicit section sources — September 23

In Clouds and cross-sections, choose **Section source** before extracting.
One loaded cloud is selected automatically. With multiple loaded clouds,
choose its full path or **Compare all loaded clouds** explicitly. This choice
is independent of viewer visibility. Changing the source clears the previous
profile. Extraction counts identify source filenames; single-cloud selection
can be edited without removing other clouds from the project.

Ground-classification job records can also be opened in the review panel.
Their ground fraction is a classification proportion, not an accuracy measure.

## September 23: independent flight review

Classification decisions now target the selected history row. Ground runs are
tracked per source cloud; switching cloud/output routing does not make them
stale, while real parameter changes and same-source reruns do. Dependencies
retain all current classification attempts. History shows source filenames and
staleness reasons and preserves the selected row after review.
Validation: 421-test full run, followed by 37 final tracker/review/editor tests.
No numerical pipeline changes; prior 73/73 reference gate remains applicable.
Automatic project source/result promotion is not implemented yet.

## Active processing versions — September 23

A successful Classify run now promotes its new cloud into the project's input
list for that flight and displays the active project inputs. The original
stays in the sidebar as a Retained version; Active input labels identify what
project QA/alignment will read. Trajectory bindings move with the active
version. Failed/cancelled runs do not promote outputs. Activation does not
accept classification quality or independent accuracy.

Right-click one cloud and choose Use this version for processing to switch
back. Showing retained files for comparison does not re-add them to project
inputs. Explicit Section source selection remains separate. Old workspaces
recover source/result links only from unambiguous completed classification
records with matching file metadata; their active inputs do not change on
load. Unrelated imported clouds are not grouped by filename guesses.

Re-inspecting promoted outputs no longer invalidates completed ground
classification when its original input and parameters remain unchanged.
Input/output changes still invalidate it. Classification reruns on derived
versions share the same flight's review history. Busy viewer loads queue the
new active display until the current load finishes.

Validation: full suite 426 passed, followed by 42 review/workspace/editor
checks and 23 final workspace checks. Numerical algorithms were unchanged;
the previous 73/73 reference result remains the numerical baseline.
