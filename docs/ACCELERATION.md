# GPU viewing and CPU tile processing — October 8, 2026

The Codex branch now supports OpenGL rendering and concurrent CPU morphology
for tiled ground classification. QA aggregation, alignment and batch flight
scheduling retain their existing execution paths. Python remains the application
language; OpenGL shaders render display samples and SciPy computes tile surfaces.

## Viewing controls

Choose **View > Renderer > Auto**, or use the toolbar's **Renderer** menu.
Auto tries hardware OpenGL 3.3 and falls back to the CPU renderer on a missing
dependency, unavailable driver or rendering error. The bottom status bar
identifies the actual device or gives the fallback reason. Choosing GPU retries
initialization; it also falls back visibly if unavailable. CPU is an explicit
reference/compatibility option. The choice is saved with the workspace view.

GPU rendering covers point projection, point visibility/depth, stereo eye
depth buffers, and imported linework. Existing camera gestures, filters, issue
pins, corridors and source-indexed point inspection remain available. Point
picking uses the original double-precision display sample, generated on demand.
Anaglyph still requires turning stereo off for unambiguous point picking.

Coordinates are converted to float32 only after subtracting a local origin
in float64. Camera-center offsets are also computed relative to this origin.
Raw State Plane coordinates never enter a float32 GPU buffer. The display and
depth buffer are visual approximations; exported coordinates remain unchanged.
Only the existing bounded display sample is uploaded, not the full source cloud.

The renderer uses an offscreen OpenGL framebuffer copied into the existing Tk
canvas. Image readback, Tk presentation, some overlays and file access still cost
CPU time. This is not a native OpenGL window or GPU classification pipeline.
ModernGL and glcontext are optional GPU dependencies, included in development
and Windows builds. Unsupported systems retain the CPU viewer.

## Ground classification controls

In **Process > Classify**, choose **Tiled / multicore** under Processing.
Set CPU workers, Tile memory budget (MiB), and optionally Tile width in source
map units. The GUI starts at two workers and a 4,096 MiB estimated budget;
the CLI retains its serial default for compatibility:

    pyargus classify-ground input.las --out output.las --tiled --workers 2 --memory-mb 4096 --cell 3 --window 60 --threshold 1.5

A tile width may be supplied with --tile-size; halo settings and their
conservative defaults are unchanged. One tile uses one worker. Small projects
can fit inside one default tile, in which case there is no tile parallelism.
Smaller tiles can increase overlapping work and repeated reads, so more workers
or smaller tiles do not guarantee faster end-to-end processing.

Readers run serially on the job thread. Only independent SciPy ground-surface
computations run in the thread pool, because native morphology releases the
Python GIL. Workers return core rasters; assembly retains tile order and the
existing lattice, candidate/noise policy, halo reach and labeling rule. Point
labeling and output writes remain streamed and serial. Entire-project batches
still run flights sequentially and may use tile workers within each flight.

The scheduler bounds the number of admitted tile tasks and uses a conservative
working-set estimate (96 bytes per candidate point plus 128 bytes per halo cell,
and the global output rasters). It waits before admitting another tile if this
estimate would exceed the budget. This is not a hard operating-system RSS limit:
one tile's read/selection buffers, decoder buffers, native allocator retention
and other application activity are additional. If one tile exceeds the budget
in a requested parallel run, increase the budget or reduce the tile width.

Stop is checked at tile boundaries, while awaiting results, between streaming
read chunks, and before writing/publishing. A running native morphology call
must finish before its worker can shut down. Cancelled/failed runs clean up the
pool and staging directory and retain a terminal job record. They do not publish
a cloud or promote a nonexistent result. Worker count, budget and measured task
admission statistics are included in the classification record.

## Measured experiment

Workstation: DESKTOP-DQMSN4T, NVIDIA RTX A4000, Windows 11 build 26200.
Synthetic seeded data; these are performance measurements, not accuracy checks
on a production survey or a cold network-load benchmark.

| Test | CPU/serial | GPU/two workers | Relative time |
|---|---:|---:|---:|
| 150,000-point normal redraw | 58.12 ms | 12.10 ms | 4.80x faster |
| 150,000-point anaglyph redraw | 84.62 ms | 15.68 ms | 5.40x faster |
| 300,000-point tiled morphology | 1.703 s | 0.881 s | 1.93x faster |

Redraw medians include framebuffer readback and Tk idle presentation, using
20 measured frames after four warm-up frames per mode. Canvas: 920 x 686.
The morphology comparison used three repeats with alternating worker order,
16 tiles, a 30-unit window and identical DEM, slope and classification masks.
Two-worker CPU-time/wall-time ratios were 1.95–1.97, confirming concurrent CPU
execution. Source-file I/O was excluded from that morphology measurement.

Harness: devtools/benchmark_acceleration.py.
Raw evidence: build/acceleration-20261008/benchmark.json.
Synthetic seam, failure, cancellation, memory-admission, GPU occlusion, precision,
linework, stereo and GUI integration checks live in the regression suite.
The Summerville tiled acceptance run now requests two workers and retains the
previous expected values; release validation is recorded separately.

Only the NVIDIA workstation has been exercised here. AMD/Intel use the same
OpenGL path but still need hardware acceptance on those machines.

## Principles and implementation sources

- ModernGL context, buffers and shader interface:
  https://moderngl.readthedocs.io/en/latest/reference/context.html
- Framebuffer readback and independent depth attachments:
  https://moderngl.readthedocs.io/en/latest/reference/framebuffer.html
- Platform OpenGL context providers:
  https://github.com/moderngl/glcontext/blob/main/README.md
- Python executor behavior and shutdown:
  https://docs.python.org/3.11/library/concurrent.futures.html
- Existing SMRF/halo mathematics and numerical references:
  pyargus/classify/ground.py, pyargus/classify/tiles.py and the project
  mathematics documentation. This change preserves those algorithms.

## Release validation

All 586 source tests passed with no skips. All 73 reference checks passed under
reference/reports/validation-20261008T213859Z-37992, including zero written
classification mismatches between whole-cloud and two-worker tiled Summerville.
The frozen entry adds actual two-worker output and GPU-required normal/stereo
checks on supported hardware. Its JSON report is requested with --self-test-report.
Installation/relocation results accompany the October 8 installer.
