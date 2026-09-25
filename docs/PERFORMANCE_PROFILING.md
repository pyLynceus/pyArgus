# Repeatable workflow profiling

Run from the isolated checkout with its environment:

```powershell
.venv/Scripts/python.exe -m reference.profile_workflow --cloud C:/data/flight1.las --cloud C:/data/flight2.las --out C:/scratch/new-benchmark --repeats 2 --production
```

The output directory must not exist. Source LAS/LAZ files are read-only.
The harness creates verified SHA-256 local copies and alternates original/local
order between repeats. It records metadata before/after, copy durations,
Python/platform/source commit, harness hash, parameters, cProfile files and
an incrementally saved report.json. It does not load or save a GUI workspace.

Default operations: chunk scan, overview sampling, fixed section extraction,
viewport refinement and a fixed-size viewer redraw sweep. `--production`
adds whole-cloud classification per input and disk-backed QA on the new
classified benchmark copies. Those results are experimental timing artifacts;
they must not be treated as accepted deliverables or promoted project inputs.

## Interpreting results

- The local copy and hash checks warm caches. These are warm/repeated-access
  measurements; they cannot establish cold-network or cold-disk speed.
- cProfile adds overhead. CPU time includes all process threads; subtracting
  it from elapsed time does not directly measure network wait.
- Windows RSS is sampled every 25 ms for the entire process, not just arrays
  belonging to an operation. Retained allocator memory affects later baselines.
- Function cumulative times overlap. Do not add parent and child times.
- QA reads local generated clouds in both variants, forces the disk-backed
  path, and omits trajectories/control. It does not benchmark all QA modes.
- Redraw reports actual canvas dimensions and rejects an unlaid-out canvas.
  It measures draw plus idle updates for the existing bounded display sample,
  not full-cloud rendering, input latency, or GPU frame timing.
- Classification uses the existing defaults in map units. On an unfamiliar
  dataset, performance results do not establish appropriate classification
  settings, ground quality, CRS correctness or alignment accuracy.

Run heavy benchmarks and test suites serially. Retain the JSON and profiles
with the resulting report. A failed run has no completed status; do not
present its partial measurements as a completed benchmark.

## Migration rule

First fix repeated work and access patterns. Add a compiled implementation
only where profiles show a suitable bottleneck and numerical/output-equivalence
checks protect behavior. A Python call into a compiled SciPy kernel is not
evidence that translating the caller into Rust or C++ will improve that kernel.

Spatial-cache follow-up: [experiment results](SECTION_CACHE_EXPERIMENT.md).
