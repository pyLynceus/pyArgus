# pyArgus

An open-source lidar production suite fitted to the TrueView 660 UAS
workflow. Sibling to pyLynceus and Plumbline, built on the same rules.

**Read `HANDOFF.md` before doing anything substantive.** It carries the
current state, what has and has not been validated against real data,
and the next step with its reasoning.

## Two checkouts, one repository

`Desktop/pyArgus` (branch `main`) is Claude's working checkout;
`OneDrive - Platinum Geomatics/pyArgus-Codex` -- one level ABOVE this
Desktop folder, not beside this checkout -- is a git worktree on
`codex/isolated-improvements` for Codex. They share `.git`, so a branch
checked out in one cannot be checked out in the other, and heavy runs
(pytest, the battery, builds) must not overlap between them. Each has
its own `.venv`; never build or validate from the other's. Merge
through `main`; never force-push or rewrite either branch's history.

## Running anything

The project has its own environment and needs it:

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

After any substantive change to qa/, align/, classify/, surfaces/ or
formats/, also run the acceptance battery against its recorded
numbers (needs Z: and the cached geoid grid; ~3 minutes):

```bash
.venv/Scripts/python.exe -m reference.run_all
```

A failure means behavior changed: fix it, or update the expectation
in reference/run_all.py AND the RESULTS.md entry together, never one
without the other.

To rebuild: `uv venv --python 3.11 .venv` then
`UV_LINK_MODE=copy uv pip install -e ".[dev]"` (OneDrive refuses uv's
hardlinks; without copy mode the install fails with os error 396).

## The habits this project is built on

Inherited from pyLynceus, where each was paid for:

* **Check claims against something outside the strip.** Solver
  residuals are not accuracy. An alignment result exists only when the
  post-adjustment `qa.overlap.strip_dz` maps and checkpoint residuals
  confirm it.
* **Prefer refusing to guessing.** Modules raise rather than
  extrapolate, interpolate past the data, or return a number that reads
  as meaningful and is not. Keep that property when adding code.
* **Distrust vendor angle conventions until proven.** LP360's
  Omega/Phi/Kappa columns are wrong by up to 79 degrees for this
  workflow, and ATLAS negates all three attitude angles. The convention
  in `pyargus.core.rotation` (Rz*Ry*Rx, +Z up) is the one proven for
  TrueView 660 EO in pyLynceus; validate any new data source's angles
  against known geometry before feeding them in.
* **Repeat before recording.** A number becomes "measured" after it
  survives multiple seeds and sizes, not after one confirming run.
* **The math core stays pure.** Nothing in `pyargus/core` or
  `pyargus/align` imports GUI code or optional format dependencies.

## Mechanical traps

* Two feet exist. Every unit conversion goes through
  `pyargus.core.units`, explicitly.
* SBET heading wraps at +/-pi; `formats.sbet.interpolate` handles it.
  Do not interpolate heading with a bare `np.interp` anywhere else.
