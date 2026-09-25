# GUI usability status — September 25, 2026

The usability rewrite is partially delivered. This is the current status;
chronological entries in other documents can describe older behavior.

Current executable:
`C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-releases/2026-09-25-8e36ca5/pyArgus/pyArgus.exe`

Keep the entire containing folder, including `_internal`. Source checkout:
`C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex`.
The old Desktop/pyArgus/dist-dialogs executable does not contain this work.

| Area | Delivered | Still to do |
|---|---|---|
| Main layout | Project files at left; one 3D viewer; task/scope at right; lower review/settings/log dock | Further compacting and fewer nested controls |
| Navigation | Orbit, pan, zoom, fit, standard views and bounded local-detail refinement | GPU renderer; progressive spatially indexed detail |
| Inputs | Shared importer for clouds/trajectories; explicit task input/scope | Better defaults and fewer setup clicks |
| Source/result versions | Successful classifications become active processing inputs; original retained; explicit switch-back | Extend the model consistently to other processing stages |
| Progress | Elapsed time, completion/failure/cancellation, per-file attempts and review decisions, stale reasons | Stronger next-action guidance and batch resume |
| Cross-sections | Explicit source selection or all-loaded comparison; complete/sample counts; classification editing; left/right section stepping with automatic extraction | Saved review presets and simpler profile navigation |
| Classification | Single-cloud or sequential whole-project batch, unique output names and records; noise preservation/screening | Spatial noise detection; automatic memory-aware tiled GUI dispatch |
| Build identity | Current executable path and adjacent build-info.json | In-app About/build identity |

The station/elevation cross-section remains a 2D plot intentionally; the
separate 2D plan/cloud viewer was removed. One 3D cloud viewer does not mean
removing profile inspection.

## Next implementation order

1. Profile the current application on repeatable inputs; separate loading,
   computation and redraw work before choosing a language or renderer.
2. Use that evidence to choose indexed access/caching improvements.
3. Introduce a compiled component only for a demonstrated bottleneck and
   compare its outputs against the existing implementation.
4. Upgrade the rendering architecture independently of workflow logic.
5. Keep numerical regression, metadata and provenance checks throughout.

GUI work remains on the roadmap. Performance work is not a declaration that
the compact layout, presets or next-action design is complete.

Section stepping is delivered; see [operator instructions](SECTION_STEPPING.md).

## Spatial-access experiment

The selective section-cache experiment passed exact-result tests and showed
measured gains on a real two-file client delivery. Optional section caching is now integrated into the GUI. See
[experiment results](SECTION_CACHE_EXPERIMENT.md); the [GUI workflow](SECTION_CACHE_GUI.md) describes build, cancellation,
manual cleanup and full-scan fallback. Viewer caching remains pending.
