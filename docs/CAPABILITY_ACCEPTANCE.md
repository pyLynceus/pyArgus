# Capability and acceptance inventory — October 9, 2026

The long-term objective is an end-to-end open-source lidar workstation.
Implemented code and regression validation are not TerraSolid feature parity
or an unrestricted production-accuracy claim.

| Capability | Implemented behavior | Remaining acceptance or limit |
|---|---|---|
| Import and inventory | LAS/LAZ, multi-file projects, TRJ/SBET, header overview and matching | Explicit clocks, frames, units and conventions; no inferred sensor calibration |
| QA | Density, ground overlap and checkpoint reports; disk-backed large QA | Unclassified inputs cannot supply ground-only checks; declared methods and independent checks required |
| Ground classification | Shared whole/tiled rules, noise preservation, optional Z screening, sequential batches and CPU tile workers | Operator review; conservative memory estimates; no automatic restart/resume or general spatial noise detector |
| Other classification | Trusted-model training/application and height-based workflows | Model trust, parameter/unit agreement and independent class validation |
| Alignment | Supported offsets, boresight and time-dependent corrections with trajectory geometry | Observability and withheld checks; project solve uses in-memory arrays |
| Viewing | Orthographic 3D, CPU/OpenGL, anaglyph, DXF references and bounded local detail | Approximately 150k display sample; GPU tested on NVIDIA, AMD/Intel acceptance pending |
| Review | Sections and stepping, classification editing, corridors, named views, issue notes, original/result comparison | Complete/sample status remains visible; review decisions do not certify accuracy |
| Terrain and delivery | DTM/DSM/TIN, contours, soft breaklines, image colorization and QA review packages | Hard topology-preserving breaklines, surface repair and broader independent acceptance remain work |
| Distribution | Apache 2.0 source, pinned Windows recipe, frozen tests and installer tooling | Audited release assets and source/binary identity; local installer is not included in this public backup |

## Product acceptance requirements

1. Inventory exact inputs, point counts, source IDs, CRS, units, conventions and
   control roles. Refuse ambiguous or invalid contracts before output.
2. Produce an initial QA record; reserve withheld checks before fitting.
3. Account for all output points, preserve non-target dimensions and compare
   whole/tiled classification across genuine seams on manageable subsets.
4. Inspect representative ground, noise, walls, vegetation and overlap in 3D
   and cross-sections; record unresolved issues and operator acceptance.
5. Check terrain/contours downstream using declared NoData, interpolation and
   breakline policies and project-specific tolerances.
6. Apply adjustment only when supported parameters improve withheld checks
   without degrading other checks. Also report the unadjusted option.
7. Exercise cancellation, missing inputs, corrupt metadata and disk failures;
   distinguish incomplete products from completed output.
8. Reopen the workspace and products in a fresh process, recording source/build
   identity, output hashes and all required checks or explicit limitations.

The latest local application run passed 586 source checks and 73 field-reference
checks. These establish scoped regression behavior; they do not approve any
particular client's deliverables. See HANDOFF.md, ACCELERATION.md and the
validation recipes. Keep numerical thresholds tied to the delivery specification.
