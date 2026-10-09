# pyArgus

An open-source lidar workstation for importing, inspecting, classifying,
aligning, reviewing and delivering point clouds. The long-term aim is an
end-to-end alternative to the TerraSolid suite; current capabilities have
explicit limits and do not establish feature parity or survey accuracy.

## Current desktop

The workspace uses Review, Process and Deliver tabs with File, View, Tools
and Help menus. One 3D cloud viewer supports pan, orbit, cursor zoom, standard
views, red/cyan anaglyph, imported DXF references, local-detail caches,
cross-sections, named views, issue notes and original/result comparison.
Project records track stage attempts, input versions, completion and review
status. Successful processing still requires operator acceptance.

OpenGL 3.3 can accelerate the bounded display sample, with a visible CPU
fallback. Tiled ground classification supports bounded concurrent CPU
morphology; flights in a batch remain sequential. QA and alignment retain
existing execution paths. See [acceleration](docs/ACCELERATION.md) for measured
synthetic timings, hardware coverage and resource limits.

## Install from source

Python 3.10 or later is required; the recorded Windows validation uses 3.11.
Create an independent environment rather than reusing another project's one:

```powershell
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
& ./.venv/Scripts/pyargus.exe gui
```

The installed command is `pyargus gui`. For a pinned Windows environment, see
[Windows rebuild](docs/WINDOWS_REBUILD.md) and
`requirements-validation-win-py311.txt`. Use copy mode when installing with uv
into a synced folder. PDAL is an additional native dependency for COPC writing.
Optional package groups are `lidar`, `crs`, `ml`, `imagery`, `cad` and `gpu`.

The October 8 installer remains a separately retained local release. This
branch is a source backup and does not publish that executable, its training
assets, client projects or private records. Installer build tooling is in
`packaging/windows/`; see [installation guide](docs/WINDOWS_INSTALLER.md).

## Workflow and guides

1. Add LAS/LAZ files and optional TRJ/SBET trajectories. Declare CRS, units,
   clocks and conventions explicitly; inspect inventory and matching first.
2. Run initial QA. Unclassified data cannot support ground-only overlap or
   control conclusions merely because a density report completes.
3. Classify, inspect representative sections and retain the originals.
4. Adjust only when the geometry, observability and independent checks support
   it. Project alignment still has an in-memory point limit.
5. Generate terrain/contours from reviewed inputs and export a QA review package.

- [Workspace layout](docs/WORKSPACE_LAYOUT.md), [GUI status](docs/GUI_STATUS.md)
- [QA review](docs/QA_REVIEW.md), [noise and batch classification](docs/NOISE_AND_BATCH.md)
- [Sections](docs/SECTION_STEPPING.md), [DXF references](docs/REVIEW_LINEWORK.md)
- [Saved views and issues](docs/REVIEW_MEMORY.md), [version comparison](docs/VERSION_COMPARISON.md)
- [Review packages](docs/REVIEW_PACKAGE.md), [capability limits](docs/CAPABILITY_ACCEPTANCE.md)

The CLI includes `info`, `density`, `qa-report`, `trajectory-info`,
`sbet-info`, `project-info`, `project-qa`, `project-align`, `classify-ground`,
`align`, `dtm`, `contours`, `colorize` and `copc`. Run `pyargus --help` and a
command's `--help` for its input contract and options.

## Architecture and validation

`pyargus/core` holds pure numerical operations. Format adapters, QA, alignment,
classification, surfaces and imagery modules feed shared jobs used by both CLI
and desktop. GUI modules organize those operations; they do not duplicate the
numerical algorithms. Output contracts retain metadata and source identities.

```powershell
& ./.venv/Scripts/python.exe -m pytest tests/ -q -ra
& ./.venv/Scripts/python.exe -m devtools.validate
```

Run heavy checks serially. The latest local application validation recorded
586 source checks and 73 field-reference checks passing. Those are historical
results for the exported application code, not a fresh CI result or independent
accuracy certification. Field checks require separately held datasets and
grid/native dependencies: `python -m reference.run_all`.

Read [HANDOFF.md](HANDOFF.md) before substantive changes, and
[backup provenance](docs/BACKUP_STATUS.md) for this export's scope.
License: [Apache 2.0](LICENSE).
