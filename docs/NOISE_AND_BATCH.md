# Noise handling and batch ground classification

## GUI workflow

1. Add the clouds and confirm the active input versions in Project files.
2. Choose **Classify**, then **Entire project** to process all active project clouds.
3. Set Cell, Slope, Window and Threshold once for the batch.
4. Leave **Noise min Z** and **Noise max Z** blank unless you have established
   valid elevation limits for this project. Values use the source LAS elevation
   units. Points below the minimum become class 7; above the maximum, class 18.
5. Choose an existing **Batch output parent**, then Run Classify.
6. Review each flight under Progress / history. Successful execution leaves
   the classification **Needs review**, not accepted automatically.

The batch creates a unique subfolder, numbered output filenames, batch.json,
and an individual classification job record per executed flight. Duplicate
input basenames cannot overwrite one another. Inputs are snapshotted at batch
start; each successful output replaces its source as that flight's active
processing version. Original files are retained unchanged.

Selected cloud remains the default scope for a single-file run, which uses
Classified cloud out. Entire project uses Batch output parent instead.

## Noise policy

Existing low/high-noise classes 7 and 18 remain unchanged and cannot seed the
SMRF surface or become ground. This applies to whole-cloud and tiled drivers,
including --any-return. Explicit elevation screening is applied before fitting
and during output labeling. Points exactly at a limit remain eligible.
Blank limits preserve known noise only: they do not discover untagged outliers.
This is not a general statistical or neighborhood-based noise detector.

Example CLI options: `classify-ground ... --noise-min 100 --noise-max 500`.
Choose limits from verified project units and terrain bounds; these example
values are not recommendations for any project.

## Failure, memory and review

Flights run sequentially. Stop or a failed flight stops the batch; completed
outputs and their review records survive, and remaining flights are not run.
The manifest records each item's status. Automatic resume after restarting the
application is not implemented. A process crash can leave a Running manifest;
inspect the individual records and outputs before starting another batch.

The GUI uses the whole-cloud classifier for each flight. Sequential execution
avoids loading all flights together, but a single large flight must still fit
memory. The CLI tiled driver remains available for larger inputs.

Neither a completed batch nor the proportion labeled ground establishes
accuracy. Review representative sections, noise, walls, vegetation and overlap
before accepting classification or proceeding to alignment and surfaces.
