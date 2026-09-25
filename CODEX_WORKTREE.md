# Codex worktree

Checkout: `C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex`

Branch: `codex/isolated-improvements`

Starting commit: `b6b0d3f` from the original pyArgus checkout, including Claude's
shared whole/tiled ground-classification policy and stronger seam tests.

The original checkout remains at
`C:/Users/bjordan/OneDrive - Platinum Geomatics/Desktop/pyArgus` on `main`.
This is a Git worktree: source files and `.venv` are separate, but Git objects,
remotes and branch references are shared. Do not change global Git settings,
force-push, move main or modify the original checkout while working here.

Use this checkout's `.venv/Scripts/python.exe`, never the original checkout's
environment. The environment was freshly installed from `.[dev]`; do not
assume its unconstrained dependency versions match Claude's environment.
Dependency installation here does not change the original `.venv`.

Run heavy shells/tests serially on this Windows machine. Consult the user
before overlapping a long run known to be active in another agent. Keep Z:
datasets read-only, keep pyLynceus isolated, and publish new outputs only.

## First bounded improvement

Camera-sidecar selection retains exact image and stem sidecar precedence.
Without an image-specific sidecar, a shared calibration is accepted only if
there is exactly one `.cal` file immediately beside the image. Multiple
fallback files refuse with their names; nested flight folders are not searched.
An explicitly supplied calibration remains an explicit user choice.

This closes an arbitrary-first-file fallback in image colorization. It does
not establish the authority of vendor P4D calibration, add P4D parsing, verify
serial-to-frame provenance, or solve the still-open issue of multiple physical
cameras sharing a role tag. Those require separate work and validation.

## Next review targets

1. Validate every camera role's calibration consistency across all frames;
   current resolver samples one calibration per role. Preserve provenance.
2. Implement a read-only, complete SH151 trajectory association/uncertainty
   audit before any new geometry adjustment. SBETs are available; raw laser
   ranges/encoder data and lidar calibration remain missing.
3. Advance constrained overlap/control adjustment only when withheld checks
   improve. Do not force image agreement by drifting camera and cloud together.

No original workstation calibration or source data should be edited to make
an experiment pass. Keep proposed changes on this branch for review before
integration; worktree creation does not merge or push them.

## Validation of initial change

Full suite in the isolated environment: 336 passed, 1 skipped (137 seconds). The full run did not print the skip reason. Subsequent targeted packaging and COPC checks passed (1 and 9 tests respectively). pip check reported no broken requirements. No real-data reference battery was rerun for this imagery-only change. No source datasets, original-checkout files or pyLynceus files were changed.


## Capability inventory

The first product audit is in [docs/CAPABILITY_ACCEPTANCE.md](docs/CAPABILITY_ACCEPTANCE.md). It defines 20 capability areas, the P1 production-workflow acceptance gates and a prioritized improvement backlog. Read it before treating an implemented phase as production-ready.


## Serial baseline runner

Use python -m devtools.validate in this checkout's environment. See docs/VALIDATION_BASELINE.md for scope, output manifests, skip review and remaining clean-machine/build-provenance work.


## All-frame camera consistency

The colorization resolver now checks every distinct matched image's calibration, compares all projection parameters within each role and refuses conflicts before reading the cloud. Equivalent sidecars are allowed; explicit overrides remain explicit. Returned colorization statistics include per-image paths, calibration hashes, parameters and selection mode. These statistics are not yet automatically persisted as an output-sidecar manifest. This does not identify physical serials or establish P4D authority.


Real-data metadata check: all 1,083 Summerville images passed all-frame consistency (361 each for N/P/S). Per-role focal lengths are approximately 4420.2, 4419.1 and 4416.8 pixels. Provenance saved under reference/reports/calibration-consistency/summerville.json. This was not a new image colorization or independent geometry validation run.


## Shared job records

Added schema-1 per-attempt records to CLI/GUI colorization, including failures
and cancellation. See docs/JOB_RECORDS.md for identity and transaction limits.
Other production stages are not integrated yet.


## QA and alignment records

Extended records to single-cloud CLI/GUI QA and alignment, plus project QA
(array and disk-backed dispatch) and project alignment. Cancellation propagates
while retaining a cancelled record. Project before/after QA summaries are
persisted and included with export mappings; single-cloud comparisons retain
their solver/unquantized limitations. Source data and numerical algorithms
are unchanged. See docs/JOB_RECORDS.md for output locations and coverage.


## QA review workspace and cross-sections

Added Data > QA review / cross-sections. Reviews schema-1 job records and
before/after metrics, then loads bounded plan samples and full-file corridor
sections for original/corrected comparisons. Section geometry, counts,
sampling, cancellation, input mutation and GUI rendering have synthetic tests.
See docs/QA_REVIEW.md for workflow and limits. Z: was unavailable during this
implementation, so no new Summerville/SH151 field-data validation is claimed.


## Unified workspace and progress tracker

Embedded the project controls and 3D viewer in the main desktop; QA and
cross-sections are docked, with no main raster/2D cloud preview. Added workflow
history, review decisions, conservative staleness, workspace persistence,
point picking, filters, viewport refinement, and asset/deliverable controls.
See docs/UNIFIED_WORKSPACE.md. Existing numerical pipelines and source datasets
are unchanged; single-cloud processing stages remain explicit.


## GUI consolidation — September 16, 2026

- One Project files sidebar and mixed-file import; source clouds display
  automatically. Trajectory registration is shared with the viewer and survives
  a cancelled display confirmation. Clock prerequisites select the sidebar rows.
- Task selector with explicit entire-project / selected-cloud scope; project
  output folder and single-cloud trajectory selection stay visible in context.
- Hidden duplicate legacy input panels, compact camera presets, sidebar
  visibility/actions, Log dock, readable job history and saved task selection.
- Regression coverage includes import deduplication, missing clocks, routing,
  selected trajectory configuration and removal without phantom re-import.
- Standalone viewer/project adapters remain supported. Core QA, classification
  and alignment algorithms are unchanged; see docs/UNIFIED_WORKSPACE.md.

## Manual classification editor — September 17, 2026

Added source-indexed editing of complete single-cloud sections. Selection uses
station/elevation and the full declared corridor width, not display samples.
The separate editor supports rectangle/polygon selection, class assignment,
undo/redo, guarded application shutdown and cancellable export. Export verifies
every written point record and preserves original metadata; edits and history
are recorded beside the new cloud. See docs/MANUAL_CLASSIFICATION.md.

Sampled/multifile sections, waveform LAS and COPC editing are refused. Workflow
tracker integration and resumable editing sessions remain future work. The
Z: drive was unavailable, so Summerville editing acceptance remains pending.

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
job's accuracy or acceptance of its provisional ground-classification outputs.
## Current executable — September 23, 2026

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-23-8f45724/pyArgus/pyArgus.exe

Keep the entire pyArgus folder, including _internal. Source commit: 8f45724.
The adjacent build-info.json records the executable SHA-256 and validation.
Packaged self-test exited 0. Reference gate: 73/73; full suite before final
review changes: 418 passed; final record/review tests: 18 passed; final
section/workspace/editor tests: 34 passed. This supersedes the September 17
executable. No client-job reclassification or accuracy acceptance is claimed.
GitHub publication and in-application build identity remain pending.


## September 23: independent flight review

Classification decisions now target the selected history row. Ground runs are
tracked per source cloud; switching cloud/output routing does not make them
stale, while real parameter changes and same-source reruns do. Dependencies
retain all current classification attempts. History shows source filenames and
staleness reasons and preserves the selected row after review.
Validation: 421-test full run, followed by 37 final tracker/review/editor tests.
No numerical pipeline changes; prior 73/73 reference gate remains applicable.
Automatic project source/result promotion is not implemented yet.
## Current executable — per-flight tracker, September 23

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-23-fa553e6/pyArgus/pyArgus.exe

Keep _internal beside the exe. Source commit fa553e6; build-info.json includes
SHA-256 and validation. Packaged self-test passed. Full run: 421 passed;
subsequent tracker/review/editor checks: 37 passed; final tracker checks: 17
passed. The 73/73 reference gate predates these workflow-only changes.
Source/result promotion and noise handling remain pending; no new client-job
cloud was generated. Commits are local, not pushed.


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


## Noise and sequential batch classification — September 24, 2026

Implemented in the isolated Codex checkout: preserve/exclude classes 7/18 in
whole and tiled ground classification; optional explicit min/max elevation
screens; GUI Classify / Entire project with a batch output parent, sequential
flights, unique filenames and per-flight records/review. Stop/failure halts
the queue and retains completed results. Original clouds remain unchanged.
See docs/NOISE_AND_BATCH.md for operator steps and limitations. Spatial noise
detection and automatic batch resume are not implemented. No client-job
cloud was reclassified, and that job's provisional outputs remain unaccepted.

Validation: full suite 432 passed, one Tk display skip; all 11 record tests
passed on retry. Final noise/batch/workspace tests passed 29, including a later
flight failure retaining the earlier successful output. Full reference run:
72/73, with only the old tile candidate count failing after intentional noise
exclusion. Expected count updated with explanation in reference/RESULTS.md;
a separate tiled reference repeat passed all 13 checks, including the updated exact count and equality.
New executable packaging is the remaining release step; older build below
remains the released executable until the new release entry is added.


## Latest executable — noise and batch classification, September 24

C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-24-c747213/pyArgus/pyArgus.exe

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


## Performance baseline and GUI status — September 24, 2026

The first language/architecture step is complete: repeatable profiling, not
migration. See docs/PERFORMANCE_BASELINE_2026-09-24.md and
reference/profile_workflow.py. Two strip-adjusted LAS sources from a real
client delivery were read-only; verified copies and benchmark-only
classified/QA outputs are kept outside the project in a local benchmarks
folder that is not in the repository.
No benchmark result was promoted or accepted in a GUI workspace.

Two source/local repeats matched result counts. Warm sections took about 2 s
at the median and refinement about 3 s; disk-backed QA took about two
minutes. Actual 920x672 redraws at about 150,000 points took under 0.1 s
per frame. Initial 1x1 redraw samples are excluded; corrected
measurements and harness hashes are preserved. Final synthetic harness smoke
passed all 14 operations with valid canvas dimensions and unchanged source.

Largest measured numerical costs are already compiled SciPy morphology,
NumPy sorting and SQLite reduction. One source scan was an outlier whose
elapsed time was about twenty times its CPU time, so cache/access conditions
matter. These are instrumented, warmed-cache observations, not cold-network
benchmarks or accuracy checks.
Next experiment: optional cached/spatial access with exact section-count,
point-index/coordinate and invalidation checks plus measured build/query costs.
No Rust/C++ migration or production algorithm change is justified yet.

GUI rewrite remains partial: docs/GUI_STATUS.md is the delivered/pending
checklist. Presets, section stepping, compact layout, next-action guidance
and in-app build identity remain pending. Current released exe is still
2026-09-24-c747213 below; this profiling increment needs no executable rebuild.


## Spatial section-cache experiment — September 24, 2026

Experiment complete; see docs/SECTION_CACHE_EXPERIMENT.md. This is not yet a
GUI feature. The local sidecar preserves original point indices and replays
reference sampling order. Production source files and workspace inputs remain
unchanged. No Rust/C++ or production algorithm change was made.

On a real two-file client delivery of about 25 million points, the cache
built in under half a minute and under 1 GiB. Short sections measured roughly
5-8x faster, a long narrow section about 3x, a broad section ~1x.
Six geometries repeated twice agreed exactly in counts and every returned
array, including sampled order. 11 focused tests passed, including oblique
large-coordinate, invalidation and interrupted-build cases. Rough build-cost
break-even is under twenty queries for the tested mix, not a universal threshold.

Evidence: C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-benchmarks/2026-09-24-section-cache-oriented.
The initial bounding-box-only experiment is retained separately and documents
why corridor-oriented cell selection was necessary. Metadata-only source and
cache invalidation cannot detect deliberately preserved size/mtime changes.

Next: optional GUI integration with visible build/cancel/progress, disk-space
and cleanup policy, source-version invalidation and a full-scan fallback.
The current executable is still c747213; this prototype is reference-only.


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
37 passed after message/source-selector polish. Managed-cache tests on both
strip-adjusted files of a real client delivery matched the full scan exactly
for six query shapes, including a sampled corridor of several million returns
and the broad-query scan fallback.
Evidence: C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-benchmarks/2026-09-24-section-cache-gui/report.json.
Source datasets and workspaces were not modified. Classification, alignment
and terrain algorithms were unchanged. Packaged self-test now exercises cache
build/query/clear; executable packaging is the remaining release step.


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

