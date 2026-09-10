# SH 151 (Keystone Dam, OK) — lidar-vs-control workup

2026-09-08, revised 2026-09-10. Fixed-wing corridor job, 22 strips in
3 flights (F1 west corridor, F2 northeast segment, F3 = F1 corridor
reflown 5.4 h later), OK North ftUS + NAVD88, GPS seconds-of-week
time. Control, checkpoints and the OSSDA shots were all observed by
Frontier Land Survey in OK State Plane North / Geoid 18. Client
symptom: imagery AT tight, control misses the lidar inconsistently
above and below. Workup scripts: `reference/sh151_gather.py` (per-
strip near-mark cache), `reference/sh151_report.py` (the per-strip
decomposition) and `reference/sh151_cross_sensor.py` (the two-sensor
adjudication). Z: read-only throughout.

## The verdict in one line

**The lidar block is rigid, the misses are position-locked at
individual marks, and an independent sensor over the same marks says
the marks are right** — so the error is in the delivered lidar, and
its shape points at the vendor's LCP2 adjustment.

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
   "trends", impossible for real trajectory drift). In the step-3
   table the per-mark spread across strips is 0.005–0.050 ft at every
   problem mark: the block does not disagree with itself.
4. **Population A — slope/vegetation marks**: the biggest positives
   sit on 11–27% slope faces; a lowest-returns surface collapses
   several (200202 +0.48 → +0.06; 80813 +0.24 → −0.03). Lidar is
   reading vegetation above the mark: a checking-method artifact.
   These are excluded from the step-3 adjudication.
5. **Population B — flat hard-surface offsets that persist**:
   grade-corrected plane fits leave 200203 +0.225, 200205 +0.219,
   80806 −0.218, 200223 −0.171, 80805 −0.152, 80809 −0.150 and
   others. Clean marks at the same grades read ±0.01. The field flips
   sign within 300–2,000 ft along one road, far too jumpy for a geoid
   or datum story.
6. **The AT DOES adjudicate Population B, and it clears the marks.**
   *(This corrects the original finding, which claimed the opposite.)*
   In `rtesults.txt` the resX and resY columns are 0.000 by
   MEASUREMENT PROCEDURE — the stereo operator navigates to the
   mark's known planimetric position and reads height there — so
   resZ is a photogrammetric-minus-surveyed height difference at the
   mark. 58 of the 65 marks carry a nonzero one; only 7 are the
   constrained-looking zeros the original workup generalised from.
   Their mean is −0.002 ft, so the imagery carries no systematic
   vertical bias against this network.

   Over the 49 marks that have an AT check and sit under 8% grade,
   the lidar misses by more than 0.10 ft at 16. At **14 of those 16
   the imagery lands within its own 0.11 ft noise of the surveyed
   elevation** while the lidar is out by 0.10–0.23 ft. Where the
   lidar is clean (33 marks) the imagery agrees at 26. Two sensors
   over one control network, and only one disagrees with the ground
   survey.

   The test is on MAGNITUDE only: the sign convention of resZ is not
   documented in the report and cannot be recovered from the data
   (the signed correlation between the sensors is ~0 at every grade
   band — which is itself informative, since it means their errors
   are independent rather than sharing a common mark error).
7. **Two marks need re-observation**: 80806 (lidar −0.218, imagery
   0.207 off) and 80822 (lidar +0.120, imagery 0.127 off). Both
   sensors miss these, which is the signature of the mark itself.
8. **A third population repeats the pattern**: sh151.xlsx
   "Deviations" (60 shots, names 731xxxxx/802xxxxx/819xxxxx) shows
   the same mark-local ±0.5 ft mixed-sign field.
9. **There is also a corridor-scale TILT, and it is a separate
   question.** Over the 13,700 ft span the lidar-minus-survey field
   carries +0.143 ft/mile east and −0.056 ft/mile north (correlation
   with easting +0.59); removing it drops the rms from 0.101 to
   0.078 ft, with the mark-local residuals of finding 6 as the
   remainder. **The imagery cannot adjudicate this component**: the
   AT is adjusted TO these marks, so it would absorb a tilt in the
   network itself and its own near-flatness proves nothing about one.
   A geoid-model difference between the survey (GEOID18, per the
   client) and the vendor's processing is a live explanation, which
   is why the geoid question is worth more than a formality.

## What this leaves

**The vendor's LCP2 adjustment is the remaining explanation.** The
strip filenames carry `_LCP2_` — the delivered strips are already
warped to a lidar control point set. A wrong LCP value bends every
strip identically at that location, which is exactly the observed
signature: rigid inter-strip agreement, repeatable local misses, sign
flips between nearby control points — and now, independent imagery
that confirms the surveyed elevations the warped lidar misses.

A systemic survey bust is no longer a live suspect for Population B:
it would have to have missed the same marks in a way the
photogrammetry, tied to the same network, does not see.

Read the misfit as TWO components, because they have different
answers. The mark-local part (finding 6) is settled: the imagery
confirms the marks, so the delivered lidar is wrong there. The
corridor tilt (finding 9) is not settled and the imagery cannot
settle it — it is either part of the same warp or a geoid-model
difference, and the vendor's answer on the geoid decides which.

## Recommended next actions

1. **Ask ADS for the LCP2 control list and adjustment report**, and
   state the finding rather than the question: the imagery confirms
   the surveyed elevations at the marks their delivered lidar misses,
   so the warp is the thing to examine. Compare their LCP values near
   200203, 200205, 200223, 80805, 80809, 80814, 80817, 80818.
2. **Request the PRE-adjustment (pre-LCP2) strips.** The raw block's
   internal consistency suggests it may need only a bias shift, or
   nothing; `pyargus align` can verify the unadjusted block and the
   gather/report scripts rerun against any strip set.
3. **Re-occupy 80806 and 80822** — the only two marks the evidence
   actually impeaches.
4. Vegetated/slope marks: check with a lowest-surface rule or
   re-shoot on hard surface; they should not be quoted against the
   delivery as-is.
