# Noise handling and batch ground classification

## GUI workflow

1. Add the clouds and confirm the active input versions in Project files.
2. Choose **Classify**, then **Entire project** to process all active project clouds.
3. Set Cell, Slope, Window and Threshold once for the batch.
4. Leave **Noise min Z** and **Noise max Z** blank unless you have established
   valid elevation limits for this project. Values use the source LAS elevation
   units. Points below the minimum become class 7; above the maximum, class 18.
   **Noise max fraction** (default 0.001, i.e. 0.1%) refuses a window that
   would flag more than that share of a cloud: that is the site, not its
   noise. Raise it only on purpose.
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

There is a second route to the same classes: `pyargus noise-cut in.las --out
flagged.las --z-min A --z-max B` flags once, as its own recorded step, and
writes a new cloud plus a `.noise.json` listing every point it flagged. Both
routes land on 7 and 18 and classification treats the result identically; the
job log reports the two separately (already flagged, screened now). The
same two refusals guard both, in the same order. A window outside the cloud's
own elevation range (from its header) refuses before a point is read, which
catches a bound from the wrong job or metres typed for a cloud in feet. A
window that would flag more than the declared fraction of the cloud refuses
before anything is classified or written: `--max-fraction` on `noise-cut`,
`--noise-max-fraction` on `classify-ground`, **Noise max fraction** in the
desktop stage and batch, each defaulting to 0.1%. Points already flagged
before the run do not count against it. The tiled driver counts on one extra
streaming pass, taken first, and refuses on the running count. For a new site,
`noise-cut` is still the better first step: it writes a `.noise.json` listing
every point the window caught, so the choice can be audited.

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
