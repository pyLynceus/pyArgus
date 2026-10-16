# Automatic alignment comparison reports

Every new **multi-file project alignment** and enabled **LP360 alignment** now
writes one `report.html` in its alignment output folder. A new run requires a
new output folder; earlier reports and original clouds remain preserved.

The report combines the existing before/after QA with the exported corrections,
input identities, saved settings, optional survey comparisons, and interactive
check-location/error plots. Follow **Before QA and maps** or **After QA and maps**
for density, coverage and ground-difference maps.

## Setup in the GUI

1. Open **Tools > Alignment report settings…**. This selects the **Alignment
   report** tab in project settings. In the LP360 setup dialog, use its own
   **Alignment report** tab.
2. Optionally choose a survey CSV and its explicit column order: `pnez` means
   point ID, northing, easting, elevation; `penz` means ID, easting, northing,
   elevation. The file has no header; additional description columns are allowed.
3. Choose **reference** or **independent**. Select independent only for survey
   observations withheld from fitting and earlier adjustments of these clouds.
   These reporting checks never enter pyArgus's alignment solve. Checks within
   the report radius of supplied fitting-control XY are excluded from summary
   accuracy statistics and remain individually visible.
4. Choose the surface category: **pavement**, **other_ground**, or **unspecified**.
   A single report check set uses one category; do not combine pavement and other
   ground under one tolerance. Add an optional material description if known.
5. Default tolerances are +/-0.10 US survey ft for pavement and +/-0.50 US survey
   ft for other ground. Neighborhood radius defaults to 2 US survey ft with
   at least 8 class-2 returns. Length settings convert into the declared cloud
   units. An unspecified surface receives no tolerance assessment.
6. Run **Align project**, or run the LP360 job with alignment enabled. In
   **Deliver**, select the resulting report and click **Open selected report**;
   double-clicking a report opens it too. The LP360 job's **Open results** page
   links to `alignment/report.html` in its Alignment stage row.

Settings persist with saved projects and workspaces. A review note is not required.
If LP360 has an existing Control CSV but no separate report-check CSV, it is
included as a **reference**, with surface unspecified. It is not silently
reclassified as independent check evidence or fitted as alignment control.

## What the numbers mean

- Solver patch RMS describes the fitting observations. It is not an independent
  accuracy result.
- Flight-pair QA uses ground-cell medians from each state's existing QA report.
  Before and after cell sets can differ, especially after boresight changes XY.
  Both counts are shown; these are not advertised as the same cell samples.
- Survey comparisons fit an ordinary least-squares local ground plane, centered
  at surveyed XY. The point must lie inside its ground-return convex hull. The
  scaled plane-design condition must not exceed 30. Sparse, collinear and
  one-sided neighborhoods remain unavailable with a reason.
- Merged and per-flight observations remain available. Merged before/after
  summary statistics use the same IDs supported in both states and exclude
  fitting-control neighborhoods. All input IDs remain in the table and CSV,
  including checks that cannot be assessed.
- Positive residual means cloud above survey. After values use coordinates read
  back from actual exported LAS/LAZ files, including coordinate quantization.
- Local plane scatter is not survey uncertainty, and class 2 does not establish
  the physical surface. The report preserves the declared role/material and
  identifies unavailable independent accuracy assessments.
- **Items to review** highlights higher flight-pair cell RMSE, higher paired
  checkpoint RMSE, threshold exceedances and missing support. These rules do
  not diagnose a physical cause or approve the adjustment.

## Retained evidence

The alignment folder contains:

- `report.html`: portable interactive comparison; its viewer script and data are
  embedded. Keep adjacent QA maps/folders for its download and map links.
- `alignment_comparison.json`: comparisons, settings, source identities,
  checkpoint observations and limitations.
- `checkpoint_comparison.csv` and `checkpoint_flights.csv`: every supplied check
  and each available per-flight observation.
- `overlap_comparison.csv` and `corrections.csv`: flight-pair metrics and offsets.
- `report_checkpoints.csv`: exact copy of the supplied CSV, when provided.
- `alignment.json`, `project.json`, `before/`, `after/`, and adjusted clouds.

The native per-attempt job record includes these products and the checkpoint CSV
SHA256. Changing the CSV during processing refuses publication of the run.
Cancellation or failure before publication discards the unpublished run folder.
LP360 retains earlier completed stages according to its existing workflow.

This feature covers project and LP360 alignment exports. Legacy single-cloud
`align` solve/export paths retain their existing job records; they have not been
converted to this comparison page. The deeper project scan-angle, timing,
reflectance and trajectory investigation remains a separate diagnostic workflow.
No such diagnosis is implied by this routine report. Existing reports are not
retroactively rewritten, and no fitting algorithm or automatic acceptance policy
has changed.
