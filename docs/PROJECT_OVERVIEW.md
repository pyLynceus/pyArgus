# Project overview and workflow status

Open **View > Project overview / status**, or click **Project status** above
the sidebar locator. The main cloud viewer remains the only cloud viewer.
The map is an orientation aid drawn from LAS/LAZ header rectangles.

## Map controls

- Click within a loaded cloud rectangle to center the current 3D view there.
  Rotation, zoom, stereo and coloring stay as they are. Camera history supports
  Previous view. Processing inputs, stage decisions and section source stay unchanged.
- Select a cloud row, then **Center selected** or **Fit selected extent**.
  Fitting uses the full header XYZ range, which can include isolated noise.
- **Load selected cloud** explicitly loads just that cloud through the normal
  viewer. This can scan points and resets the profile/overlays as normal loading
  does. A plain map click never starts a load or section extraction.
- Solid rectangles are visible loaded clouds; dashed rectangles are hidden or
  not loaded. Each coordinate group has its own map. Undeclared, geographic or
  incompatible CRS are not combined or reprojected.
- White outlines approximate the current view on the horizontal plane at the
  camera-center height. Edge-on views have no finite plane outline. The white
  cross marks the approximate visible camera-plane center. Yellow is the
  section corridor; coral circles are available unresolved issues in that CRS.
- The **Map** checkbox collapses the sidebar locator. This preference and the
  coordinate group are saved in the workspace. Camera movement updates the
  locator even when the Project overview tab is hidden.

## Header inventory

Header reads run on a background thread and never read/decompress point records.
Size/mtime identifies cached headers. **Refresh headers** rechecks metadata and
reuses headers only when that identity is unchanged. The panel shows when headers
were checked and reports unreadable/empty files. Metadata identity is not a
content hash. EVLR payloads are not loaded: a CRS stored only there is reported
as unmapped rather than silently assumed. No extra files are written to the dataset.

Rectangles are bounding boxes, not surveyed outlines, occupied coverage, density
maps or accuracy evidence. They may include noise, empty space and outdated
vendor bounds. Map navigation requires a matching loaded CRS and source
identity. A changed header after refresh requires a cloud reload. Header totals
are recorded point counts, not validation of the LAS contents or trajectories.

## Status and next action

The sidebar now shows a compact current-action message and button. Detailed
stage evidence lives in Project overview and Job history. The overview shows:

- Active processing clouds and trajectories, selected task input, loaded/visible
  review clouds, unset trajectory clocks and header/map warnings.
- Accepted/skipped recorded stage decisions, unresolved issues, and current
  statuses including Needs review, Failed, Cancelled and Outdated.
- Ground-run coverage for each active input lineage, including promoted results.
  Above-ground classification does not count as a ground run. An accepted run for
  one cloud does not imply all current project inputs were processed; missing
  coverage is labelled partial. Coverage is based on recorded attempts, not a
  fresh count of class-2 points. Explicitly skipped Classification remains skipped.
- Current section source and whether a profile has actually been extracted.

The action button prepares the next task/settings or opens the appropriate
review history. It never runs processing, accepts work, resolves an issue or
extracts a section. Click a stage in Stage evidence to inspect its history.
Stage acceptance and issue resolution are operator review decisions, not an
accuracy certification. Existing job provenance and stale-result rules apply.

## Validation

Header-only/cache tests prohibit point reads; geometry tests check large
coordinates and the inverse camera-plane projection. GUI tests check navigation
without scans or input changes, busy/stale/CRS refusals, partial ground coverage,
workspace preferences, obsolete worker-result rejection and compact layout.
Actual 1600 × 950 and 1400 × 900 layouts are checked with synthetic LAS data.
Numerical processing modules are unchanged.
