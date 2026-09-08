# Summerville reference results

Measured 2026-09-08 by `reference/summerville.py` against
`Z:\Users\BJordan\Summerville_SS\Summerville_SS.las` (15,284,332 points,
four strips, classified) and the surveyed control (13 marks, P,N,E,Z
CSVs). Everything on Z: read-only. Units are US survey feet unless
marked.

## Time base

LAS gps_time is Adjusted Standard GPS; with week 2385,
`sow = gps_time + 1e9 - 2385*604800` puts 100.00% of returns inside the
SBET window (481638..482252 s, 200 Hz, 614 s flight). Validates the
SBET reader and the week arithmetic against real POSPac output.

## Density

3-ft cells: median 8.33 pts/ft² (89.7 pts/m²), p5 0.44, p95 22.89.
The p5/p95 spread is overlap structure, not a defect: multi-strip
coverage in the middle, single-strip at the edges.

## Strip-to-strip dZ (ground returns, 6-ft cells, b − a)

| pair | median | rmse | p95 abs dz | cells |
|------|--------|------|------------|-------|
| 1–2  | +0.000 | 0.210 | 0.380 | 2113 |
| 2–3  | −0.005 | 0.230 | 0.480 | 3450 |
| 3–4  | +0.030 | 0.217 | 0.448 |  864 |

Strips form a chain (1–3, 1–4, 2–4 do not overlap). Medians ≤ 0.03 ft:
this delivery is already well aligned, so Summerville validates the QA
machinery but is NOT a "before" case for Phase-4 alignment — a
deliberately mis-adjusted copy (or synthetic misalignment injected via
the georef model) will be needed to prove the solver moves things the
right way.

## Control comparison — the acceptance test

Local measure (median of ground returns within 3 ft of each mark,
lidar − control, the pyLynceus `compare_to_control` method):

| mark | dz (ft) | neighbours |
|------|---------|------------|
| 1    | +0.361  | 53  |
| 2    | +0.188  | 107 |
| 3    | −0.109  | 86  |
| 4    | +0.120  | 64  |
| 202  | +0.171  | 43  |
| 203  | −0.011  | 12  |

n 6, median **+0.146**, nmad **0.148** — reproducing pyLynceus's
recorded +0.146 ft (robust sd 0.150) exactly, same six marks. This
cross-validates the entire pyArgus LAS path, control parsing, and
ground-class handling against an independent codebase on real data.

Marks 200, 201, 208 have no ground return within 3 ft (road-edge
situations); 204–207 lie outside ground coverage entirely (204, 206,
207 are north of the cloud's extent).

TIN measure (`qa.checkpoints`, 60-ft gather) over the 9 in-coverage
marks: mean −0.011, median −0.020, rmse 0.247, NVA 0.483, nmad 0.153.
It disagrees with the local measure by design: interpolation admits
marks without local ground returns and spans kerbs and ditches. Quote
the local measure; use the TIN measure only where its assumptions are
stated.
