# Manual classification editing

Open the QA / cross-sections workspace with one cloud loaded. In the main 3D
Top view, Ctrl-click A and B, set the corridor's full width, and extract the
section. Choose **Edit classifications…**.

The editor requires exactly one input and every corridor point to be present.
If extraction sampled the corridor, shorten or narrow it and extract again.
This first iteration does not edit a sampled cloud or multiple files.

1. Choose Rectangle and click two corners, or Polygon and click its vertices,
   then Finish polygon. White points show the exact selection count.
2. Selection is in station/elevation and includes the entire declared corridor
   width. All classes and flight lines are shown in the editor, independently
   of the review pane's display filters. Pan and zoom do not alter selection.
3. Enter a LAS classification code and Assign. The supported range depends on
   the point format (0–31 for legacy formats, 0–255 for newer formats).
4. Undo and Redo work within this session. A new assignment clears redo.
5. Export LAS/LAZ to a new filename. This writes the entire source cloud with
   only the intended classifications changed, not just the section.
6. Add the output file to the main viewer and inspect it with Classification
   coloring before accepting it. To edit another section cumulatively, load
   the exported cloud and extract the next section from that output.

## Preservation and evidence

Source point indices, not screen pixel IDs, drive changes. The source's size
and modification time are checked against the extraction identity. Every output
point record is reread and hashed against the expected edited records. Coordinate
integers, other dimensions and classification flags must match. Schema, scale,
offset, CRS, VLRs (excluding compression transport metadata) and EVLRs are
verified; original extra-dimension statistics are retained.

The adjacent `.edits.json` records each changed source index and its before/after
class, operation history, section definition and record hashes. This is a new
standalone edit record, not yet an integrated workspace-tracker stage. Undo is
in memory; the sidecar is an audit trail, not a resumable editing project.

Export is cancellable and publishes only after verification. Existing paths are
never overwritten. Exceptions remove this attempt's temporary outputs. The LAS
and sidecar are two filesystem publications, not a crash-atomic pair: a process
or machine failure can leave a temporary file or only one published artifact.
Keep the verified sidecar with the output. Source identity is metadata-based,
not protection against an adversarial same-size/same-timestamp replacement.

Waveform formats and COPC inputs are refused because they require a dedicated
preservation/reindexing workflow. Undo history is capped at five million stored
point changes. Windows uses exclusive same-directory rename for publication, including on
OneDrive/network folders; the POSIX fallback requires hard-link support.

## Validation boundary

Synthetic tests cover inclusive selection, full-corridor depth, sampled-section
refusal, undo/redo branching, legacy class limits, LAS and LAZ round trips,
classification flags, extra dimensions, VLR/EVLR preservation, cancellation,
source changes, deliberately corrupted output, and the editor GUI.

The recorded Summerville source path was unavailable during implementation.
A real-data edit/export/reopen acceptance check remains pending; synthetic
record preservation does not establish the correctness of an operator's class
choices. Direct 3D lasso selection, multifile edits, persistent sessions, class
filters, and integrated workflow-tracker updates remain future work.
