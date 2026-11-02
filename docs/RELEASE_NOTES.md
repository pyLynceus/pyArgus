# pyArgus release notes

## 0.2.0 review-fix Windows build - October 22, 2026

The newest Windows executable includes the combined backend reliability and
GUI integration repairs. Source acceptance: 783 passes, one Linux-only skip;
reference acceptance: 73/73. Frozen/relocated GPU, multicore, PDAL and Geoid18
checks passed. The complete source/recipe payload passes the release-content
gate. Installer lifecycle testing remains pending; existing installations are
unchanged. See [build acceptance](WINDOWS_REVIEW_BUILD_20261022.md).

## 0.2.0 — October 16, 2026

This development release brings the Review / Process / Deliver desktop,
LP360 job processing and alignment reporting under a consistent version.
The application title, Help > About this build, the `pyargus --version`
command of a source or Arch install, Windows executable properties, installer
and job records identify version 0.2.0. The frozen Windows executable has no
command line beyond `--self-test`.

### Included capabilities

- LP360 project discovery and a recorded inspect-to-export workflow, with
  explicit missing-file, coordinate-system, trajectory-clock and control choices.
- Polygon cleanup with full-resolution class/height selection, undo/redo,
  verified new-cloud export and dependent-product staleness.
- Automatic project/LP360 alignment reports with before/after overlap,
  optional survey checks, per-flight inspection, maps and downloadable evidence.
- Measured occupied-cell flight-line overlap and conservative coverage maps.
- Missing terrain cells remain missing through ASCII reload, DXF and contours.
- Review / Process / Deliver navigation, DXF reference linework, saved views,
  issue notes, original/result comparison and offline review packages.
- Optional OpenGL viewing and red/cyan stereo with CPU fallback; bounded
  multicore tiled ground classification and sequential flight batches.

### Accuracy and processing boundaries

Processing completion and a software version do not certify survey accuracy.
Review ground classification, overlaps and independent check shots. Control
used in a fit must remain distinct from checks used only for evaluation;
repeatedly examined development checks are not a fresh blind acceptance set.
Other-surface accuracy is unassessed without suitable independent checks.

The desktop sample remains bounded. Project alignment still has an in-memory
point limit; the large-project QA engine is disk-backed. Deep scan-geometry
investigations and bespoke large-project adjustment experiments remain separate
from the standard GUI workflow. Batch restart/resume is not implemented.
No numerical processing algorithm is changed by the version-label update.

### Build and verification

Portable application: `dist/0.2.0-2026-10-16/pyArgus/`.
Installer: `dist-installer/0.2.0-2026-10-16/`.
A later 0.2.0 build, `0.2.0-control-coverage-2026-10-19` (portable folder,
installer and the Arch package `0.2.0-archlinux-control-coverage-2026-10-19`),
adds the control-coverage audit; see `CONTROL_COVERAGE.md` beside that installer.
Neither 0.2.0 payload passes the October 21 release-content gate described in
WINDOWS_INSTALLER.md. The 16 October payload's `Sources/pyArgus-source.zip`
contains internal working notes (HANDOFF.md and CODEX_WORKTREE.md, with client
names and server paths): do not distribute that installer further, and if it
has already left this workstation, send its recipients the next build, whose
source archive excludes those files. The 19 October archive is clean. Keep the
entire portable folder together, including `_internal` and `native-pdal`.
See the adjacent build information, payload manifest and release verification
for exact source identity, dependency reuse and completed validation.
Existing installations and older dated releases are retained.
