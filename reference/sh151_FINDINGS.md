# SH 151 (Keystone Dam, OK) — lidar-vs-control workup

2026-09-08. Fixed-wing corridor job, 22 strips in 3 flights (F1 west
corridor, F2 northeast segment, F3 = F1 corridor reflown 5.4 h
later), OK North ftUS + NAVD88, GPS seconds-of-week time. Client
symptom: imagery AT tight, control misses the lidar inconsistently
above and below. Workup scripts: `reference/sh151_gather.py` (per-
strip near-mark cache) and `reference/sh151_report.py`. Z: read-only
throughout.

## The verdict in one line

**The lidar block is rigid; the disagreement is position-locked at
individual marks** — every strip and every flight reads the same
wrong value at the same mark, so this is not misalignment, not
boresight, not trajectory drift, and an adjustment run would find
nothing to fix.

## Evidence

1. **Flight-to-flight**: at shared marks, F3−F1 = +0.005 ft median
   (nmad 0.008), F2−F1 = +0.001 (0.010), F3−F2 = +0.002 (0.017).
   Same corridor, hours apart, agreement at the noise floor.
2. **Reproduction**: our merged check-shot stats match the client
   report (rms 0.140 vs 0.139; max +0.585 vs +0.586) — same
   phenomenon, independently measured, then decomposed per strip.
3. **Per-strip decomposition**: the worst marks read identically from
   every covering strip (200011: +0.72/+0.71/+0.65 across three
   strips; 80708: +0.23/+0.21/+0.24 across F1+F2+F3). Apparent
   per-strip biases and along-strip "drifts" are mark-composition
   artifacts (adjacent strips over the same ground show opposite
   "trends", impossible for real trajectory drift).
4. **Population A — slope/vegetation marks**: the biggest positives
   sit on 11–27% slope faces; a lowest-returns surface collapses
   several (200202 +0.48 → +0.06; 80813 +0.24 → −0.03). Lidar is
   reading vegetation above the mark: a checking-method artifact.
5. **Population B — flat hard-surface offsets that persist**:
   grade-corrected plane fits leave 80707 +0.294 (0.8% slope),
   200205 +0.223, 200203 +0.225, 200223 −0.172, 80806 −0.218,
   80805 −0.158. Clean marks at the same slopes read ±0.01. The
   field flips sign within 300–2,000 ft along one road (−0.22 …
   +0.02 … +0.30), far too jumpy for a geoid or datum story.
6. **The AT cannot adjudicate Population B**: at exactly the worst
   marks the AT residuals are 0.000 — those points were CONSTRAINED
   control in the aerotriangulation, so its agreement there is by
   construction, not evidence.
7. **A third population repeats the pattern**: sh151.xlsx
   "Deviations" (60 shots, names 731xxxxx/802xxxxx/819xxxxx) shows
   the same mark-local ±0.5 ft mixed-sign field.

## The two live suspects for Population B

* **The vendor's LCP2 adjustment.** The strip filenames carry
  `_LCP2_` — the delivered strips appear ALREADY warped to a lidar
  control point set. A wrong LCP value bends every strip identically
  at that location: exactly this signature (rigid inter-strip
  agreement + repeatable local misses + sign flips between nearby
  control points).
* **Survey busts at specific marks** (sessions/rod heights/
  localization) — though three independent shot populations showing
  the same style of field weakens this unless the bust is systemic.

## Recommended next actions

1. **Get the LCP2 control list and adjustment report from the
   vendor** (ADS/TerraFlight processing report). Compare their LCP
   values near 80707, 200205, 80806 against the OSSDA marks: one
   busted LCP there is the smoking gun.
2. **Re-occupy 3–5 Population-B marks** (80707, 80806, 200205,
   200223) with redundant ties — the cheapest decisive test of the
   survey side.
3. If the LCPs prove bad: request the PRE-adjustment strips. The raw
   block's internal consistency suggests it may need only a bias
   shift (or nothing) rather than a warp; `pyargus align` can verify
   the unadjusted block and the control comparison can be re-run
   as-is (the gather/report scripts are rerunnable against any strip
   set).
4. Vegetated/slope marks: check with a lowest-surface rule or
   re-shoot on hard surface; they should not be quoted against the
   delivery as-is.
