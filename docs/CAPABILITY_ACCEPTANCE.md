# pyArgus capability and acceptance inventory

Snapshot: 2026-09-15. Reviewed Codex branch `codex/isolated-improvements` at
`cbb7504`, based on Claude's `b6b0d3f`. This is an engineering inventory, not a
claim of TerraSolid feature parity or survey certification.

## Product objective

Build an end-to-end open-source lidar workstation that can import, inspect,
classify, adjust, edit, surface, quality-check and deliver real projects.
Retain the existing shared math and job implementations where evidence supports
them. The first product milestone is one reproducible production workflow,
not another completed list of algorithms.

## Status vocabulary

- **Implemented / recorded validation:** callable code, tests and documented
  real-data evidence exist for the stated scope. Not unrestricted readiness.
- **Implemented / limited validation:** callable code and tests exist, but
  operational, sensor-transfer or independent accuracy evidence is incomplete.
- **Experimental:** a prototype or candidate exists but is not accepted for
  applying production corrections.
- **Not implemented:** no complete operator workflow identified in this audit.
- **Release gap:** engineering or distribution requirement remains unresolved.

No capability receives blanket production approval from this inventory.
Accept a defined use case, dataset, version and parameter range instead.

## Capability matrix

Paths are relative to the repository root. Test filenames are evidence entry
points; they are not assertions that every possible edge case is covered.

| ID / capability | Current status and entry points | Evidence | Limitation / next acceptance |
|---|---|---|---|
| C01 LAS/LAZ ingest and metadata | Implemented / recorded validation. `info`, `formats/las.py` | `tests/test_las.py`, `tests/test_streaming.py`; reference streaming equality | Validate stale headers, extra dimensions, source metadata and point-order preservation on the chosen delivery. A COPC conversion changes point order. |
| C02 Streaming density and COPC | Implemented / recorded validation. `density`, `copc`, `formats/copc.py` | `tests/test_density.py`, `tests/test_copc.py`; large streaming reference | COPC creation has an external executable dependency. Spatial indexing reduces repeated reads, not overlapping processing. Record dependency availability and actual memory/I/O. |
| C03 Trajectory reading and attachment | Implemented / limited validation. `trajectory-info`, `sbet-info`, `formats/trajectory.py`, `align/attach.py` | `tests/test_sbet.py`, `tests/test_trj.py`, `tests/test_attach.py`; Summerville SBET and Connector TRJ examples | Clock, week, vertical reference and attitude convention remain sensor-specific. Parsing is not calibration validation. Full SH151 association/uncertainty audit remains open. |
| C04 Multi-file project inventory | Implemented / recorded validation. `project-info`, Data > Multi-file project | `tests/test_project.py`; recorded Connector 402,465,700 uniquely matched points | JSON stores paths/settings, not data. Demonstrate reopen on a moved project and clear missing-file handling. One sensor/calibration context per project. |
| C05 QA reports and checkpoint statistics | Implemented / recorded validation. `qa-report`, `project-qa`, `qa/` | `tests/test_report.py`, `tests/test_checkpoints.py`, `tests/test_control_by_strip.py`; Summerville baseline | Different local/TIN measurement methods yield different statistics. Reports must state method, units, exclusions and checkpoint independence. |
| C06 Disk-backed large-project QA | Implemented / recorded validation. `large_qa.py`, automatic project QA path | `tests/test_large_qa.py`; full Summerville recorded parity | Not proof of full Connector acceptance. Scratch allowance and disk failures need operator-visible handling. Large path lacks the small path's full per-strip control-plane decomposition. |
| C07 Ground classification | Implemented / recorded validation. `classify-ground`, Classify; `classify/job.py` | `tests/test_ground.py`, `tests/test_cli_classify.py`, `tests/test_tiled_ground.py`; Summerville and one SH151 strip equality | Shared candidate/label policy is essential. Tiled memory depends on halo point count. Whole GUI path is not automatically tiled. Equality is not independent ground-label accuracy. |
| C08 Above-ground classification | Implemented / limited validation. train/apply jobs, Above ground; `classify/above.py` | `tests/test_above.py`, `tests/test_desktop_above.py`; recorded Summerville metrics | Trusted joblib only; parameters/units must match. Existing labels are not independent truth. Need spatially separated and cross-project class precision/recall. |
| C09 Strip offset/boresight adjustment | Implemented / limited validation. `align`, `project-align`, `align/solve.py` | `tests/test_align.py`, `tests/test_attach.py`, `tests/test_cli_align.py`; injected truth and Summerville reference | Observability, correct sensor geometry and independent checkpoints required. Project solve defaults to a 25M-point array limit. Streaming exports do not remove it. |
| C10 Time-dependent drift adjustment | Implemented / limited validation. `align --drift-spacing`, `align/drift.py` | `tests/test_drift.py`; constructed drift cases in `reference/alignment_proof.py` | Flexible corrections can absorb unrelated error. No accepted SH151 drift solution. Require withheld spatial/flight checks and parameter observability. |
| C11 DTM/DSM/TIN generation | Implemented / recorded validation. `dtm`, `surfaces/` | `tests/test_dtm.py`, `tests/test_tin.py`; reference surfaces | Define gap filling, interpolation support and vegetation/structure policy. Not a complete interactive terrain repair workflow. |
| C12 Breaklines and contours | Implemented / limited validation. `contours`, `formats/breaklines.py` | `tests/test_contours.py`, `tests/test_contour_formats.py`, `tests/test_usability.py`; recorded 2,152 Summerville contour lines | TIN constraints are soft. No automatic trustworthy draping of 2D drawings. Hard topology-preserving breaklines and surface editing remain future work. |
| C13 Image colorization | Implemented / limited validation. `colorize`, Colorize; `imagery/job.py` | `tests/test_colorize.py`, `tests/test_cli_colorize.py`; recorded Summerville results | Job loads full XYZ and retains RGB arrays. Image cache budget is not a whole-job memory bound. Camera/datum/visibility checks do not prove absolute accuracy. |
| C14 Calibration provenance | Implemented / limited validation. `imagery/camera.py`, `imagery/job.py` | `tests/test_calibration_selection.py`; image-specific sidecar regression tests | Codex fix rejects ambiguous folder fallback. Resolver still takes one sample per role; different serials/calibrations under one role can be missed. P4D authority/parser question is unresolved and belongs to separate evidence. |
| C15 Desktop workflow and completion | Implemented / limited validation. `gui.py`, `project_gui.py`, stage previews | `tests/test_gui.py`, `tests/test_job_status.py`, `tests/test_dialog_types.py`, packaging self-test | Timer indicates elapsed activity, not reliable ETA. Cancellation varies by job and may wait for expensive work. No durable job resume or complete end-to-end multi-file pipeline demonstrated. |
| C16 3D viewing | Implemented / limited validation. `viewer3d.py` | `tests/test_viewer3d.py`; recorded Summerville visual inspection | Fixed sample about 150k points, orthographic rendering. No progressive detail, full point editing, cross-section workflow or measurement tools identified. |
| C17 Classification editing / undo | Not implemented as an operator workflow | Viewer and GUI review | Need stable point identities, durable edit history, selection tools, undo/redo and round-trip verification. Not just drawing a selection rectangle. |
| C18 SH151 correction | Experimental. Original-repo reports and handoffs | AT, stereo, direct-image and trajectory screens summarized below | No accepted corrected LAS. Do not treat prototype surface or correlation peaks as independent control. |
| C19 Raw sensor regeneration | Inputs/workflow incomplete for SH151 | Directory and archive audit | SBETs do not supply raw laser ranges, encoder observations or lidar calibration. Reprocessing delivered XYZ is not recovery of original measurements. |
| C20 Release, license and reproducibility | Release gap. `pyproject.toml`, `packaging/` | `tests/test_packaging_gate.py`, current branch history | Dependencies have broad minimums; no root LICENSE found. Choose/document a project license and review distribution dependencies before claiming an unrestricted open-source release. Binary/source provenance and repeatable build remain incomplete. |

Implementation paths in this table omit the `pyargus/` prefix where obvious.
This is a scoped inventory of pyArgus, not a current feature-by-feature audit of
TerraSolid, POSPac or other products.

## Evidence ledger and confidence

| Evidence | Recorded result | Boundary |
|---|---|---|
| Codex isolated full suite | 336 passed, 1 skipped; 137 seconds | Run for cbb7504 change. Skip reason not captured in full run; later packaging and COPC targeted tests passed. |
| Inherited Claude gate | b6b0d3f records 332 tests, 73/73 reference checks | Historical record. Reference gate not rerun in Codex worktree yet. |
| Summerville QA | 15,284,332 points; interstrip medians 0.000, -0.005, +0.030 ft | Already aligned; a regression reference, not evidence of fixing a bad block. |
| Summerville control | Local six-mark median +0.146 ft, NMAD 0.148 ft | Local median method, not interchangeable with TIN metrics. |
| Ground equality | Latest accepted record: zero whole/tiled differences on Summerville and 41,366,226-point SH151 strip | Latest tests corrected earlier multi-return and seam-test defects. Do not repeat superseded memory/equality claims. |
| SH151 sparse AT fit | Baseline 0.1318 ft; spatial CV 0.1288 ft | Marginal candidate, unapplied. |
| SH151 stereo pilot | Pair median discrepancy about 0.465 ft; no accepted four-view pavement references | Original stereo geometry not reproduced reliably. |
| SH151 trajectory screen | 52 marks/161 observations; 0.1008 to 0.0991 ft spatial CV | Three unsupported held-out observations; not accepted. No attitude/boresight solve performed in this screen. |

Source of recorded metrics: `reference/RESULTS.md`, `HANDOFF.md`,
`CODEX_WORKTREE.md` and the original checkout's SH151 handoffs. Earlier
HANDOFF passages claiming the roadmap is complete describe implemented phases,
not an accepted end-to-end product. Evidence should be refreshed per release.

## Sample-specific assumptions that must remain visible

1. Foot units are not interchangeable; control column order is explicit.
2. Summerville's TrueView frame and camera conventions do not establish SH151's.
3. Filename camera roles do not uniquely identify physical camera serials.
4. Class 2 is useful when valid ground labels exist; SH151 near-control data
   were unclassified. Smoothness alone does not prove pavement or bare ground.
5. Same control used in fitting cannot establish independent accuracy.
6. A small-cloud equality test does not prove tile seams or large-job memory.
7. Source and COPC row indices cannot be assumed to identify the same point.
8. Atomic publication and cancellation must be checked per job; do not infer
   all stages share the project export's guarantees.

## First product acceptance: P1, reviewed lidar deliverables

Scope: a declared single-sensor, multi-file block whose alignment fits the
documented resource limits. Ground classification may use the tiled CLI.
Optional alignment is evaluated separately; an already-good block must not be
adjusted merely to exercise a button. No arbitrary sensor transfer is implied.

| Gate | Procedure | Required evidence / pass condition |
|---|---|---|
| P1-01 Input contract | Inventory cloud headers, source IDs, CRS, units, control roles and optional trajectories. | Manifest with exact paths/signatures, version, settings, point counts and declared conventions. Invalid or ambiguous inputs refuse before outputs. |
| P1-02 Baseline | Produce QA before modifying points. | Reopenable report, explicit statistic methods, counts and exclusions. Reserve independent checks before fitting. |
| P1-03 Ground | Run the chosen whole/tiled path on representative multi-return data. | All output points accounted for; non-target dimensions preserved. Tiled parity against the actual whole command on a manageable subset with genuine seams. Record peak tile size and passes. |
| P1-04 Review | Inspect classified ground in plan/3D and targeted cross-sections. | Operator can identify representative ground defects. Cross-sections/editing currently missing: this gate is NOT complete. Temporary external review must be documented, not counted as native functionality. |
| P1-05 Products | Generate terrain and contours from reviewed labels. | Independent contour-level/geometry checks; declared NoData and breakline policy; output readable downstream. Project-specific tolerances agreed before evaluation. |
| P1-06 Optional adjustment | Fit supported parameters using overlap and fitting controls only. | Exported coordinates improve the predeclared withheld metrics without degrading overlap or other checks. Degenerate parameters refuse. Report unadjusted option too. |
| P1-07 Failure recovery | Stop a job, exercise insufficient disk, missing input and corrupt metadata. | Clear status; original files unchanged; incomplete products unmistakable; documented restart procedure. Durable resume is future work. |
| P1-08 Delivery | Reopen project and products in a fresh process/environment. | Identified source/build versions, checksummed outputs, packaging self-test, all required checks executed or specifically justified. No anonymous skipped gate. |

These are acceptance requirements, not claims that all gates currently pass.
Numerical accuracy thresholds must come from the particular delivery spec and
measurement method. Do not invent one universal foot/pixel threshold.

## Prioritized work from the inventory

| Order / issue | Concrete task | Done when |
|---|---|---|
| I01 Reproducible baseline | Record exact environment and test/skip results; establish source-to-build identity and a serial validation command. | A fresh checkout reproduces results; every skipped check is explained; executable points to its source commit. |
| I02 Camera-role consistency | Inspect every matched frame's resolved calibration, compare projection parameters, retain provenance and refuse conflicting same-role cameras. | A synthetic mixed-camera case fails on old code and is handled explicitly; equivalent sidecars still work. No guessing P4D conventions. |
| I03 Workflow manifest | Define a common run manifest and stage handoff contract, then add it incrementally to existing shared jobs. | Operators can identify inputs, outputs, roles, version, completion and failure state for P1. |
| I04 Cross-section review | Add non-editing sections and measurements before editing. | Known geometry returns correct distances/heights, and a representative operator can diagnose ground/strip defects. |
| I05 Project scale | Measure memory and cancellation for each stage; expose honest limits and costs. | Large-file resource report; no claim that streaming write bounds a whole solve. |
| I06 SH151 geometry | Full SBET association/provenance/uncertainty audit followed by constrained adjustment experiments. | Independently checked pilot improves; no application of current rejected candidates. |
| I07 Release policy | Select project license with Bryon; record dependency licenses and distribution requirements. | Explicit license/distribution plan and release checklist. Do not choose a license silently. |

Next implementation recommendation: I01 first, then I02. Continue SH151 as a
bounded parallel research track, not a gate on every usability improvement.

## How to maintain this inventory

- Every meaningful feature change updates its capability row and evidence.
- Keep source commit, dataset, parameters, method and result together.
- Never promote a recorded test to a broader accuracy claim.
- Refresh P1 after each release; track incomplete gates explicitly.
- Run heavy checks serially on this Windows machine. Preserve Claude's checkout
  and environment; use the Codex worktree for these improvements.

Documentation-only audit: no processing algorithms or source datasets were
changed, and no heavy reference run was performed to create this inventory.
