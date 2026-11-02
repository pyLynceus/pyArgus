# Flightline diagnostics

Flightline diagnostics reads existing LAS/LAZ files and creates a new report.
It does not solve an adjustment, fit survey control, change classifications,
write a cloud, or promote a candidate to the active processing version.

## Desktop

1. Add the baseline clouds to the current project. In Project / trajectory
   settings, declare the common XYZ units and vertical reference and configure
   any trajectories and clock settings. Without trajectories, LAS source line
   IDs are the flight identities. Repeated IDs across separate files require
   a genuine shared-flight namespace declaration; do not make that declaration
   merely to bypass an identity conflict.
2. Choose **Tools > Flightline diagnostics…**. It uses **all current project
   clouds**, regardless of the selected layer or viewer visibility.
3. Review the ground-cell settings. All length settings in this dialog are US
   survey feet and convert to the declared cloud units. Defaults: 6-foot cells,
   at least 6 ground returns per flight/cell, maximum plane RMS 0.08 ft,
   maximum slope 0.25 rise/run, review threshold 0.10 ft, and at least 12
   qualified shared cells for a supported flight-pair relationship. These are
   editable investigation settings, not survey standards or acceptance limits.
4. Optionally choose a **saved candidate project JSON** referencing an already
   processed dataset. Its CRS must equal the baseline CRS. Matching uses LAS
   line identity plus canonical trajectory path; the operator must establish
   that those represent the same physical flights. The tool does not prove
   candidate lineage, transform datums, or adjust one dataset to the other.
5. Choose a new report folder and click **Run flightline diagnostics**. Stop is
   available in this dialog and the main status bar. Closing the settings
   dialog leaves an active job running and the main Stop control available.
6. Open the report from Deliver / Job history. Select baseline/candidate and
   a flight pair; clicking a pair-table row selects its map. Hover over a
   displayed difference cell for its coordinates and signed difference.

The source preview launcher in `build/eyewitness-theme-20261027/` loads this
feature. An older installed executable does not acquire source changes until
rebuilt. A completed diagnostic run is recorded under **Initial QA**, with mode
`diagnostics`; it never marks **Alignment** complete or replaces active clouds.
Settings persist with the workspace.

## Command line

Run from the checkout with its own environment:

```powershell
& ./.venv/Scripts/python.exe -X utf8 -m pyargus.cli flightline-diagnostics baseline.project.json --out D:/work/job/diagnostics_01
```

To compare an existing candidate:

```powershell
& ./.venv/Scripts/python.exe -X utf8 -m pyargus.cli flightline-diagnostics baseline.project.json --candidate-project candidate.project.json --out D:/work/job/diagnostics_compare_01
```

Options: `--cell-ft`, `--min-points`, `--max-scatter-ft`, `--max-slope`,
`--tolerance-ft`, and `--min-cells`. Output folders cannot be reused.

## What is measured

Coverage uses occupied, world-aligned, half-open XY cells. Known noise classes
7 and 18 do not contribute. Each cell receives contributions across all input
chunks before reduction. The map shows actual observed multiplicity per displayed
cell, distinguishing one, two, and three-or-more analysis flights. It can be
sampled; full counts remain in CSV. This is not planned flight sidelap.

Height assessment uses **class 2 only**. An unclassified dataset can therefore
have observed coverage without any available ground-height comparison. Missing
support stays unavailable; it is not zero disagreement.

For each flight/cell, the engine retains an exact raw-Z median and evaluates an
ordinary least-squares ground plane at the cell center. The plane uses local
coordinates and a shared vertical origin to reduce survey-coordinate precision
loss. A qualified plane requires sufficient returns, returns in all four
quadrants around the center, full rank, design condition no greater than 30,
and scatter and slope below the selected limits. Rejected cells retain their
counts, available metrics, and reasons. Classification or surface identity is
not independently verified.

The pair residual is **height(B) minus height(A)**. Summaries include median,
RMS, NMAD, P95 absolute difference, and the number beyond the review threshold.
Each qualified cell has equal weight. These are surface-difference statistics,
not independent observations, confidence intervals, or checkpoint accuracy.
Pair finding text classifies support, median and RMS. Inspect the separate
exceeding-cell count for rare large differences even when those summary metrics
stay below the threshold. A bounded map sample can omit a localized difference;
the complete cell CSV and exceeding count retain it. No finding is approval.
Raw cell medians are preserved separately; unequal sampling on slopes can make
raw median differences disagree even when the two local planes coincide.

A vertical translation shared by every flight cancels in B-minus-A. Control
fit can therefore improve while inter-flight differences remain unchanged;
this report does not substitute for the survey-location residual reports.

No direct horizontal offset or feature-edge agreement is estimated. Horizontal
misregistration can create height residuals on slopes; flat pavement alone does
not constrain an XY translation. These maps do not distinguish those causes.

A pair needs the selected minimum number of qualified shared cells to connect
two flights in the support graph. Disconnected components and flights with no
supported neighbors remain explicit. A connected graph does not establish
geometric calibration or survey accuracy.

Spatial trends are descriptive OLS fits to the qualified cell residuals, with
an isotropically normalized footprint and a condition gate. They are unavailable
for too few or degenerate cell locations. Reported gradients are cloud height
units per 1000 US survey feet east/north. A trend is not a diagnosis of roll,
pitch, lever arm, GNSS drift, datum, or any other physical cause, and is never
applied to points.

## Candidate comparison

Each dataset retains its own coverage and qualification statistics. The common
comparison uses only **identical world cells and matching flight pairs qualified
in both states**. It reports before and after statistics on precisely that
common population; the underlying point observations can differ. Unsupported
comparisons remain null. Baseline-only and candidate-only flights remain in
separate inventories, rather than silently disappearing from the report.

## Survey locations

Optional locations come from the baseline project's Alignment report settings:
the reference Control / PID CSV and the reporting check CSV. Declared independent
checks that duplicate or lie within the report radius of a reference location
are flagged as role conflicts. All locations, including uncovered ones, remain
visible in the evidence.

This diagnostic only asks which flights have a **qualified ground cell at the
location**. It does not establish support around the physical target, measure
cloud-minus-survey residuals, fit control, or establish independent accuracy.
The center of a supported cell and a target elsewhere within that cell are not
interchangeable. Use the existing alignment/checkpoint reports for their stated
local-target measurements. Candidate location interpretation assumes the same
declared vertical reference.

## Files and provenance

Keep the output folder together:

- `report.html`: self-contained interactive maps/data with adjacent download links.
- `diagnostics.json`: method, settings, native units, complete inventories,
  source identities, graph, pair statistics, trends, map samples, and limitations.
- `baseline.project.json` and optional `candidate.project.json`: exact run settings.
- Each dataset folder: `flightlines.csv`, `pairs.csv`, `surface_cells.csv`,
  `overlap_cells.csv`, and `coverage_cells.csv` with complete cell evidence.
- `common_cells.csv`: every paired baseline/candidate residual when requested.

A schema-1 per-attempt job record is written beside the report folder. Survey
CSVs are content hashed. Large LAS and trajectory identities use metadata;
this is not a cryptographic proof of every original byte. Inputs are rechecked
before exclusive publication. Failed/cancelled work does not publish a partial
report. A publication collision preserves the existing destination and retains
the complete staged report at the recovery path in the error/job record.

## Resource and validation scope

Point input is chunked (up to 500,000 records); exact medians and reductions use
SQLite disk scratch. Cache allowance is 32 MiB per dataset, with two databases
for comparisons. This is not a measured whole-process RSS bound; trajectories,
input arrays, sorting and rendering add costs. Choose an output drive with
ample scratch space. Ingest stops if less than 256 MiB free remains; SQL scratch
can still fail separately if its temporary storage fills. At most 128 analysis
flights are admitted. Maps use deterministic bounded samples; CSVs/statistics
use all accepted cells.

Synthetic validation includes known offsets, unequal sampling on slopes,
rough/one-sided/absent ground, large survey coordinates, unit conversion,
common-cell comparisons, disconnected flights, input changes, cancellation,
publication races, CLI use, and actual native Tk routing/lifecycle. The example
under `build/flightline-diagnostics-20261027/demo/report-final/` is synthetic.
It is not a Example_Project result, survey acceptance, or a vendor regeneration.

## Validation — October 27, 2026 feature (UTC October 28)

62 focused tests passed. The combined current-source gate passed dependency
checks and 813 tests, with one Linux-specific X11 ownership test skipped on
Windows. All 73 unchanged real-data reference checks passed. Raw runner status
is `needs_skip_review`; the X11 skip was explicitly reviewed as outside the
Windows scope, and is not Linux validation. No environment warnings or source
changes occurred during the gate. Canonical source: `cf604b3201126f59646f7fc49ac5aad36f2a8e2a320530a1bc374922983f11d4`.
Evidence: `reference/reports/validation-20261028T032721Z-53020/validation.json`.

Headless browser checks passed at three widths with no JavaScript errors.
The synthetic example maps and screenshots were reviewed; live Windows/DPI
operator acceptance remains pending. The installed binary was not rebuilt.
