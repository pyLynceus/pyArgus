# Original/result comparison

Open **View > Original / result comparison > Prepare / choose pair**, or
the **Version comparison** tab in the Review pane. The toolbar **Compare**
menu exposes the same commands.

## Prepare a pair

1. Load a cloud and wait for the viewer to finish.
2. Choose **Original** and **Result**. **Use recorded lineage** selects a
   recorded descendant of the selected processing cloud when one exists.
   Use **Browse** for a manual comparison, including results from other software.
3. Confirm that both files use the same XYZ units and vertical datum. Matching
   horizontal CRS tags alone do not establish matching vertical datums.
4. Click **Prepare comparison**. The viewer samples the two files once, or
   reuses an already loaded pair with current source identities. It keeps the
   current camera, filters, stereo settings, section location and overlays.
5. Click **Original**, **Result** or **Both**. In Review mode, **F6** switches
   Original/Result when focus is outside a text-entry control. The toolbar
   shows the current role. For Both, choose **Color > Dataset** to distinguish
   the clouds, or keep Classification to compare class assignments.

Switching uses the prepared samples; it does not scan the LAS records again.
Preparation disables Auto detail to keep comparison switches predictable.
Explicit Refine view remains available. Use the ordinary class and line
filters for inspection; an unclassified Original may disappear under Ground.
The notice explains when the selected version has no sampled points under
the current filters.

Only the comparison pair is loaded for this review. **Restore previous
display** restores the preceding bounded cloud sample, camera, filters,
visibility, stereo, overlays and existing section sample without rescanning.
That temporary display backup is available only in the current session.

## Compare a cross-section

1. Define a section corridor with the existing section tools.
2. Click **Extract comparison section**. Extraction reads both files explicitly
   using the existing cache or scan path. Stop remains available.
3. Click **Show cross-section**. Use **Layout > 3D + Profile** if helpful.
4. Switch Original/Result/Both. Both displays the two profile samples on a common
   scale; switching preserves profile zoom and pan and reuses the same section.

Counts describe the extracted corridor before display filters. The profile
has its own existing color and line controls. A previous single-cloud profile
is cleared when it does not describe the prepared pair. Moving the corridor
requires a new explicit extraction for that location. Editing classifications
still requires a complete single-cloud section; a paired review sample is
not an editing source. Section export retains both sampled inputs regardless
of the current Original/Result display selection.

## Provenance and saved workspaces

The panel shows full paths and **Recorded lineage** or **Manual pair —
relationship not verified**. Recorded lineage currently covers the cloud
versions recorded by classification. Other processing results can be chosen
manually. Filenames and point counts are never used to infer a relationship.
Successful recorded jobs and their source/output size/mtime signatures are
checked. Manual selection establishes only an explicit viewing pair.

Comparison requires distinct, nonempty LAS/LAZ files with declared matching
projected CRS, matching axis units and a frame compatible with the current
viewer references. It does not reproject or infer a vertical datum. Missing
or changed sources and concurrent jobs/loads are refused. Source checks are
metadata checks, not cryptographic validation of every point record.

Pair selections, confirmation, display role and review-only cloud registration
are saved in the workspace. Reopening requires **Prepare comparison** again
before using the switches; it verifies the current sources. Profile samples
and the previous-display backup are not serialized or extracted automatically.

Comparisons preserve processing inputs, selected task input, trajectory
bindings, stage decisions and source files. A manually browsed file is marked
**Review only** until explicitly added or promoted for processing. Reviewing
a result does not accept a stage or establish survey accuracy. Differences
are inspected visually; numerical difference maps and accuracy assessment
remain separate QA operations.
