# QA review and cross-sections

Launch the GUI from this worktree's environment (`python -m pyargus gui`).
In Data, select **QA review / cross-sections…**.

## Review a job

1. Open the QA or alignment `.job-<id>.json` beside its output file/folder.
2. Read the before/after measures, skipped control and trajectory counts.
   Amber rows need investigation. The editable 0.25 default is in the job's
   map units; it is a review aid, not a project accuracy specification.
3. Switch to Clouds and cross-sections. Original and corrected files are
   listed separately with full paths. Missing or changed recorded files
   cannot be loaded as if they were the original job inputs.

The workspace supports schema-1 single-cloud and project QA/alignment job
records. Older HTML-only reports need a new tracked run; HTML is not parsed.
Project QA may read trajectory counts from the associated inventory.json,
and labels this secondary source. Aggregate strip flags do not locate an
individual bad overlap cell. Solver-only records have no independent QA.

## Inspect a section

1. Select clouds with Ctrl/Shift, confirm shared XYZ units/vertical datum,
   then Load selected clouds. LAS files must declare the same projected CRS.
   Standalone inspection is available through Add LAS/LAZ.
2. Click A then B in the plan view, or enter exact endpoint coordinates.
   Set the **full** corridor width in map units and click Extract section.
   The arrow points from A to B; station starts at A. Cross-track is positive
   to the left of that direction. Endpoints and corridor edges are included.
3. Compare elevation against station. Dataset colors distinguish original
   (cyan) and corrected (orange). Switch to Flight line or Classification;
   enter a LAS line ID to filter the displayed sample. Reused line IDs remain
   separate file/line groups. The eight flight-line colors repeat.
4. Wheel zooms, right-drag pans, and Fit views resets. Vertical exaggeration
   affects only the section display, never coordinates. Layer selection
   toggles already-loaded files without rescanning.
5. Export sample CSV saves XYZ, station, cross-track, class, LAS line ID,
   source path and zero-based source point index. Its JSON companion records
   the cut, CRS, source identities and matched/displayed counts. A new name
   is required. Export includes the whole section sample, irrespective of
   current visibility or line filters; it does not modify a LAS file.

## Scale and limitations

The plan preview contains at most 100,000 regularly sampled points. A section
scans the full selected files in 250,000-point chunks, independently of that
preview. Exact finite-coordinate corridor counts are retained. Deterministic
uniform priority samples per file cap the GUI section display near 100,000
points across selected layers. Small comparison layers retain their own
allocation. Display filters run after sampling, so absence in a filtered view
is not proof that a class/line has no points. Empty sections are reported.

Loading and extraction run in background workers with elapsed time and Stop.
Sources are checked for size/time changes during loading and extraction.
These checks are not cryptographic content identity. LAS/LAZ scans can still
take time on a network drive; this first version has no spatial index.
There is no automatic reprojection, registration, point editing, or acceptance
certification. It is a read-only review tool. Survey accuracy still requires
appropriate independent checks.
