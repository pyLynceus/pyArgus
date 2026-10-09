# Review / Process / Deliver workspace

The September 30 layout keeps one 3D viewer and the existing processing engines.
Use the top tabs to choose the work you are doing:

| Tab | What appears | Typical next action |
|---|---|---|
| Review | Layers, viewer, compact viewing toolbar and project progress | Import clouds or DXF; inspect stereo or a section |
| Process | The same viewer plus task settings at right | Select a task and its input scope, then Run |
| Deliver | Existing output list and export actions at right | Open an output folder or export a section/feature file |

Switching tabs preserves camera position, loaded inputs and task settings. It
does not start processing or approve a stage. Each mode remembers whether its
lower pane is open during the session. Workspace saves restore the current
mode, lower-pane visibility and selected page. Older workspaces open in Review.

## Menus and viewing

- **File**: open/save/resume workspace, add data, load/save analysis project.
- **View**: orientations, stereo, filters, fit, previous view, local detail,
  linework settings and history.
- **Tools**: processing tasks, project settings, sections, QA reports and
  optional feature tracing.
- **Help**: mouse/keyboard controls and packaged source-build identity.

The viewer toolbar keeps View, Color, Fit and Previous view directly available.
Stereo and Sections use drop-down menus. More contains display filters, Refine,
Build view cache, Reset detail and Stop loading. The toolbar wraps on narrower
windows. Auto detail retains its existing cache requirement and stays off by
default. Stereo settings control depth and eye swapping; picking requires mono.

**Review pane** opens/closes the lower area without unloading data. Its tabs are
Cross-section, QA results, Linework, Job history and Log. Project settings is
available in Process. Drag the horizontal divider to change the split. Opening
section review gives the profile additional space without resetting the camera.

## Layers and linework

**Add data** is the shared entry point for clouds/trajectories, folders,
reference DXF, control CSV, terrain breaklines, existing outputs and job records.
The sidebar groups Point clouds, Trajectories, Linework, Control and Outputs.
DXF references remain separate from processing breaklines and cloud inputs.

Select a cloud to set the processing input. Double-click a layer to toggle
visibility; right-click for its available actions. For a DXF reference, choose
fit, sections or style settings. Select the reference in the sidebar before
using the lower Linework controls. Import compatibility declarations and source
checks still apply; adding a reference does not transform the cloud.

For sections, use **Sections → Follow imported line** or draw an A/B section.
Choose the section source explicitly, then extract. Previous/Next along a route
use the existing station settings. See LINE_FOLLOWING_SECTIONS.md.

Manual tracing remains optional under **Tools → Optional feature tracing**.
Hidden tracing controls cannot capture points. Switching workflow tabs ends
the active tracing mode; existing features are retained.

## Progress and delivery

The sidebar progress list reflects actual stage status; click a stage to see
its attempts and review decisions. Changing modes or opening a file never marks
a stage accepted. The bottom status bar shows job state, elapsed time and viewer
status, with Jobs/log and Stop job available even in Review.

Deliver lists registered outputs. Section CSV exports the current sample;
traced DXF uses existing feature acceptance/provenance rules. Record selected
deliverables records the selected project files; it neither copies nor approves
them. Processing produces LAS/surface outputs as before.

This release changes navigation, not classification, alignment or surface math.
Saved camera bookmarks, issue markers, comparison presets and a consolidated
review report remain future work.
