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
The only exceptions were the owner's, on 2026-09-25 and 2026-09-28
(below). Since then the Codex branch sits on the old, unpublished
history: bring its work over by cherry-pick, never by merge.

## Public repository, private job material

github.com/pyLynceus/pyArgus is PUBLIC. Client job material -- job
logs, job scripts, client file names, control coordinates, a job's
results -- does not belong here. It lives in the private local
repository `pyArgus-jobs` (on the OneDrive Desktop beside this
checkout, with no remote). Reference code here stays generic
(`reference/grid_compare.py`, `reference/mark_profile.py`) and the job
scripts import it; test fixtures use invented values, never real ones
shifted by a constant. A local pre-push hook (`.git/hooks/pre-push`,
not versioned) refuses a push that would carry such material in text
files or commit messages; it cannot see inside a DOCX or PDF, so check
binary documents by hand. The Summerville and SH 151 material predates
this rule and stays public by the owner's decision.

By the owner's decision the public history was rewritten twice. On
2026-09-25 an unsent draft letter was purged from it, and the unpushed
work since the last public commit was published as a single commit so
that no client job detail rode along in older versions of files or in
commit messages. On 2026-09-28 a second client job, public since
2026-09-09, was removed from every commit. The detailed history is
kept locally only (branches `private/full-history-2026-09-25` and
`private/pre-purge-2026-09-28`, and bundles in
`pyArgus-jobs`). Commit ids cited in documents from before 2026-09-28,
including release source commits, exist only there.

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
