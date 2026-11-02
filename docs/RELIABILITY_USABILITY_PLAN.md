# Reliability and usability implementation plan

Authorized September 22, 2026. Work only in the isolated Codex checkout.

1. Reconcile reviewed branches, current handoff, serial regression validation.
   Source integrated via fast-forward to 2d03090. Shutdown cancellation fixed.
2. Build identity in executable/About and records; transactional classification
   output and per-run provenance. No partially written final deliverables.
3. Source/result version model: exactly one active analysis version per flight;
   explicit comparison mode. Separate visibility from analysis inclusion.
   Cross-section controls must list input files before extraction and report
   complete/sample status. Automatically activate successful outputs.
4. Independent per-file stage attempts and review decisions, with explicit
   stale reasons. Display-only changes must not invalidate processing.
5. Preserve/exclude noise classes in classification. Reproduce reported Gravel
   Springs pits before choosing a detector; do not hard-code an elevation band.
   New classifications must use new output names and retain originals.
6. Control import and project QA, overlap checks and checkpoint provenance.
   External LP360 results are comparisons, not independent ground truth.
7. Sequential batch classification, one project output folder, unique names,
   review presets, profile fitting/stepping, compact layout and next actions.
8. Rebuild outside OneDrive with explicit build provenance; publish after checks.

Example_Project remains provisional. Do not run alignment or approve ground_01.
The main-checkout, pyLynceus and original source datasets remain unchanged.

Validation for initial integration: 44 focused tests passed; full suite 410 passed in 142.79 seconds. Reference battery launched separately; result pending at this checkpoint. Executable has not been rebuilt.

Validation completed September 23: reference.run_all passed 73/73 checks.
Colorization accounted for 1,243 seconds of the reference runtime. Final
classification-record/review integration checks passed 18/18 after the earlier
418-test full-suite pass. This validates regression behavior, not Gravel
Springs accuracy or acceptance of its provisional ground_01 outputs.

September 23 noise/batch implementation: known classes 7/18 are preserved
and excluded by both classification drivers. Optional explicit min/max Z
screening and sequential GUI project classification are implemented. Spatial
noise detection, Example_Project pit validation, automatic batch resume, review
presets and profile stepping remain pending. Validation and packaging are recorded in the current HANDOFF.md release entry.

Current GUI checklist: docs/GUI_STATUS.md. Architecture step 1 completed on
September 24: profiling harness and Example_Project baseline, without production
algorithm changes. Next: benchmark optional cached/spatial access; preserve
source indices, exact counts and invalidation. See PERFORMANCE_BASELINE_2026-09-24.md.

September 24: optional GUI section cache implemented and validated (450 full
suite, 37 final focused tests; six real managed-cache/full-scan comparisons).
See SECTION_CACHE_GUI.md. Viewer caching, section stepping, presets, compact
layout and in-app build identity remain separate pending work.
