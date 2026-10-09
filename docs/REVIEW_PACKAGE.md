# QA review-package export

Choose **File > Export QA review package**, **Review > Export QA review
package**, or the **Export QA review package** button in **Deliver**.
The Deliver export-action selector routes to the same command.

## Export a review

1. Save or apply the issue notes you want to share. If the selected issue has
   unapplied title, category, state or note edits, export asks you to use
   **Apply note** first.
2. In Deliver, optionally enter a short review summary. Choose whether to
   include current-view/profile previews and the extracted section sample CSV.
   Previews are enabled by default; the section CSV is opt-in.
3. Click **Export QA review package** and choose a **new ZIP filename**. Export
   refuses to overwrite existing files or referenced sources. File-menu export
   retains the current viewing layout.
4. Follow elapsed time and messages in the normal job status/log. **Stop job**
   cancels before publication. A successful export appears as an output layer;
   it does not create or approve a processing stage.
5. Extract the entire ZIP into a folder, then open **report.html** in a browser.
   **Open last package folder** locates the ZIP. Keep all extracted files
   together so the report's links and previews work.

## What the package contains

| File | Purpose |
|---|---|
| `report.html` | Offline report: review summary, workflow status, issues, view definitions, comparison context, stages, attempts, decisions, cached headers and source inventory |
| `package.json` | Export identity, software/source commit, per-reference metadata checks, current-versus-recorded job status, comparison readiness and profile context |
| `workspace-snapshot.argus.json` | In-memory workspace snapshot at capture time, with absolute data references |
| `review-notes.json` | Saved views, issue records and Resume Review definitions |
| `sources.csv` | Source paths, roles, availability and changed recorded identities |
| `issues.csv` | All issues, including resolved ones, their anchors and context warnings |
| `stages.csv`, `attempts.csv` | Stage summary and recorded attempt history at export |
| `manifest.json` | SHA256 and sizes of the generated archive members; excludes itself |
| `current-cloud.png`, `current-profile.png` | Optional previews of the current sampled display and valid extracted profile |
| `section-sample.csv` | Optional existing section sample with XYZ, station, across, class, line, source file and original point-record index |

The archive does **not** copy LAS/LAZ files, trajectories, reference DXF,
surfaces, original reports or external job-record contents. These remain
absolute-path references. Existing report/job-record locations are listed.
The package can be read offline without those datasets; reopening its workspace
in pyArgus still needs access to the referenced storage. Paths and notes are
included in full, so share the package with that in mind.

## How to interpret the evidence

- Available means accessible at the metadata check, not approved quality.
  Changed, missing and unavailable references remain in the report. A changed
  identity can belong to an older attempt; per-record expectations remain in
  package.json.
- Source checks use file size and modification time. Archive hashes cover
  generated members only, not external cloud contents. File changes during
  export refuse publication; directory observations and workspace autosaves
  are informational. The snapshot is captured in memory independently of a
  later autosave.
- Current stage status uses the captured processing settings where available.
  `settings_checked=false` flags attempts without comparable current settings.
  Accepted, Skipped and Resolved retain their recorded operator meaning; no
  new numerical QA or accuracy certification is performed.
- Cached overview headers are included without a new header scan. Header
  rectangles are not actual occupied coverage and can include noise.
- Previews capture the current raster and 2D canvas annotations. Font and
  arrow styling may differ slightly. The profile is rendered at a readable
  1024 × 360 resolution even when its pane is hidden, using its current
  filters, zoom/pan and exaggeration. The cloud preview retains current
  filters, stereo and camera settings. Saved views are definitions, not
  automatically replayed screenshots.
- A stale current display is excluded from previews with an explanation.
  Records can still be exported. A section sample requires current sources
  and a corridor matching its extraction; re-extract or turn off that option.
  CSV retains every sampled input/class/line independently of display filters.
  It is not a full-cloud export. Text cells with spreadsheet formula prefixes
  are neutralized in CSV; JSON preserves the original text.

Loading, processing, pending view restoration, extraction and corridor dragging
must finish before capture. Export uses the normal background job runner and
bounded member/total limits. It scans no point records, changes no processing
inputs, and makes no acceptance decisions. After a stop or write failure, no
new final archive is published. A completed archive is retained if Stop is
pressed after publication.
