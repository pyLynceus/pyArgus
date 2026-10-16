# LP360 job shortcut

Use **LP360 job…** in the Layers sidebar or File menu. Choose the project root,
check the discovered inputs, then click **Run LP360 job**. The original LP360
files remain untouched. Each run creates its own timestamped folder under
`<project root>/pyArgus_jobs`, or your selected output parent.

The Files and readiness page lists the source LAS folder, trajectories,
control, EO and imagery. When more than one flight folder or control CSV exists,
choose the intended input. Missing or ambiguous requirements stay on this
screen with Browse controls. You can explicitly disable alignment or continue
without survey control. Recoloring is optional; existing RGB is preserved by
default. Missing EO does not block an existing-color cloud workflow.

Discovery recognizes `Cycle_*/Flight_*/LAS`, `Trajectories/*.trj`, POS `sbet*.out`,
System `eo_Photos*.csv`, camera `.cal` files and CSVs named for control/GCPs,
checkpoints or Allpts. It prefers flight LAS folders over root-derived clouds.
It excludes pyArgus output directories, records, logs, POSPac processing trees,
build/dist folders and directory links. `smrmsg.out` is not treated as an SBET.
Multiple flight folders require a choice; the newest folder is not presumed
correct. Manual LAS and trajectory selection handles alternate layouts.

LAS tags supply units and coordinate-system information. A horizontal CRS alone
does not establish Z units/datum: enter a verified declaration and confirm common
XYZ units/vertical datum when needed. TRJ time-base suggestions use actual stored
point/trajectory timestamps; file dates do not define the GPS week. LAS week-time
inputs require the verified week. Final matching scans the complete cloud and
refuses alignment with unmatched or ambiguous returns. It does not extrapolate
trajectories to repair missing coverage.

The recorded sequence is:

1. Inventory and full trajectory matching.
2. Exact baseline QA, including control comparison when supplied.
3. Ground classification of each flight, using tiled CPU processing.
4. Exact ground QA across the block.
5. Relative vertical strip adjustment, if enabled. Attitudes are unused;
   the first strip remains fixed. Survey marks are used for QA, not fitted.
6. Recoloring from EO/imagery/calibration, if explicitly enabled.
7. Combined class-2 mean DTM and supported grid-triangle DXF surface.
8. Contours from the published ASCII elevations, without smoothing or gap fill.
9. Final exact QA against the resulting clouds and supplied control.
10. SHA256-verified separate final flight files and an export manifest.

Lengths on Processing settings use the LAS XYZ units. The suggested feet profile
uses cell 3, window 60, threshold 1.5, alignment cell 6 and contour interval 1.
The meter profile uses cell 1, window 18, threshold 0.5, alignment cell 2 and
contour interval 0.25. Review these parameters for the terrain and required
products. The array limit still applies to alignment; large blocks need a
smaller selection or an explicit RAM-appropriate limit. The surface-cell guard
and output-space estimate refuse oversized jobs rather than silently sampling.

Existing noise classes 7/18 remain noise. Optional low/high Z limits are explicit
operator settings; the shortcut does not infer noise thresholds or automatically
apply manual cleanup. Elevated structures or vegetation can still require review.

The result folder contains `report.html`, `run.json`, `project.argus.json`, native
per-attempt records, stage outputs and `final_clouds/manifest.json`. The GUI loads
the new workspace when the full sequence completes. Every completed stage is
**Needs review**, or explicitly **Skipped**; automatic processing never records
an accuracy approval. Review actual overlap/control maps before using products.

Stop is cooperative. Running native operations may need to return before stopping.
Completed stages and a failure/cancellation record remain available. A failed
stage stops downstream processing and does not claim a final deliverable. This
first shortcut starts a new run; it does not resume a partial run automatically.
Neither pyLynceus jobs nor other existing workspaces are rewritten.


## Missing surface coverage (October 13 repair)

The ASCII surface uses its declared `NODATA_value` for empty ground cells.
The workflow restores the original empty-cell mask after reading those published
heights: DXF triangles and contour squares require four populated corners, and
contour levels use only populated elevations. No terrain is created across gaps.
Populated heights still use the published three-decimal ASCII values.

The October 12 shortcut did not restore that mask. Its surface DXF, grid cache
and populated-cell summary can consequently contain missing-data markers as
terrain. Regenerate those products with the October 13 build; existing output
folders are retained rather than silently rewritten. An already correct ASCII
nodata declaration is unaffected. The shortcut still starts a new run, rather
than automatically resuming a failed run.

A real low/high ground outlier can still trigger the 1000-contour-level guard.
Review the classified cloud or use explicit noise limits appropriate to the
project before regenerating products. The missing-data repair does not change
point classifications, remove measured returns or automatically choose those
limits.

## Measured coverage overlap

All new native QA stages include directional strip coverage percentages and
a map of one, two, or three-plus strip coverage. Known noise 7/18 is excluded
from this coverage measurement. Planned sidelap and ground-height differences
remain separate. See [COVERAGE_OVERLAP.md](COVERAGE_OVERLAP.md) for denominators,
exact CSVs, map resolution and review limits. Large QA scratch preflight now
allows 256 bytes per input return plus 64 MiB.
