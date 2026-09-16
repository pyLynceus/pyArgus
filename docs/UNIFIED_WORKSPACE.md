# Unified desktop workspace

The main window now embeds the 3D viewer. Project inputs, progress/history,
QA/sections, and layers/deliverables are docks below it; drag the divider to
resize. The former raster preview is no longer a main viewer. Numerical
processing still uses the existing shared stage and project functions.

## Start a project

1. Open Project inputs / matching. Add multiple LAS/LAZ and TRJ/SBET files or
   load an existing project JSON. Set clock, CRS, vertical and binding options.
2. Load project clouds into the embedded viewer. Overlay project tracks uses
   the existing explicit trajectory-frame/vertical prompts.
3. Run Inspect / match, then project QA. The progress tracker records each
   attempt, source file identities, settings, output paths, elapsed time and
   available QA/alignment job records. There is one processing runner.
4. Select a stage to inspect its attempts and details. Load selected result
   opens available clouds and QA records. For single-cloud classification,
   surfaces or colorization, select a layer and Use cloud for processing.
   Those algorithms are not converted to whole-project batch processing by
   this GUI change. Project alignment retains its current array limit.

## Progress and review

Stages are Inspect, Initial QA, Classification, Alignment, Surface, Contours,
Colorization, Final QA and Delivery. Select Initial QA or Final QA before a
QA run. Successful processing means Needs review. Accept and Needs review
require a note. Optional steps may be explicitly skipped with a reason.
Imported artifacts without a verified job history remain Unverified import.
Historical attempts and decisions are retained rather than overwritten.

Outdated is computed from input/output size and modification time, current
stage settings, and upstream attempt IDs. It is conservative: even a repeated
upstream run can invalidate dependent work. It is not a content hash or a
proof of accuracy. Upstream dependencies guide review, rather than preventing
legitimate work on already classified/imported data. Skipping or accepting is
a recorded user decision, not an independent accuracy certificate.

The top summary shows the next unresolved stage and last completed action.
The job panel retains running/finished/cancelled/failed status and elapsed
time. If a previous session ended while running, the attempt reopens as
unverified, never as successfully completed. Select deliverables records the
chosen files for review; it does not transmit or publish them.

## 3D and section tools

- Left drag orbits; right drag pans; wheel zooms. Presets and Fit selected
  use the same 3D camera. File checkboxes and class/LAS-line filters change
  visibility without rereading. File/line identities remain distinct.
- Shift-click picks a displayed point and reports XYZ, class, source line
  and file. It is a sampled point, not a fitted ground measurement.
- Refine view scans all loaded clouds within the current orthographic view
  footprint and retains a bounded uniform sample. It runs in the background
  with cancellation; zoom alone does not automatically scan a network drive.
  Whole project restores the overview. There is no spatial index yet.
- In Top view, Ctrl-click A then B to place a section. In QA / cross-sections,
  set full width and Extract section. It scans full files using the previously
  implemented bounded section extractor. The only 2D inspection plot is the
  station/elevation section; there is no second plan/cloud viewer.
- Add control CSVs with explicit column order or DXF/GeoJSON breaklines in
  Layers / deliverables. Show selected overlays them after frame confirmation.
  Generated ASC surfaces can be sampled as green 3D overlays on a loaded cloud.
  Surface/control/breakline overlays are visual context, not transformations.

## Save and reopen

Save workspace as writes an `.argus.json` document containing project settings,
layers, processing settings, active cloud, job history, review notes, camera,
file visibility and section definitions. The initial autosave location is
`%LOCALAPPDATA%/pyArgus-Codex/last-workspace.json`. Resume last explicitly reads
that session. Autosave occurs at job transitions, periodically and on close.
Open workspace restores referenced clouds when available. Overlay coordinates
still require explicit confirmation; controls, breaklines and trajectories
remain listed even if not drawn yet. Existing project JSONs remain separate
analysis inputs and are loaded in the Project inputs dock.

The workspace references source data; it does not copy or edit it. Source
datasets and the other Claude checkout are unaffected. Validation uses
independent synthetic fixtures and packaged GUI smoke checks. No new real-data
accuracy claim follows from the interface changes.
