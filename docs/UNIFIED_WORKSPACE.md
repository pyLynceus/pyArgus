# Unified desktop workspace

Current delivered/pending checklist: [GUI status](GUI_STATUS.md).

The main window has one Project files sidebar, a central 3D viewer, and a
Task panel on the right. The lower dock contains Progress/history, Project
settings, QA/cross-sections, and Log. Drag the dividers to resize the viewer
and dock. Processing uses the existing shared stage and project functions.

## Start a project

1. Click **Add files** once to choose LAS/LAZ clouds and TRJ/SBET trajectories.
   Clouds display automatically. Trajectories are registered as project inputs
   immediately, even before a coordinate confirmation or time-base selection.
   Control CSV, DXF/GeoJSON breaklines and ASC surfaces use the same importer.
2. Select trajectory rows in the sidebar and click **Settings**. Set their time
   base and, where required, GPS week and verified frame/attitude conventions.
   The sidebar identifies trajectories that still need their time base. A
   configured clock is not a claim that matching or alignment has passed.
3. Choose **Inspect / match** in the Task panel, check its project scope, and
   run it. Review Matching results in Project settings. Choose Strip QA or
   Align next, and provide a new output folder in the Task panel. Project CRS,
   vertical datum, point limits and alignment options remain in Settings.
4. Choose Classify, DTM / DSM, Contours, Above ground or Colorize for a
   **Selected cloud** task. Select that cloud in the sidebar; its name appears
   above the task settings. Classify additionally supports Entire project for
   sequential batches; the other listed operations remain single-cloud tools.
   QA and Align also offer an explicit Selected cloud scope. They never
   silently fall back from project processing to a single input.
5. Double-click a file to show or hide it. A filled circle means displayed;
   an empty circle means hidden or not yet loaded. Trajectory display still
   requires frame/vertical confirmation. Right-click provides fit, remove,
   add folder, legacy analysis-project load/save, output import and delivery
   selection. Removing a file changes project references, not the source file.

Project alignment retains its existing in-memory point limit. The new GUI
does not turn existing algorithms into whole-project batch implementations.

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
  use the same 3D camera. Sidebar visibility and class/LAS-line filters change
  visibility without rereading. File/line identities remain distinct.
- Shift-click picks a displayed point and reports XYZ, class, source line
  and file. It is a sampled point, not a fitted ground measurement.
- Refine view scans all loaded clouds within the current orthographic view
  footprint and retains a bounded uniform sample. It runs in the background
  with cancellation; zoom alone does not automatically scan a network drive.
  Reset detail restores the overview. There is no spatial index yet.
- In Top view, Ctrl-click A then B to place a section. In QA / cross-sections,
  set full width and Extract section. It scans full files using the previously
  implemented bounded section extractor. The only 2D inspection plot is the
  station/elevation section; there is no second plan/cloud viewer.
- Add control CSVs with explicit column order or DXF/GeoJSON breaklines in
  Project files. Double-click overlays them after frame confirmation.
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
analysis inputs and can be loaded from the Project files context menu.

The workspace references source data; it does not copy or edit it. Source
datasets and the other Claude checkout are unaffected. Validation uses
independent synthetic fixtures and packaged GUI smoke checks. No new real-data
accuracy claim follows from the interface changes.

## Per-input classification review — September 23

Classification history retains a current attempt for each input cloud and
stage implementation. Accept/Needs review acts on the selected history row;
newer attempts for the same cloud supersede older ones. Choosing another
input or output filename does not invalidate ground-classification parameters.
Actual parameter changes, source/output changes and upstream reruns still do.
Downstream dependencies include every current classification attempt, not just
the last flight. The stage summary reports accepted/recorded input counts;
this is not a claim that every project flight has been processed. The history
shows cloud filenames, source paths and explicit reasons for stale results.
Successful ground classification now promotes its result as described below;
other processing stages do not yet share the full version-promotion model.

## Active processing versions — September 23

A successful Classify run now promotes its new cloud into the project's input
list for that flight and displays the active project inputs. The original
stays in the sidebar as a Retained version; Active input labels identify what
project QA/alignment will read. Trajectory bindings move with the active
version. Failed/cancelled runs do not promote outputs. Activation does not
accept classification quality or independent accuracy.

Right-click one cloud and choose Use this version for processing to switch
back. Showing retained files for comparison does not re-add them to project
inputs. Explicit Section source selection remains separate. Old workspaces
recover source/result links only from unambiguous completed classification
records with matching file metadata; their active inputs do not change on
load. Unrelated imported clouds are not grouped by filename guesses.

Re-inspecting promoted outputs no longer invalidates completed ground
classification when its original input and parameters remain unchanged.
Input/output changes still invalidate it. Classification reruns on derived
versions share the same flight's review history. Busy viewer loads queue the
new active display until the current load finishes.

Validation: full suite 426 passed, followed by 42 review/workspace/editor
checks and 23 final workspace checks. Numerical algorithms were unchanged;
the previous 73/73 reference result remains the numerical baseline.

## Noise screening and sequential classification

Classify now supports Entire project. Choose a Batch output parent; each
active input gets a unique output and separate review attempt. Existing
noise classes are preserved and excluded from ground fitting. Optional
elevation limits are explicit project settings, not automatic detection.
See [Noise and batch workflow](NOISE_AND_BATCH.md) for steps and limitations.

## Optional section cache

Cross-sections now offer Build section cache, Use cache when available and
Clear all section caches. Builds are explicit; selective queries reuse valid
local data and other queries fall back to a full scan. See
[section cache workflow](SECTION_CACHE_GUI.md).
