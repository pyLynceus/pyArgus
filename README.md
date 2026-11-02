# pyArgus

An open-source lidar production suite fitted to a Leica/LP360 TrueView
660 UAS workflow: strip QA, strip alignment, classification, surfaces,
and deliverables. Sibling to pyLynceus (photogrammetry) and Plumbline
(block QA).

The strategy: assemble the solved parts (PDAL, laspy, COPC, GDAL,
startin cover ingest, ground filtering, gridding, surfacing) and build
the one missing part -- rigorous least-squares strip adjustment, the
TerraMatch capability with no open equivalent. That custom core is
Phase 4; the QA that referees it ships first.

## Current version

**pyArgus 0.2.0 — October 16, 2026.** See the [release notes](docs/RELEASE_NOTES.md)
for capabilities, limitations and build locations. Help > About this build and
Windows executable properties show the application version.
The newest Windows package is the October 22 review-fix build; see
[its acceptance and installation scope](docs/WINDOWS_REVIEW_BUILD_20261022.md).

## Arch Linux / WSL

A native **0.2.0-2** Arch Linux x86_64 package was built, installed and tested
on October 19, 2026. Launch the installed WSL application with
`wsl -d archlinux -u builder --exec pyargus-gui` from Windows, or
`pyargus-gui` inside Arch. See [Linux installation and build instructions](docs/LINUX_ARCH.md).
The package, portable archive, checksums and verification are retained under
`dist-installer/0.2.0-archlinux-control-coverage-2026-10-19/`. This build was qualified on Arch
WSL2/WSLg; other Linux distributions have not been tested.

## Control / PID coverage audit

New project and LP360 alignments include a control-coverage map, separate fitting /
reference / independent counts, rejected locations and advisory geometry/gap
warnings. Open **Tools > Alignment report settings > Control coverage** to select
reference PIDs and edit the planning thresholds. Audit-only PIDs never enter the
solve. See [Control coverage instructions](docs/CONTROL_COVERAGE.md).

## LP360 job shortcut

Use **LP360 job…** in the sidebar or File menu to discover project inputs,
resolve missing files/settings, and run the recorded QA-to-export sequence.
See [LP360 job instructions](docs/LP360_JOBS.md).

## Polygon cleanup in the review viewer

Use **Cleanup…** or **Tools → Area cleanup…** to draw a Top-view polygon,
read its complete source returns, review with explicit class/height limits,
reclassify with undo/redo, and export a verified new processing version.
The workflow tracker marks dependent products outdated. See
[Area cleanup instructions](docs/AREA_CLEANUP.md). This feature is included in version 0.2.0.

## Layout

    pyargus/core      pure math: units, rotation conventions, the
                      direct-georeferencing forward model
    pyargus/formats   SBET trajectories, control CSVs, LAS/LAZ (laspy,
                      optional)
    pyargus/qa        density, strip-overlap dZ, checkpoint stats, and
                      the one-command strip-QA report (PNG + world-file
                      rasters, no GDAL)
    pyargus/align     the strip-adjustment core: planar-patch
                      correspondences + robust Gauss-Newton for boresight
                      and per-strip offsets; refuses indeterminate
                      geometry; attaches real SBETs through pyproj
                      (optional [crs] extra) with the vertical datum
                      always explicit
    pyargus/classify  in-core SMRF ground classification (no PDAL: it has
                      no Windows wheel; same algorithm, ~150 lines of
                      numpy/scipy)
    pyargus/surfaces  DTM/DSM gridding + ESRI ASCII export, TIN with
                      soft breaklines, marching-squares contours out to
                      DXF (R12) and GeoJSON
    pyargus/formats   LAS/LAZ (whole, streamed, or COPC-queried),
                      SBET/TerraScan trajectories, control, EO, DXF
    pyargus/imagery   RGB colorization from oriented imagery: the
                      LP360/pyLynceus EO bridge, an Agisoft-native
                      calibrated camera, occlusion refereed by the
                      cloud itself (optional [imagery] extra)

The commands:

    pyargus qa-report cloud.las --out qa/ \
      --control marks.csv --control-order pnez --sbet trajectory.out
    pyargus classify-ground cloud.las --out classified.las --cell 3 \
      --window 60 --threshold 1.5
    pyargus dtm classified.las --out dtm.asc --cell 3
    pyargus align cloud.las --sbet trajectory.out \
      --vertical EPSG:6360 --proj-network --write aligned.las
    pyargus contours classified.las --out contours.dxf --interval 1 \
      --breaklines creek.geojson
    pyargus colorize cloud.las --eo eo_Photos.csv --images Flight_dir \
      --out rgb.las      # or the Colorize stage in `pyargus gui`
    pyargus info cloud.las
    pyargus copc cloud.las --out cloud.copc.laz

Project alignment with boresight disabled solves vertical shifts directly
from ground overlaps. Trajectories still determine time coverage and strip
matching, but their attitude is unused. Boresight solving continues to require
verified navigation conventions. Relative alignment fixes the first analysis
strip at zero; it does not establish an absolute vertical datum.

## Running

    .venv/Scripts/python.exe -m pytest tests/ -q

To rebuild the environment, use the one recipe in `docs/WINDOWS_REBUILD.md`
(Fresh environment): uv with the pinned `requirements-validation-win-py311.txt`
in copy mode (OneDrive refuses hardlinks), then `--no-deps --no-build-isolation
-e .`. An unpinned `uv pip install -e ".[dev]"` gives a different environment
and is not the validated one. `.venv/Scripts/python.exe -m devtools.validate`
runs the suite with a recorded source fingerprint and environment.

Read `HANDOFF.md` before doing anything substantive.

## The desktop application

    pyargus gui

One window with Review, Process and Deliver modes over the same library
the CLI uses: a central 3D viewer with cross-sections, a Layers sidebar,
a Task panel (Inspect / match, Strip QA, Classify, DTM/DSM, Contours,
Above ground, Colorize, Align) and a lower dock for Job history, QA
results, linework and the log. The operator guide is
`docs/WORKSPACE_LAYOUT.md`; `docs/GUI_STATUS.md` lists what is delivered
and names the current build. The pyLynceus launcher remains; pyLynceus
has the reciprocal button, and each tool launches the other in its own
venv. The dated sections below are history and keep the menu names and
build folders of their day.

## Building the exe

The repeatable procedure is in `docs/WINDOWS_INSTALLER.md` (Repeatable
build), using the pinned environment from `docs/WINDOWS_REBUILD.md`, which
installs PyInstaller 6.22.3 and pyinstaller-hooks-contrib 2026.7 in copy
mode. Builds go to a dated folder such as `dist/0.2.0-<date>`, never to a
shared `dist/pyArgus`; the payload is staged with
`packaging/windows/stage_installer.py` and compiled with Inno Setup from
`packaging/windows/pyArgus.iss`.

**Only the dist copy runs**: the build leaves a second pyArgus.exe in
the PyInstaller work folder whose _internal is never assembled. Delete
that work folder after building; it is cache and regenerates. Copy the
whole dated `pyArgus` folder, not just the exe.

The brand regenerates from code: `.venv/Scripts/python.exe
packaging/make_logo.py` (needs Pillow) draws the mark and derives the
.ico.

### Above-ground classification in the desktop application

Use the **Above ground** tab. Select **Train model**, choose a cloud
with class-2 ground and at least two labeled classes among 3–6, set
the training cell size and XYZ units, and choose a new `.joblib` output.
After training the tab selects the new model automatically. For
**Apply model**, choose a ground-classified cloud and a new LAS/LAZ
output. The stored cell size is used automatically and the selected
XYZ units must match training; no coordinate conversion is performed.
Class-2 ground and noise classes 7/18 are preserved. Only load trusted
joblib files. Older models without processing metadata must be retrained
for GUI use; the existing CLI remains available. Model transfer accuracy
must be checked on the receiving project.

The desktop build of that date (`dist-project-release`) is no longer kept;
the current build is named in `docs/GUI_STATUS.md`. Keep any build's entire
folder together. `pyArgus.exe --self-test` exercises the bundled forest
training/persistence/inference and creates a hidden window to verify the
Above ground task, exiting zero on success.

Verified 2026-09-09: 169 tests passed; the reference battery passed all 45 checks; the packaged self-test exited 0. This build includes the checkout's concurrent alignment work. Desktop integration changes are confined to the GUI, model metadata, packaging entry, and tests.


### Job timer and completion status

The run panel shows the active stage, elapsed HH:MM:SS, and Ready, Running, Stopping, Finished, Failed, or Stopped status. The elapsed timer freezes when the worker exits; the log records the outcome and duration. An animated bar means the worker is active without a measured percentage, not an estimate of time remaining. Stop is cooperative: the display remains Stopping until the current operation returns. Inspect outputs after stopping; files already written are not rolled back. Failed or stopped jobs do not automatically hand products to downstream stages.


File dialogs now list supported formats and supply default extensions. Above ground switches its output filter between .joblib (Train model) and LAS/LAZ (Apply model). Verified with 21 GUI tests and the packaged self-test.


### Preview navigation

Use the mouse wheel or Zoom buttons to magnify the preview, drag with the left mouse button to pan, and Rotate buttons for 15-degree turns. Reset / Fit restores the original orientation and fits the image. New previews reset the view. These are 2D raster preview controls, not a 3D point-cloud viewer; they never change source coordinates or exports.



### Native TerraScan trajectories

Add a `.trj` through **Add data** (the Trajectory entry of that build's former
Data menu and its Inspect trajectory button are gone); Project settings lists it with its
time-base state. `pyargus trajectory-info flight.trj` reports record count,
time span, line number and coordinate/attitude ranges. Native TSCANTRJ version
20010715 is supported; malformed or unknown layouts refuse.

For QA, select TRJ time explicitly: **same** compares stored timestamps
directly with LAS; **week** joins trajectory GPS week seconds to LAS adjusted
standard GPS time. The sample Example_Project trajectory contains 436024721 through
436024936, consistent with adjusted standard GPS time, but the file does not
declare that interpretation. Verify it against the LAS. No date is inferred.
CLI: `pyargus qa-report cloud.las --out qa --trajectory flight.trj --trj-time same`.

Alignment additionally requires the TRJ confirmation checkbox (CLI:
`--trj-confirmed`). Confirm XYZ are in the LAS coordinate frame, horizontal
and vertical units and datum, with clockwise heading from grid north,
right-wing-down roll and nose-up pitch. TRJ angles are read in degrees and
converted to radians; source positions are used unchanged. SBET geoid/CRS
settings are bypassed for TRJ. Do not check this merely because import succeeds:
vendor convention validation is still needed for a new sensor/export.
Coverage, heading/track, flying-height and scan-angle checks remain active.
A single trajectory must cover at least 99% of the solve points; importing
and merging a whole folder of flight trajectories is not implemented.

Native file reading is validated against Example_Project line 12 (43,001 positions,
200 Hz, 215 seconds). Geometry and correction paths are tested with constructed
truth. No alignment of that real project has been performed or validated.

TRJ verification (2026-09-09): 193 tests passed, followed by 34 affected GUI/trajectory tests after the background-inspection change. All 46 reference acceptance checks passed. The final packaged self-test exited 0.


### Multi-file projects (2026-09-10)

Open **Project settings** in the desktop app (Process mode, or the sidebar
Settings button; the Data menu of the September build no longer exists). This
is the project workflow for combined strip QA and alignment; classification,
surface and single-cloud tasks keep their behavior.

1. Add LAS/LAZ files and TRJ/SBET trajectories. File pickers allow multiple
   selection; Add folder includes supported files immediately inside that
   folder (not subfolders). Repeated selections of the same path are ignored.
2. For TRJ, select the trajectories, choose **same** or **week**, and click
   **Apply to selected**. `same` means the clock stored in the LAS; `week`
   means GPS seconds of week. SBET always uses `week`. A GPS week must be
   supplied for LAS week-time inputs and for week-time trajectories when
   the cloud block spans multiple weeks. A single common week can be inferred
   from adjusted-standard LAS timestamps; that is not proof of the selected
   trajectory's acquisition date.
3. In Settings, confirm common vertical datum and XYZ units. Tagged CRS
   mismatches refuse; untagged clouds require a CRS declaration. No LAS
   coordinates are reprojected. TRJ alignment separately requires verified
   coordinate/attitude conventions. Use one sensor/calibration per project.
4. Click **Inspect / match**. The results show each cloud's matched, missing,
   and ambiguous returns and the mapping from analysis strip to original
   LAS line ID and trajectory. Internal trajectory gaps over the configured
   limit are not interpolated. TRJ line numbers constrain matching; filenames
   do not. Overlapping SBET files can be resolved by selecting LAS files and
   binding them to one selected trajectory. Bindings do not override time
   coverage or native TRJ line IDs.
5. Choose a **new output folder**, then run **Project QA** or **Align project**.
   With trajectories selected, both operations require unique matches for
   all returns. Inspect / match remains available for diagnosing incomplete
   projects. Without trajectories, QA requires confirmation before treating
   repeated IDs in multiple files as tiles of the same flights.

QA combines the selected block, so overlapping lines in separate files are
compared. A line spanning several tiles shares one analysis ID; a reused LAS
ID matched to a different trajectory gets a separate analysis ID. The HTML
report and inventory explicitly map these IDs back to source files/lines.

Alignment solves the block together, then exports one corrected LAS/LAZ per
source, retaining the source point order, flight-line IDs, classifications,
colors, extra dimensions, and headers. Numbered output prefixes avoid collisions
between identical basenames. It includes `before/report.html`,
`after/report.html`, `alignment.json`, and a saved `project.json`. After-QA uses
the actual exported, quantized coordinates. Independent checkpoints are still
needed to establish absolute accuracy. The desktop defaults to vertical offsets;
boresight solving is an explicit option and can refuse unobservable geometry.

Source files and existing output folders are never overwritten. Jobs build a
temporary result folder and publish it after successful completion; cancelling
before publication leaves no final result folder. Source changes during reading
or trajectory matching are checked and refused. Inspection runs in chunks;
QA/alignment retain arrays and default to a 25-million-point limit. Select a
smaller block or deliberately raise this limit for available RAM. This is not
a disk-backed or COPC processing engine.

Save/load projects as JSON; only file references and settings are stored, not
copies of point clouds. Equivalent CLI entry points:

    pyargus project-info project.json
    pyargus project-qa project.json --out new_qa_folder
    pyargus project-align project.json --out new_alignment_folder

`project-align --boresight` also solves boresight; `--cell` and `--min-points`
set alignment patch construction. Defaults match the project window.

Validation: the full suite passed 246 tests. The final 24 project tests include
cross-file alignment recovery, repeated line IDs, ambiguous/missing matches,
gaps, CRS/time refusals, cancellation, and preservation of exported dimensions.
`python -m reference.project_import` matched all 50,000 sampled Summerville
returns across two temporary LAS line samples and two SBET intervals, with zero
unmatched or ambiguous returns. The reference inputs on Z: were read only.

The final isolated baseline plus importer passed all 248 unit tests. The packaged self-test exited 0, including multi-file import and the project window.

Final reference validation: all 52 checks passed on the isolated committed baseline plus importer (0 failures). The final dist-project-release packaged self-test exited 0. The separate in-progress imagery changes in the shared working tree produced 3 colorization expectation mismatches in the earlier full run; they were not modified by this work. SBET coordinate conversion retains the existing NAD83(2011) source-datum assumption; SBETs in another datum need conversion before alignment.


### 3D desktop inspection

The 3D viewer is the centre of the main window (the separate `dist-3d` build
and its Data menu entry are history). Add one or several LAS/LAZ files.
Left drag orbits in three dimensions, right drag pans, and the wheel zooms.
Top, Front, Side, Oblique and Fit presets reset the camera. Projection is
orthographic, with equal XYZ scale. Files can be hidden independently.

Choose elevation, classification or original flight-line ID coloring. The
categorical palette repeats after eight IDs; identical source IDs in different
files share a color. Loading runs in a cancellable worker with elapsed time and
Finished/Failed status. This first viewer streams a fixed, deterministic sample
of at most 150,000 points; zoom does not fetch additional detail. Small or rare
features may be omitted. It is an inspection view, not a measurement tool.
All source points remain available to analysis and export independently.

**Add tracks** accepts multiple TRJ or SBET files. Confirm TRJ XYZ frame, units
and vertical datum; SBET conversion assumes NAD83(2011) ellipsoidal meters and
requires the stated LAS vertical CRS or geoid undulation. Geoid CRS conversion
requires a locally available grid. Trajectories are drawn on top of the cloud
and split at time gaps over one second; overlay alone does not validate timing,
attitude, or alignment. Project launch transfers the cloud list; add trajectories
inside the viewer. Matching projected CRS and common XYZ units are required;
LAS files must also share their vertical datum. No source files are modified.

Progressive detail, perspective projection, cross-sections, point measurement,
and coordinated before/after comparison are not part of this first release.


Trajectory time setup: imported TRJ files initially show `[set time; ...]`.
Choose `same` or `week`, then use **Apply time base to ALL trajectories**, or
select files and **Apply to selected**. The all-files action changes time base
only, preserving individual GPS weeks and attitude confirmations. Inspection
highlights unassigned files before starting. (The `dist-3d-timefix` build of
that date is no longer kept; `docs/GUI_STATUS.md` names the current one.)


### DXF breaklines and stage previews

(The `dist-usability` build of that date is no longer kept.) In **Contours**,
use **Breaklines (DXF / 3D GeoJSON)** to
select the surveyed breakline file, set the contour interval/cell size, choose
a new output filename, then run the stage. The CLI `contours --breaklines`
also accepts DXF and remains repeatable for multiple files.

Prepare a model-space, breakline-only DXF using straight **3D POLYLINE**
entities. Elevated LINE entities and straight planar POLYLINE/LWPOLYLINE
entities with nonzero stored elevation are also supported. Closed lines stay
closed, and object-coordinate vertices are converted to world coordinates.
Curved/bulged entities, meshes, splines, and blocks are refused; export these
as straight surveyed 3D polylines first. Text, points, dimensions and hatches
are ignored. Ambiguous zero-elevation planar geometry is refused; a genuine
zero-elevation surveyed breakline can be supplied as a 3D POLYLINE.
Coordinates are not reprojected or rescaled: DXF and LAS must share XYZ units,
coordinate reference and vertical datum. Breaklines use the existing **soft**
TIN constraints (densified vertices), not enforced triangle edges.
The importer uses [ezdxf](https://ezdxf.readthedocs.io/en/stable/dxfentities/polyline.html);
source installs require `.[cad]`, while the desktop bundles the dependency.

After **Classify**, the result becomes the project input for its flight and
the 3D viewer shows it in Classification colours: ground brown, unclassified
gray, vegetation greens and building red when present. The 2D stage preview
images this section once described were removed with the unified workspace;
the viewer's display sample is bounded, while exports retain all points. After
**Contours**, show the output DXF from Layers or Deliver; contour and breakline
layers draw as overlays on the loaded cloud.


### Large-project QA (including the 402-million-point Example_Project block)

Use the current build (`docs/GUI_STATUS.md`; the `dist-large-qa` build of that
date is no longer kept). Load the saved analysis project from the Layers
context menu,
keep **In-memory point limit** at 25,000,000, choose a NEW output folder, and
click **Project QA**. Above that limit QA automatically uses a disk-backed
path; it does not require raising the limit. Alignment still requires a block
within the in-memory limit. Matching is revalidated during QA; an earlier
Inspect result is not treated as a permanent cache of source files.

Prefer an output folder on a local SSD with ample free space. The initial disk
check conservatively allows 256 bytes per input point plus overhead: about
96 GiB for 402,465,700 returns. SQLite external sorting may also use the system
temporary drive, which needs free space. This allowance is an estimate, not a
hard maximum. Disk-full errors fail the job without publishing a partial report.
Temporary data is removed on success, normal failure, or Stop; a forced process
termination may leave a `.pyargus-large-qa-*` folder beside the output.

The job streams 500,000 returns at a time through the same trajectory matching
logic. All returns contribute to density; all class-2 returns contribute to
exact per-strip cell medians. No point sampling is used. Every source contributes
to the same world-aligned cells before display tiles are made. Density cells
are 3 map units, ground dZ cells 6 map units with at least 3 returns per strip.
Cells are half-open, including the outermost edge, unlike the legacy report's
maximum-edge folding. These cell-local statistics need no overlap buffer.
Sparse geometry is stored on disk rather than allocating a project-wide raster.

Open **report.html** in the chosen folder when the job says Finished. The
project density overview is reduced only if needed for display; full-resolution
256x256 map tiles have PNG/world-file pairs. Use the project's CRS in GIS.
`density_cells.csv`, `strip_dz_cells.csv`, `summary.json`, `inventory.json`,
`tiles.json` and `project.json` preserve exact cell results and source identities.
New reports also include measured occupied-area strip coverage percentages,
a north-up multiplicity map and exact coverage CSVs. Known noise classes 7/18
are excluded from coverage only. See [Measured coverage overlap](docs/COVERAGE_OVERLAP.md)
for both directional denominators and the distinction from planned sidelap.
Keep the report folder together. Positive dZ means strip B is above strip A.
No qualifying overlap is reported explicitly, not as a successful alignment.
Optional API checkpoints retain local-median residuals; the large report does
not yet include the small report's per-strip plane decomposition. No checkpoints
means no absolute vertical accuracy assessment.

Stop remains active during file scans, SQL reduction, and report writing.
This release was tested on the full 15.28M-point Summerville reference and
synthetic multi-file cases; the complete 402M-point Example_Project block has not yet
been run through this release.


## License

Apache-2.0; the full text is in `LICENSE`. The patent grant is the
reason for choosing it over MIT: this repository's reason to exist is
a least-squares strip adjustment, and an explicit grant is worth more
around an algorithm than around glue code.

Copyright is held by Mapworks, LLC.

## Manual point classification

The QA / cross-sections workspace now opens a complete-section classification
editor with rectangle/polygon selection, class assignment, undo/redo, and
verified full-cloud LAS/LAZ export. See [the workflow and preservation limits](docs/MANUAL_CLASSIFICATION.md).

## Automatic project alignment reports

Project alignment and LP360 alignment now generate one before/after comparison
page, with exported-coordinate checks, corrections, input identities, downloadable
CSVs, and explicit missing-support reasons. Configure optional survey checks under
**Tools > Alignment report settings…**, or the LP360 dialog's **Alignment report**
tab. Open the completed report from **Deliver > Open selected report** or the
LP360 job results. Reference and independent checks remain distinct. See
[Automatic alignment reports](docs/ALIGNMENT_REPORTS.md) for methods and limits.

[Read-only flightline diagnostics](docs/FLIGHTLINE_DIAGNOSTICS.md) adds coverage,
qualified height-difference maps and existing baseline/candidate comparisons
through Tools > Flightline diagnostics… or the flightline-diagnostics CLI.
This is available in the source preview; the installed binary is unchanged.
