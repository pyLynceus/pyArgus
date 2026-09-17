# SH151 trajectory inventory and adjustment screening

This supersedes the earlier uncertainty about whether SH151 SBETs exist.
All paths below are under `Z:/Users/BJordan/SH 151/LIDAR/TERRAFLIGHT`.

## Confirmed inputs

| LAS group | Matching trajectory in SBET/ | Record count | GPS week-second interval |
|---|---|---:|---|
| F1 (5 strips) | sbet_Mission 1.out | 1,226,569 | 60261.004494–66394.002043 |
| F2 (15 strips) | sbet_Mission 1 (1).out | 1,241,964 | 66894.002012–73104.004275 |
| F3 (2 strips) | sbet_Mission 1 (2).out | 557,584 | 82381.001870–85169.001351 |

All three files have strictly increasing time at approximately 200 Hz.
Three corresponding `smrmsg*.out` uncertainty files are present; their contents
were not decoded in this pass. A flight report is also present in SBET/.

Seven blocks of 1,000 points were sampled throughout each of 22 LAS files.
Every sampled point's GPS week seconds matched one trajectory within 0.1 s,
with no overlap among the three SBET time intervals. Geographic positions
were transformed to EPSG6553 as a coarse location check; sampled median
horizontal aircraft-to-return distances were 186–427 ft, consistent with
project vicinity but not a lever-arm, datum, timing or boresight validation.
This was sampling, NOT a full 917-million-point association audit. Absolute
SBET acquisition week still needs confirmation from provenance/flight records.

`LAS/22_files_from_ADS_Reprocess.zip` contains exactly 22 processed LAS entries
whose names and uncompressed sizes match the extracted LAS files. Archive
contents were listed, not extracted or byte-compared. It contains no raw laser
measurements, trajectory project or calibration package.

The recursive SH151 inventory found no raw laser range/encoder measurements,
raw GNSS/IMU observations, or lidar-specific lever-arm/boresight calibration.
The supplied `.cam` file is the IMAGE camera calibration, not lidar calibration.
Thus full regeneration from raw sensor data is not currently supported by the
supplied directory. SBET-informed adjustment of delivered XYZ remains possible.

## Screening actually run

`sh151_trajectory_fit.py` read existing local strip caches and surveyed
checkpoint elevations, fitted enclosing local planes, and screened for at
least 12 returns, <=8% slope, <=0.05-ft plane RMS, at least two strips per
mark and <=0.10-ft interstrip elevation spread. Smoothness is not proof of
bare ground; these are provisional references, not newly validated control.

52 marks / 161 strip-mark observations survived. Each mark carries equal total
weight regardless of its number of strips. Five spatial folds keep all
observations of a mark together. Results:

| Model | Weighted spatial cross-validation RMS (ft) |
|---|---:|
| No correction | 0.100773 |
| One vertical offset per flight | 0.099566 |
| Offset + linear time trend per flight | 0.099051 |

Three test observations in each fitted model lacked mission support in their
training fold. The reported score includes those fallback predictions and
is NOT a fully supported validation score. Improvement is marginal even
before resolving that problem. No correction was accepted or applied.

This was a regression screening, not trajectory reprocessing or a boresight
solve. It used point times from caches with flight groups linked to the SBET
inventory; it did NOT use attitude, uncertainty or aircraft-to-return vectors
as fit variables. Cached source freshness was not revalidated here.

## Next work for Claude Code

1. Treat these SBET files as available SH151 inputs. Do not reuse UAS SBETs.
2. Confirm source provenance, GPS week, time convention, coordinate/vertical
   references and SBET frame/origin; decode uncertainty records and flight report.
3. Recheck cache/source freshness and full LAS-to-SBET timestamp coverage.
4. Consider a constrained strip-geometry adjustment with overlap tie surfaces
   and spatially reserved control. Determine parameter observability before
   introducing roll/pitch/heading, timing or horizontal shifts. Delivered XYZ
   already includes vendor adjustments; don't describe inverse calculations
   as recovery of original raw ranges/angles.
5. Compare any candidate against withheld controls and strip overlaps first.
   The independent stereo geometry remains unresolved; high image correlation
   alone is not a valid release check.

No source files, trajectories, or LAS points were changed. All outputs are
inventory and diagnostics. `inventory.json` contains sampled associations,
standard LAS dimensions and archive listing. `control_fit_screening.json`
contains per-mark inputs and model results. Standalone scripts are included.
