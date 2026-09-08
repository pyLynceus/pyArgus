# HANDOFF

Updated 2026-09-08, at the initial scaffold.

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

## What is NOT yet validated

Everything above is proven only against synthetic geometry. In
particular the frame and sign conventions in `core.georef` and the
field interpretation in `formats.sbet` are internally consistent but
have never touched a real TrueView 660 flight. Given that two vendor
angle conventions have already been wrong in this workflow (see
CLAUDE.md), treat that boundary as the current risk.

## Next step, with reasoning

**Phase 0: choose the reference dataset.** One real TrueView 660
project -- strips with point_source_id assigned, the SBET, surveyed
checkpoints, ideally the imagery too. First acts once it lands:

1. `pyargus sbet-info` on the real SBET; confirm rate, span, altitude
   read sensibly.
2. Read one strip, run `qa.density`, compare against LP360's density
   report for the same file. Agreement validates the LAS path.
3. Run `qa.overlap.strip_dz` on one overlapping pair and
   `qa.checkpoints` against the surveyed control, and compare with what
   LP360/TerraSolid-era QA said about the same project. That comparison
   is the acceptance test for all of Phase 2.

Only after those three agree does Phase 3 (ground classification)
start. PDAL is not yet a dependency; it arrives with Phase 3, and on
Windows likely via conda-forge or a pinned wheel -- decide then, not
now.

## Findings so far

* OneDrive refuses uv's hardlinks (os error 396). Rebuild the
  environment with `UV_LINK_MODE=copy uv pip install -e ".[dev]"` or
  the install dies mid-wheel.
