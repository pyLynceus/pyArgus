# Spatial section-cache experiment — September 24, 2026

Inputs: two strip-adjusted LAS files from one client delivery, about 25 million points (see JSON for authoritative per-query totals).
Two repeats per query, with scan/cache order reversed on the second repeat. cProfile enabled; OS/network caches not flushed.

| Query | Matches | Scan median (s) | Cache median (s) | Speedup | Candidate fraction |
|---|---:|---:|---:|---:|---:|
| across_25 | ~10,000 | 2.362 | 0.483 | 4.9x | 1.7% |
| across_50 | ~10,000 | 2.249 | 0.295 | 7.6x | 1.3% |
| across_75 | ~16,000 | 2.162 | 0.291 | 7.4x | 1.6% |
| along | ~140,000 | 2.262 | 0.712 | 3.2x | 13.8% |
| wide_sampled | ~9.4 million | 2.911 | 2.892 | 1.0x | 49.9% |
| outside | 0 | 2.326 | 0.177 | 13.1x | 0.0% |

Match counts are rounded here; the exact per-query totals are in the JSON.

Cache build: 24.62 seconds; cache disk size: about 0.8 GiB.
Build cost / mean query saving: 15.7 queries for this equal-weight query mix.

Every query agreed exactly with the reference scan: total/per-file counts, displayed coordinates, classifications, flight-line IDs, original point indices and sampled order. Empty and heavily sampled sections were included.

Largest sampled process RSS: 0.119 GiB. Process-wide 25 ms sampling, not isolated allocation peak.

This is an experimental local sidecar, not a LAS replacement. It stores chunked, spatially sorted XYZ/class/line/original-index records; source-order replay preserves existing sampling behavior.

Limitations: metadata-only invalidation cannot detect content changes with deliberately preserved size/mtime. No cryptographic cache-integrity check, automatic rebuild, eviction, multi-process writer coordination or GUI fallback is implemented. LAZ/COPC, other cell sizes and very large projects have not been benchmarked. The GUI remains unchanged.

Full evidence and profiles: C:\Users\bjordan\Desktop\ClaudeCodeFAA\pyArgus-benchmarks\2026-09-24-section-cache-oriented/report.json

## Development and validation

- 11 focused tests passed. Cases include exact multi-file sampling, negative
  cell boundaries, reverse direction, empty sections, noise classes, 24 seeded
  oblique sections at large map coordinates, stale/missing/modified chunks,
  duplicate sources, and cancellation before/during cache construction.
- The real-data comparison covered six query geometries, twice each, on both
  clouds. Each comparison checks all returned arrays and input identities,
  not just counts. The broad sampled section contained over nine million returns;
  its retained sample and order matched exactly.
- Initial bounding-box-only selection was slower than scanning for long and
  broad queries. Its results are retained at
  C:/Users/bjordan/Desktop/ClaudeCodeFAA/pyArgus-benchmarks/2026-09-24-section-cache.
- The revised query projects cell bounds along/across the corridor to reject
  irrelevant cells conservatively. It restores original order only after the
  exact corridor filter, then replays reference chunk-wise sampling.

## Decision

Proceed to an optional GUI cache integration with source-change invalidation,
explicit build/cancel/progress states, disk-space checks, cleanup policy and a
full-scan fallback. Prefer the cache for selective sections; broad queries
need a measured selection policy because caching did not consistently help.
Do not silently rebuild a large cache on every source-version change.

The measured break-even of about 16 queries is for this six-query mix and
instrumented run, including empty/broad cases. For the three short-section
medians alone it is about 13 queries. It excludes subsequent invalidation and
rebuild costs. Two repeats are a local baseline, not a universal speed claim.

Prototype usage (from the isolated checkout):

```powershell
.venv/Scripts/python.exe -m reference.benchmark_section_cache --cloud C:/data/a.las --cloud C:/data/b.las --out C:/scratch/new-section-experiment --repeats 2
```

The output directory must be new. Cell size is 50 source map units and source
chunks are 250,000 points. No production GUI behavior, classifier, surface,
alignment or source LAS data was changed. The latest executable remains the
September 24 c747213 build.
