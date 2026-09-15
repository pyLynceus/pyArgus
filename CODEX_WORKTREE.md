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

