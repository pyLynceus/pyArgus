# Two-file LAS performance baseline — September 24, 2026

Two strip-adjusted LAS files from one client delivery; about 25 million points; two repeats in alternating source/local order.
Instrumented with cProfile. Copies were SHA-256 verified; original metadata was unchanged.
Caches were warmed by copying/hash verification. These results do not measure cold network access.

| Operation | Source median [range] (s) | Local median [range] (s) |
|---|---:|---:|
| Read point records | 7.720 [0.922–14.519] | 0.660 [0.613–0.708] |
| Overview sample | 0.709 [0.616–0.803] | 0.678 [0.662–0.695] |
| Cross-section | 2.110 [2.013–2.206] | 2.074 [1.912–2.237] |
| Viewport refinement | 3.258 [3.245–3.270] | 3.354 [3.026–3.681] |
| Classify flight 1 | 15.309 [14.900–15.719] | 16.283 [16.064–16.502] |
| Classify flight 2 | 22.177 [22.100–22.254] | 15.175 [15.109–15.240] |

Disk-backed QA on local benchmark-classified copies: median 119.22 s; range 116.73–123.64 s (four runs). No trajectory matching or control checks.

Corrected redraw test: about 150,000 displayed points; canvas [920, 672]. Median frame times: 78.4 ms, 79.2 ms. Draw plus Tk idle updates; not input latency or full-cloud rendering.
Four initial redraw measurements had an invalid 1x1 canvas and are explicitly excluded in report.json. The harness now rejects that condition.

| Operation | Maximum sampled process RSS (GiB) |
|---|---:|
| overview | 0.188 |
| section | 0.204 |
| refine | 0.211 |
| classify_0 | 1.702 |
| classify_1 | 1.667 |
| qa | 0.281 |
| redraw | 0.099 |

RSS is sampled every 25 ms and includes retained allocations from preceding operations. It is not an isolated allocation peak.

## Profile findings

- Compiled SciPy morphology: 9.84 s in the first 14.90 s classify_0 run. This is a nested profile measurement, not an additional stage.
- SQLite reduction script: 52.76 s in the first 116.73 s qa run. This is a nested profile measurement, not an additional stage.
- QA also spends substantial time in NumPy sorting. These are already compiled operations; translating Python wrappers is not an established speedup.
- Local copying alone showed limited benefit for overview/section access under these warmed-cache conditions. However, one source scan took 14.52 s with only 0.66 s CPU, versus 0.92 s in the other repeat. This is variable waiting outside computation; the profile does not isolate network, server, storage or other system causes.
- Overview, section and refinement still scan the full source files. A spatial access experiment can reduce repeated work, but its index-build cost and query selectivity must be measured.

## Next experiment and acceptance criteria

Prototype optional, invalidation-aware cached overview/section access, then compare spatial indexing alternatives on multiple section positions and zoom extents. Keep the uncached path as the reference.

Acceptance requires matching total corridor counts, original file/point indices, classifications and coordinate values; stale sources must invalidate cached/indexed data. Report build cost, disk footprint, query times, memory and break-even query count. Do not make a production format or language change until those measurements justify it.

Treat morphology and exact QA aggregation as separate algorithmic optimization investigations. Preserve disk footprints, boundary conventions, exact medians, cancellation and provenance when comparing implementations.

## Evidence and limitations

- Full machine-readable evidence (`report.json`), per-operation cProfile files and experimental outputs: kept in a local benchmark folder outside the repository (not published).
- Harness: `reference/profile_workflow.py`; methodology: `docs/PERFORMANCE_PROFILING.md`.
- Synthetic end-to-end smoke run completed 14 operations; the final corrected harness also passed all 14 with valid canvas dimensions.
- Scan, overview, section, refinement and classification result counts matched across all four source/local repeat combinations.
- Benchmark classification used no newly selected noise bounds. It does not repair or approve the client job, and its outputs were not promoted into a workspace.
- This is a two-file LAS workload, not a broad LAZ/COPC, billion-point, GPU or cross-machine performance study.
- Production algorithms and the released executable were not changed during profiling.
