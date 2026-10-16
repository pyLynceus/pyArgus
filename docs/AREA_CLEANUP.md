# Polygon area cleanup

Included in pyArgus 0.2.0 through **Review → Cleanup…** or
**Tools → Area cleanup…**. Use the versioned portable application or installer.

## Operator workflow

1. Choose one **active processing cloud** in the cleanup window. Other overlapping
   flights are visible for context, but only the chosen cloud can be edited.
2. Click **Draw polygon**. The viewer moves to Top while retaining its center,
   zoom and pan, and turns stereo off for unambiguous XY drawing. Click plain
   left-button corners. Right-drag pans; the wheel zooms. Corner clicks do not
   orbit or fit the cloud. **Back one corner** removes the last corner.
3. Click **Finish polygon**. Set explicit source classes, an optional LAS line ID,
   and optional minimum/maximum Z. Defaults select ground class 2 at every height.
   Leave heights blank to include the entire vertical column. XYZ and height
   limits use the source CRS units. Use a higher minimum Z to isolate vegetation
   incorrectly labeled ground without changing real pavement underneath.
4. Click **Read full-resolution area**. The source is streamed by original record
   index. The count, Z range, and class counts describe all matching returns,
   independently of viewer filters or visible-point sampling. Up to 50,000
   selected points are highlighted in normal and anaglyph views as a preview.
   Review the geometry from several angles before assigning.
5. Enter a class and click **Assign**. Every return in this exact selection is
   assigned, including returns behind other points. Class 1 removes suspect
   vegetation from ground-derived products without declaring a vegetation class
   or deleting points. The supported class range follows the LAS format.
   Undo/Redo affect only the current in-memory editing session.
6. **Export verified cloud and use for processing…** to a new LAS/LAZ filename.
   The complete source is copied; every output point record and metadata are
   reread and checked. Only the intended classification bytes may change.
7. The verified file becomes the active processing version for that flight.
   Trajectory bindings follow its lineage; other flights and originals remain.
   The current camera is retained. Review this version before accepting its
   Classification attempt in Job history.
8. Read another area from the exported version for cumulative cleanup. Close the
   tool only after exporting, undoing, or explicitly discarding unsaved changes.

## Results and rebuild status

Each export writes a `.las.edits.json`/`.laz.edits.json` containing the polygon,
explicit class/line/height limits, CRS, selected count, changed record indices,
before/after classes, undo history and source/output record hashes. A native
`*.job-<id>.json` records completion, cancellation or failure. The workspace
records a Classification attempt scoped to the original flight and promotes
only a successfully verified result; the result remains **Needs review**.

The existing dependency tracker marks alignment review, surfaces, contours,
final QA and delivery **Outdated** when their classification dependency changes.
Project inspection and project QA can also become outdated because their active
input manifest changed. Accepted historical artifacts stay available.

Rebuild/review in order: current project inspect and ground QA; alignment review;
surface; contours; final QA; deliverables. Cleanup leaves XYZ unchanged, so an
old vertical-shift solution is not automatically recomputed. The operator must
review the new ground overlaps before deciding whether a new alignment solve
is necessary. This iteration shows the rebuild status; it does not implement
one-click regeneration of combined project surfaces/contours. Existing surface
GUI tasks still operate on their selected input cloud.

## Boundaries and preservation

- One source cloud per export; repeat for another overlapping flight as needed.
- The GUI refuses selections above 1,000,000 editable returns. Narrow the area or
  apply explicit height/class limits. No sampled editing fallback is allowed.
- The selection polygon is inclusive and uses the even-odd rule. Plan drawing
  requires a projected CRS and common XYZ linear units. It is not a perspective
  screen lasso. Class/line filters apply to original source labels at extraction.
- Coordinate integers, intensity, GPS time, RGB, classification flags, extra
  dimensions, CRS, scales/offsets, VLRs and EVLRs are preserved by EditSession.
  Source size/mtime are rechecked after extraction and before publication.
- Existing cloud or sidecar names are refused. Export can be cancelled before
  publication. LAS and sidecar publications are exclusive but not a crash-atomic
  two-file transaction; keep the verified sidecar with the output.
- Undo is in memory; the audit sidecar does not restore an editing session.
  A new assignment clears redo. Unsaved changes and active exports block closing
  or switching workspaces unless edits are deliberately discarded/cancelled.
- Waveform point formats and COPC inputs require a separate preservation workflow
  and are refused by the edit session. Conversion/reindexing is not automatic.

## Verification boundary

Synthetic tests cover exact record preservation, inclusive polygons and height
limits, class/line filtering, cancellation, input changes, mouse navigation,
stereo previews, source lineage and dependent-product invalidation. Ground
quality and project acceptance require separate operator review.
