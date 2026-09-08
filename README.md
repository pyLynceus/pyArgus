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
                      geometry (CLI arrives with the map-frame trajectory
                      plumbing, Phase 4.5)
    pyargus/classify  in-core SMRF ground classification (no PDAL: it has
                      no Windows wheel; same algorithm, ~150 lines of
                      numpy/scipy)
    pyargus/surfaces  DTM gridding + ESRI ASCII export; TIN/contours later

The commands:

    pyargus qa-report cloud.las --out qa/ \
      --control marks.csv --control-order pnez --sbet trajectory.out
    pyargus classify-ground cloud.las --out classified.las --cell 3 \
      --window 60 --threshold 1.5
    pyargus dtm classified.las --out dtm.asc --cell 3

## Running

    .venv/Scripts/python.exe -m pytest tests/ -q

To rebuild the environment: `uv venv --python 3.11 .venv` then
`UV_LINK_MODE=copy uv pip install -e ".[dev]"` (copy mode because
OneDrive refuses hardlinks).

Read `HANDOFF.md` before doing anything substantive.
