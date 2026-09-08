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
    pyargus/formats   SBET trajectories, LAS/LAZ (laspy, optional)
    pyargus/qa        density, strip-overlap dZ, ASPRS checkpoint stats
    pyargus/align     Phase 4, the custom strip-adjustment core (plan only)
    pyargus/classify  Phases 3/5 (plan only)
    pyargus/surfaces  Phases 3/6 (plan only)

## Running

    .venv/Scripts/python.exe -m pytest tests/ -q

To rebuild the environment: `uv venv --python 3.11 .venv` then
`UV_LINK_MODE=copy uv pip install -e ".[dev]"` (copy mode because
OneDrive refuses hardlinks).

Read `HANDOFF.md` before doing anything substantive.
