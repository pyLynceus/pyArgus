# Measured flight-line coverage overlap

Run Project QA (including the LP360 shortcut's QA stages) and open its HTML
report. The **Measured coverage overlap** section appears before Density.
Older reports remain unchanged; run a new QA to obtain these measurements.

## What the percentages mean

A strip covers an XY cell when it has at least one return there, excluding
known noise classes 7 and 18. Other classifications are included. Ground-only
height differences remain a separate calculation with their existing class-2
and minimum-return requirements. Density continues to count all returns.

For each pair, the report shows both directions:

- **% A covered by B:** shared occupied cells divided by A's occupied cells.
- **% B covered by A:** shared occupied cells divided by B's occupied cells.
- **Pair union %:** shared cells divided by A cells + B cells - shared cells.

Different strip footprints can produce different directional percentages.
For example, 40 shared cells out of 100 A cells and 80 B cells means 40% of A,
50% of B, and 28.57% of the pair's union. The project-wide percentage counts
cells covered by at least two strips once, including cells with three or more.
Per-strip shared-with-any percentages also count each shared cell once.

These are **measured occupied-area percentages**, not planned cross-track
sidelap or a flight-planning width calculation. They do not establish survey
accuracy or provide a pass/fail threshold. Point density, cell size, vegetation,
occlusions and unclassified outliers can change the measured footprints.
Transparent cells can be outside the survey boundary or have no observed
eligible return; they are not confirmed survey gaps without a boundary.

## Map and exact files

The map is north up: blue means one strip, amber two, and purple three or more.
The overview is at most 1024 pixels on its longest side. Each coarse pixel uses
the minimum strip count among its occupied fine cells; empty fine cells are
ignored. It is an overview, not an exact gap map.

The default grid is 3 by 3 source CRS units, world aligned. Cells use floor(X /
cell) and floor(Y / cell), including negative coordinates and maximum edges.
Strips from the same analysis identity are merged across source chunks before
counting overlap. No convex hull filling, interpolation or point sampling is
used. The report names the source units; square areas are in those units squared.

- `coverage_pairs.csv`: every pair, shared area and three percentages.
- `coverage_strips.csv`: each strip's area, eligible returns and coverage status.
- `coverage_cells.csv`: each occupied cell's lower-left XY, multiplicity and
  analysis IDs. Use `inventory.json` / the report's identity table to map IDs
  to LAS source IDs and trajectories.
- `coverage.png` / `coverage.pgw`: overview image and world file.
- `tiles/coverage_*.png` / `.pgw`: exact 256 by 256 full-resolution map tiles.
  Disk-backed QA adds `coverage.prj`; use the recorded project CRS for tiles.
- `summary.json`: the `coverage_overlap` object, including grid, exclusions,
  per-strip and pair measurements. Disk-backed `tiles.json` lists coverage tiles.

An isolated strip is labeled explicitly and zero-overlap pairs remain in the
table. A strip with only excluded noise has no eligible coverage; percentages
with a zero denominator are blank / a dash (JSON null). One strip has no pair
comparison. No eligible coverage has no inferred area or percentage.

## Resources and review

Both array and disk-backed QA use the same occupancy calculation. Large QA
streams input chunks and stores coverage cells in SQLite alongside exact ground
statistics. The scratch allowance is conservatively 256 bytes per input return
plus 64 MiB; choose an output drive with sufficient space. Stop remains available.

Review the coverage map, then ground strip differences and checkpoints where
provided. New QA results remain **Needs review** until the operator accepts them.
The reporting update does not change coordinates, classifications or surfaces.
