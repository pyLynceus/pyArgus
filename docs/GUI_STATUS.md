Current installation package: [WINDOWS_INSTALLER.md](WINDOWS_INSTALLER.md), October 8, 2026. GPU viewing and bounded CPU tile processing are delivered; see [acceleration](ACCELERATION.md).

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

Current executable:
`dist/2026-10-08-acceleration/pyArgus/pyArgus.exe` (locally retained release)

All 586 source checks and all 73 field reference checks passed. Packaged runtime
verification is recorded with the dated installer. See
[Windows rebuild](WINDOWS_REBUILD.md) for environment and native PDAL setup.

Keep the entire containing folder, including `_internal`. This public branch
contains source; the separately retained local executable and installer are
not uploaded here. Rebuild and verify any new binary using the documented recipe.

| Area | Delivered | Still to do |
|---|---|---|
| Main layout | Review / Process / Deliver tabs; File/View/Tools/Help menus; grouped Layers; compact wrapping toolbar; collapsible review pane | Further compacting of section settings after operator feedback |
| Navigation | Orbit, pan, zoom, fit, standard views, bounded local-detail refinement and adjustable red/cyan anaglyph inspection; cursor zoom, picked orbit center, Previous view; optional OpenGL GPU normal/stereo rendering with visible CPU fallback | Further progressive spatially indexed detail |
| Inputs | Shared importer for clouds/trajectories; explicit task input/scope | Better defaults and fewer setup clicks |
| Source/result versions | Successful classifications become active processing inputs; original retained; explicit switch-back; separate review-only Original/Result/Both comparison and F6 swaps with common profile scale | Extend the model consistently to other processing stages |
| Progress | Elapsed time, completion/failure/cancellation, per-file attempts and review decisions, stale reasons; evidence-based next-action button; partial ground-run coverage | Batch resume and additional stage coverage summaries |
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

1. Review Original/Result comparison, paired sections and package export on a representative project.
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
measured gains on a representative project. Optional section caching is now integrated into the GUI. See
[experiment results](SECTION_CACHE_EXPERIMENT.md); the [GUI workflow](SECTION_CACHE_GUI.md) describes build, cancellation,
manual cleanup and full-scan fallback. Viewer caching and idle-triggered local refinement are delivered; see [Auto detail](AUTO_DETAIL.md).

See [Features workspace](FEATURES_WORKSPACE.md) for tracing, review and export.

See [Anaglyph viewer](ANAGLYPH_VIEWER.md) for glasses, depth, eye swapping and picking limitations.

DXF reference layers and Review mode are documented in [Review / linework](REVIEW_LINEWORK.md). Automatic refinement is available with a valid local cache. Line-following sections are delivered; see [instructions](LINE_FOLLOWING_SECTIONS.md). Issue markers, saved camera views and Resume Review are delivered; see
[review memory](REVIEW_MEMORY.md).
