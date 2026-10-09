# Features workspace

This first version creates manually traced 3D linework. It does not detect
curbs/walls automatically and does not feed breaklines into surfaces yet.

## Trace and review

1. Load the cloud you intend to trace. Use its classified/adjusted version
   deliberately; features retain that source file's metadata identity.
2. Open **Features**, enter a name and feature type, then **New line**.
3. Shift-click cloud points in order. **Append vertices** adds vertices only
   while Features is the active tab. **Finish tracing** returns to Inspect.
   Left drag continues to orbit, right drag pans and the wheel zooms.
4. Picks snap to the existing viewer's displayed points within eight pixels,
   not a full-resolution nearest-neighbor search. Use **Refine view** for
   local detail. Examine different views before accepting any line.
5. Select a vertex row to edit XYZ numerically, or choose **Replace selected
   vertex** and Shift-click its replacement. **Delete vertex** removes it.
   Source identity is retained for manual edits; their method is recorded.
6. Use **Reverse**, **Split at vertex** (interior vertices only), or select two
   features with Ctrl-click and **Join two lines**. Join connects the earlier
   list item's end to the later item's start; it does not silently reverse or
   bridge gaps intelligently. Both lines must have the same type and CRS.
7. **Undo/Redo** retains up to 100 edits for the current session. Geometry
   edits return a line to Candidate. Apply properties with status Accepted
   only after review. Acceptance is not an accuracy certification.

Candidate lines are yellow, accepted lines green, with vertices numbered on
the selected line. Overlays draw on top of the cloud (not depth-occluded).
Only features matching the loaded viewer CRS are drawn. Missing/changed
sources are flagged when a line is selected and block acceptance/export.

## Save and deliver

Features save in the normal workspace JSON, including name, type, review
status, XYZ vertices, source size/mtime identity, CRS and edit method.
Edits trigger workspace saving. Undo history and tracing mode are session-only;
opening a workspace returns to Inspect. Older workspaces open with no features.

**Export DXF** exports all accepted lines by default. Uncheck Accepted only to
include candidates; drafts with fewer than two vertices must be completed or
removed first. Each type/status gets its own layer. Coordinates remain as
stored, with no reprojection. DXF units distinguish metres, international feet
and US survey feet; other units are marked unspecified. A same-name
`.features.json` sidecar retains CRS and provenance; preserve it with the DXF.
The DXF contains each feature ID as PYARGUS extended data to associate entities
with sidecar records. Existing output/sidecar names are refused.

Publication of the DXF and JSON is not a crash-atomic two-file transaction;
ordinary write failures clean up files created by the attempt. Source identity
uses size and modification time, not a content hash. Neither source cloud nor
its classifications are edited by these tools.

## Next

Assisted extraction, profile-based vertex snapping, persistent review presets,
feature-aligned cross-section stepping and surface breakline integration remain
future work. Validate manual linework on representative wall,
barrier and pavement sections before advancing to automated extraction.
