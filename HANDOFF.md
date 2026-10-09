# pyArgus development handoff — October 9, 2026

This public branch backs up the locally validated application state from
source commit `b30cd69be67b374ce9a798476754e9ace6d468ed`. It is based on the
existing public main history, rather than the development history that also
contains private client records. Application code is copied unchanged.
Private project notes, job scripts and unaudited binary manuals are retained
locally and excluded from this snapshot. See docs/BACKUP_STATUS.md.

## Current delivery

- Review / Process / Deliver workspace, grouped layers, shared importer,
  active source/result versions, per-file stage tracking and clear next actions.
- 3D CPU and optional OpenGL viewing, red/cyan anaglyph, imported DXF linework,
  bounded local-detail refinement, optional spatial caches and visible fallback.
- Cross-section extraction/editing and stepping, draggable corridors,
  line-following sections, named camera views, issue notes and Resume Review.
- Original/result comparison and offline review-package export.
- Whole-cloud and tiled ground classification, known-noise preservation,
  optional elevation screening, sequential flight batches and CPU tile workers.
- QA reports, trajectory attachment, constrained alignment, terrain, contours
  and image colorization through existing shared jobs.
- Pinned Windows dependencies, frozen-runtime self-tests and installer tooling.

The locally retained October 8 Windows installer passed installation,
relocation, CPU/GPU rendering and two-worker classification checks. This public
source branch does not include the local installer or training payload.

## Evidence and boundaries

Recorded validation: 586 source tests with no skips and 73 field-reference
checks passed. The application modules here match that local state; packaging
and documentation provenance must still be checked when building a new binary.

OpenGL was exercised on an NVIDIA RTX A4000 under Windows 11. Synthetic redraw
medians improved 4.80x in normal mode and 5.40x in anaglyph. Two-worker synthetic
morphology improved 1.93x, excluding source I/O. These are scoped measurements,
not promises for cold network loads, other GPUs or all projects.

The display remains bounded to approximately 150,000 points. CPU/Tk readback,
metadata and file access still matter. Tile budgets are conservative admission
estimates, not hard process-RSS limits; native work can delay cancellation.
Batch restart/resume is not implemented. QA and alignment are not newly
parallelized, and project alignment still requires in-memory arrays.

Processing completion is not acceptance. Ground fractions and solver residuals
do not establish accuracy. Inspect sections and withheld checkpoints, record
units/methods/exclusions, and preserve original data and review decisions.

## Next priorities

1. Exercise the delivered review, comparison and export workflow on a
   representative operator project; record unresolved usability findings.
2. Validate OpenGL on AMD/Intel and compare CPU/GPU behavior on the same scene.
3. Measure loading, cache access, compute and redraw separately before choosing
   additional optimization or larger display samples.
4. Add safe batch restart/resume and consistent input-version handling for
   additional stages, with explicit completion and stale-state evidence.
5. Continue independent accuracy acceptance and terrain/breakline workflows
   toward the long-term end-to-end product objective.

## Contributor process

Read CLAUDE.md and the current guides. Use an independent environment; keep
other checkouts and client datasets unchanged. Run heavy checks serially.
Validate algorithm changes with the affected synthetic tests and the separate
field-reference gate where available. Record unavailable or skipped checks;
never silently replace a field acceptance with a source-only pass.

The public branch intentionally excludes private history. Do not merge or push
an older private branch to recover records into this public repository. Build
new distributable packages from an audited public source tree and separately
review the included documentation, training material and source archives.
