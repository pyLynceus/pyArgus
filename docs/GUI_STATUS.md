Current installation package: [WINDOWS_INSTALLER.md](WINDOWS_INSTALLER.md); the newest dated Windows build is 0.2.0-review-2026-10-22; see [acceptance scope](WINDOWS_REVIEW_BUILD_20261022.md). GPU viewing and bounded CPU tile processing are delivered; see [acceleration](ACCELERATION.md).

## Source flightline diagnostics — October 27, 2026

Tools > Flightline diagnostics… opens a scrollable eyeWitness-themed dialog
with a visible Run flightline diagnostics footer. It uses all current project
clouds, with an optional saved candidate project and explicit settings. Closing
the dialog leaves an active job and the main Stop control available. Settings
persist; reports enter Initial QA/history, without Alignment completion or cloud
promotion. CLI use is also available. See [operator guide](FLIGHTLINE_DIAGNOSTICS.md).

Combined current-source validation: 813 passed, one Linux-only X11 skip reviewed
for the Windows scope, all 73 reference checks passed, no failures/environment
warnings. Raw verdict remains needs_skip_review. This also covers the earlier
theme code. Browser report layout and native Tk routing/lifecycle are checked;
live Windows/DPI visual acceptance and a rebuilt installer remain pending.
Evidence: build/flightline-diagnostics-20261027/. Installed binary unchanged.

## eyeWitness theme — October 27, 2026

The source checkout defaults to eyeWitness's dark suite styling. It covers
menus, tables, input/selection/disabled states, notebooks, notes and logs, with
font-aware table row heights. Point-class colors and processing are unchanged.
Set SURVEY_SUITE_THEME=original before starting to restore the light palette.
The installed binary still needs a rebuild. Native Windows chrome/file dialogs
can follow the operating-system appearance. Four native theme/scaling checks
and 15 focused GUI regressions passed; visual/operator acceptance and a full
current-source release gate remain pending. Evidence and a separate source
preview launcher: build/eyewitness-theme-20261027/.

# GUI usability status — October 8, 2026

The usability rewrite is partially delivered. This is the current status;
chronological entries in other documents can describe older behavior.

Project context, named class filters, Solo/Compare and compact sections are delivered;
see [review shortcuts](REVIEW_SHORTCUTS.md).

Draggable section corridors and Full 3D / 3D + Profile / Comparison review
layouts are delivered; see [review navigation](REVIEW_NAVIGATION.md).

Saved camera views, issue pins/notes and Resume Review are delivered; see
[review memory](REVIEW_MEMORY.md).

Header footprint overview, a collapsible sidebar locator and current-action
status are delivered; see [project overview](PROJECT_OVERVIEW.md).

Original/result comparison with preserved viewing context and paired sections
is delivered; see [comparison guide](VERSION_COMPARISON.md).

Offline QA review-package export is delivered through File, Review and Deliver;
see [review-package guide](REVIEW_PACKAGE.md).

The menu-and-tab layout is delivered; see [operator guide](WORKSPACE_LAYOUT.md).

Current executable (newest dated portable build):
`C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex/dist/0.2.0-review-2026-10-22/pyArgus/pyArgus.exe`

That build includes the task-input, Align promotion, window-fit and camera
continuity changes of October 21-22. Combined source acceptance is 783 passed,
one Linux-only skip, with all 73 reference checks passed. Packaged and relocated
GPU/native/multicore self-tests passed; installation lifecycle testing is pending.
Evidence: `build/release-review-20261022/` and the dated installer's verification. See [Windows rebuild](WINDOWS_REBUILD.md) for environment and native PDAL setup.

Keep the entire containing folder, including `_internal`. Source checkout:
`C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex`.
The old Desktop/pyArgus/dist-dialogs executable does not contain this work.

| Area | Delivered | Still to do |
|---|---|---|
| Main layout | Review / Process / Deliver tabs; File/View/Tools/Help menus; grouped Layers; compact wrapping toolbar; collapsible review pane | Further compacting of section settings after operator feedback |
| Navigation | Orbit, pan, zoom, fit, standard views, bounded local-detail refinement and adjustable red/cyan anaglyph inspection; cursor zoom, picked orbit center, Previous view; optional OpenGL GPU normal/stereo rendering with visible CPU fallback | Further progressive spatially indexed detail |
| Inputs | Shared importer for clouds/trajectories; explicit task input/scope; since October 21, 2026 the single-cloud task input is set only by right-click → Use as task input and carries a ▶ badge, so selecting a row changes nothing | Better defaults and fewer setup clicks |
| Source/result versions | Successful classifications and (since October 21, 2026) alignments become project inputs with the camera kept; original retained; explicit switch-back, also with the camera kept; unregistered files are refused as versions; since October 22, 2026 showing a retained cloud, Reset detail and review-pane or dock resizes leave the camera and the point under the viewer centre in place; separate review-only Original/Result/Both comparison and F6 swaps with common profile scale | Extend the model to colourisation and manual-edit imports |
| Progress | Elapsed time, completion/failure/cancellation, per-file attempts and review decisions, stale reasons; evidence-based next-action button; partial ground-run coverage; since October 22, 2026 a finished Inspect opens Matching results in the dock and a finished LP360 job shows its delivered clouds | Batch resume and additional stage coverage summaries |
| Cross-sections | Explicit source selection or all-loaded comparison; complete/sample counts; classification editing; left/right section stepping plus station-based sections along imported DXF entities, keyboard stepping and saved route settings; draggable A/B, move, width and rotation handles; optional extract on release | Operator feedback on corridor interaction |
| Review memory | Named views with camera/filter/layout/section context; issue pins and notes; Next open issue; Resume Review; workspace persistence and JSON notes export | Cross-project issue summaries |
| Overview | Background header-only inventory; projected CRS groups; click-to-center locator; camera-plane, section and issue overlays; selected extent fit; compact processing/viewing/status summary | Actual occupied coverage map; shared suite launcher |
| Features | Manual 3D point-snapped line tracing; vertex XYZ edits; split/join/reverse; undo/redo; review status; workspace persistence; DXF plus provenance | Assisted extraction, section-profile snapping, surface integration |
| Classification | Single-cloud or sequential whole-project batch, unique output names and records; noise preservation/screening; optional tiled CPU workers and estimated memory budget | Spatial noise detection; automatic tiled dispatch after profiling |
| Review export | Offline HTML/JSON/CSV ZIP with source checks, issue/view records, stage/attempt history, optional current previews and section sample; cancellation, no-overwrite publication and output receipt | Cross-project review aggregation |
| Build identity | Current executable path, adjacent build-info.json and Help → About source commit | Release/update distribution |

The station/elevation cross-section remains a 2D plot intentionally; the
separate 2D plan/cloud viewer was removed. One 3D cloud viewer does not mean
removing profile inspection.

## Next viewing steps

1. Review Original/Result comparison, paired sections and package export on Example_Project.
2. Shared suite project launcher after the project context is stable.
3. Hardware acceptance on AMD/Intel, larger display samples and further indexed access based on measured bottlenecks.

## Performance roadmap

1. Profile the current application on repeatable inputs; separate loading,
   computation and redraw work before choosing a language or renderer.
2. Use that evidence to choose indexed access/caching improvements.
3. Introduce a compiled component only for a demonstrated bottleneck and
   compare its outputs against the existing implementation.
4. Upgrade the rendering architecture independently of workflow logic.
5. Keep numerical regression, metadata and provenance checks throughout.

The compact navigation layout, layout presets, saved camera views, issue
notes and Resume Review are delivered. Source identity checks prevent
recalling stale views; a saved section definition still requires explicit
extraction to display its profile.

Section stepping is delivered; see [operator instructions](SECTION_STEPPING.md).

## Spatial-access experiment

The selective section-cache experiment passed exact-result tests and showed
measured gains on Example_Project. Optional section caching is now integrated into the GUI. See
[experiment results](SECTION_CACHE_EXPERIMENT.md); the [GUI workflow](SECTION_CACHE_GUI.md) describes build, cancellation,
manual cleanup and full-scan fallback. Viewer caching and idle-triggered local refinement are delivered; see [Auto detail](AUTO_DETAIL.md).

See [Features workspace](FEATURES_WORKSPACE.md) for tracing, review and export.

See [Anaglyph viewer](ANAGLYPH_VIEWER.md) for glasses, depth, eye swapping and picking limitations.

DXF reference layers and Review mode are documented in [Review / linework](REVIEW_LINEWORK.md). Automatic refinement is available with a valid local cache. Line-following sections are delivered; see [instructions](LINE_FOLLOWING_SECTIONS.md). Issue markers, saved camera views and Resume Review are delivered; see
[review memory](REVIEW_MEMORY.md).
