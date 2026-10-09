# Section handles and review layouts

The embedded viewer has three layouts in **Layout** (also **View → Layout
presets**):

| Layout | Arrangement |
| --- | --- |
| Full 3D | The viewer fills the review workspace. |
| 3D + Profile | Viewer above a compact cross-section panel. |
| Comparison review | Viewer and profile with Dataset colors to distinguish clouds. |

Presets leave the camera, processing inputs, visible clouds and Section source
unchanged. They arrange the Review workspace and collapse advanced section
options. Comparison coloring changes the viewer/profile display only; it does
not load clouds, extract a section, calculate alignment or approve a result.
Stereo uses grayscale. Choose explicit comparison inputs under Section source
and confirm their units and vertical datum before extracting.

## Moving a section with the mouse

1. Load the clouds. Choose the required **Section source** in Cross-section.
2. Choose **Sections → Edit corridor handles (Top view)**, or **Edit corridor**
   beside Extract section. This opens the panel, turns stereo off and selects
   Top view. If there is no corridor, it places one at the view center.
3. Drag inside the corridor or its **Move** handle to translate it. Drag **A**
   or **B** to change its endpoints, **W** to change its full width, or **R**
   to rotate it about its center. W is offset slightly from the edge to keep
   narrow corridors easy to select.
4. Release to apply the definition. The previous profile is cleared when the
   geometry changes. Click **Extract section** to refresh it.

**Extract on release** is optional and defaults off. When enabled, releasing
a changed corridor uses the normal extraction path and its cache, source and
provenance checks. Without a valid explicit source the drag is refused. A cache
miss can scan the source files, so leave it off while positioning a corridor.

Escape during a drag cancels the preview and retains the previous definition,
profile and route. Escape again turns handles off. Panning, zooming, changing
orientation or opening another panel cancels an active preview. You can still
orbit outside the corridor, pan with the right mouse button, and zoom with the
wheel. Handles appear only in normal Top view, including a rotated Top view;
they do not operate in stereo or while a scan is running. Double-clicking a
handle does not fit the cloud. Shift-click point inspection and Ctrl-click A/B
remain available.

Committing a mouse adjustment leaves any followed DXF route and switches to
manual A/B sections. Cancelling leaves the route intact. This manipulates the
section selection only; it does not edit cloud points or reference linework.

The workspace saves the layout, split ratio and Extract on release preference.
Unsaved drag previews are not recorded, including by autosave. Reopening does
not extract a section, and handles start disabled. Profile samples are still
bounded by the existing extraction/display limits. Numerical processing and
classification engines have not changed.

Validated with synthetic LAS/DXF data and GUI regression tests. Operator review
on a representative project remains useful for checking comfortable handle placement,
profile size and repeated section movement with actual project data.

Saved camera views, issue pins and Resume Review are documented in [review memory](REVIEW_MEMORY.md).
