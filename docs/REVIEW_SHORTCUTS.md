# Project context and review shortcuts

The project strip remains visible in Review, Process and Deliver. It shows the
workspace name and directory, the processing input, and the loaded cloud's CRS
and axis units. Project details shows full paths and registered version history.
The directory is the workspace's location; it is not inferred from whichever
input happens to be selected. Missing version history is labeled unknown rather
than inferred from names such as `_ground`. A horizontal CRS alone does not
establish a vertical datum.

## Quick class filters

Click All, Ground (2), Vegetation (3/4/5), Buildings (6), or Noise (7/18).
These filter the viewer sample immediately. Custom accepts a named group or
comma-separated class numbers, for example `2,6,9`; LAS line filtering remains
available there. Existing LAS line filters still apply alongside class filters.
The selection saves with the workspace. These controls do not classify points,
select processing input classes, or change the section source.

## Solo and Compare

Select a loaded cloud row in Layers and click Solo to hide the other clouds.
Select two or more loaded cloud rows using Ctrl/Shift, then Compare to show
those clouds with dataset colors. The sidebar identifies the colors; the palette
repeats after eight files. Stereo uses grayscale, so switch stereo off to compare
by color. Restore returns to the visibility and coloring before the first
Solo/Compare action. A changed loaded-file list invalidates that restore.

These actions keep the camera, project inputs, reference linework and explicit
section source intact. They do not perform alignment or compute differences.
Selecting a cloud row retains the existing behavior of setting the processing
input; the Solo/Compare buttons themselves do not change it. Clouds must already
be loaded; the buttons do not start an unexpected file scan.

## Compact sections

Source, full corridor width, Extract and stepping controls remain visible.
Following a DXF line retains station, span, spacing and Previous/Next controls.
Open Section options for endpoint coordinates, display settings, local cache
maintenance, classification editing and CSV export. Collapsing options preserves
those values and the extracted section. Standalone review retains its full layout.

Visibility and class filters affect the main viewer only. Choose the section
source explicitly; they do not silently redefine extraction inputs.

For draggable corridors and layout presets, see [review navigation](REVIEW_NAVIGATION.md).
