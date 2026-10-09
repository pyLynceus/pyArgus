# Saved views, issue markers and Resume Review

Use the **Review** dropdown above the viewer. **Review notes** opens a panel
with saved views on the left and issues on the right. It is also under
**View → Review notes / saved views**. These tools organize review; they do
not run processing stages or certify accuracy.

## Save and return to a view

1. Position the cloud, choose the display filters and stereo setting, and set
   a section or DXF route if needed.
2. Choose **Review → Save current view…**, name the location, and press Enter.
3. Return through **Review → Saved views → name**, or double-click a saved
   view in Review notes. **Replace** records the current context under that
   existing name; **Rename** changes its name; **Delete** removes the bookmark.

A view saves the loaded LAS/LAZ paths and their identities, camera, cloud
visibility, color/class/line filters, stereo settings, section definition,
explicit Section source and comparison confirmation, followed route, profile
display settings, DXF visibility and review layout. Camera pan is recorded in
map units so resizing the viewer preserves the viewed center. It stores no
full cloud arrays or profile samples. Returning restores the definition; use
**Extract section** when you need a fresh profile. Auto detail is turned off
on return so review resumption does not start an implicit detail scan.

Returning can load the recorded LAS files when the viewer has different clouds
loaded. The processing project/version selection and task parameters remain
independent of this viewing action. Reference DXF layers must already be
registered in the same workspace. Trajectory, control and surface overlays
use their existing loading tools; bookmarks do not reconstruct those overlays.

## Record an issue

Choose **Review → Place issue on point**, then click a displayed point. This
creates an issue and opens its title, type, status and note. Press **Apply note**
to save edits. The pick uses the current display sample and retains its source
file, XYZ, class and line ID. It is not a survey measurement or a digitized
breakline. Escape cancels placement. Point placement requires normal viewing;
turn stereo off first.

**Issue at view center** places an approximate pin at the center of the visible
camera plane, including its pan. This is useful in stereo. The record explicitly
labels its location `view-center`; its height is not inferred from the terrain.

Pins show open issues in coral, issues under review in amber, and resolved
issues in green when **Resolved pins** is enabled. In stereo, markers are
grayscale points rendered separately for each eye; return to normal viewing to
pick them. Click a normal-view pin to open its note. Double-click an issue row
or use **Go to issue** to restore its original view. **Next open issue** cycles
through unresolved records. **Resolve** and **Reopen** record operator decisions
and leave the cloud classification and processing-stage approvals intact.

## Resume Review

The workspace records the last valid position in Review mode during normal
saves, autosave and close. Entering Process or Deliver keeps that checkpoint.
Choose **Review → Resume Review** or **File → Resume Review** to return to it.
From a fresh session, Resume Review can open the last workspace and return to
its checkpoint. It restores viewing/section context and starts no QA, alignment,
classification or section-extraction job. Loading the recorded display clouds
may take time. Older workspaces open normally; they gain a checkpoint after a
cloud has been reviewed and the workspace saved.

Saved positions use file size and modification time, matching the existing
project provenance mechanism. Missing/changed clouds or reference files make
a position unavailable. Removed/reimported references also require reopening
the recorded workspace. Returning is refused before applying a stale context;
old notes remain readable. Pins are hidden when their recorded data context
differs from the loaded cloud identities/frame. This metadata check does not
cryptographically prove content identity if both size and timestamps are kept.

Notes/bookmarks/checkpoints live in `review_notes` inside the `.argus.json`
workspace. **Export notes…** writes a separate JSON file containing notes,
locations, saved camera contexts and source identities for handoff. It cannot
overwrite the workspace or registered source files. The export is a review
record, not a point-cloud deliverable or a numerical QA report.

Validated with synthetic LAS/DXF data, GUI regression tests and the frozen
application smoke test. Review on a representative project remains the next operator
check for comfortable pin placement and returning between locations.
