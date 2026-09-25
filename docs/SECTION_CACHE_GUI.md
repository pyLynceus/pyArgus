# Cross-section cache in the GUI

1. Load project clouds and open **QA / cross-sections → Clouds and cross-sections**.
2. Choose **Section source**: one cloud or **Compare all loaded clouds**.
3. Click **Build section cache** once. The status line reports file/point
   progress and elapsed time. **Stop** cancels; completed files can be reused.
4. Keep **Use cache when available** checked and extract sections normally.
   The cache status reports **Spatial cache** or **Full scan** with a reason.
5. Uncheck the option to force the original full scan. **Clear all section
   caches** removes recognized local section caches across projects, including
   retained source versions; it never removes LAS/LAZ inputs or project outputs.

The checkbox is session-local. Caches persist across launches and are found
from the selected source identity. No cache is built automatically, and a
changed/activated cloud version does not silently trigger a rebuild.

## Storage and safety

Default location: `%LOCALAPPDATA%/pyArgus-Codex/section-cache-v2` on Windows.
The build checks available space conservatively (128 bytes per source point
plus a 256 MiB reserve). Actual caches usually use less; the real-data
experiment used about 0.8 GiB for about 25 million points. No automatic eviction occurs;
use Clear all section caches to reclaim space. Unknown files in that directory
are retained. Abandoned recognized staging folders can also be cleared.

Missing, stale, damaged or busy caches fall back to full scanning. Existing
GUI source-change checks still require reloading a cloud changed since it was
loaded; fallback never bypasses that check. Cancelled extraction remains
cancelled instead of starting a scan. Manifest checksums and chunk metadata
are validated. Source invalidation uses resolved path, size and nanosecond
mtime; it cannot detect deliberate content changes that preserve metadata.
This is a performance cache, not an accuracy or provenance certificate.

A process lock prevents cooperating app instances from clearing/building a
cache during a cached query. A crashed process releases the OS lock. Cache
builds publish only completed per-file directories; an interrupted multi-file
build retains previously completed files and removes its current staging data.

Queries predicted to touch more than 35% of the cached source points use a
full scan. This is a conservative heuristic from the experiment, not a promise
of optimal performance for every sensor, coordinate system or storage device.
The fixed spatial cell is 50 source map units. Classifications, coordinates,
original indices and existing section sampling behavior are preserved.

This feature accelerates section extraction only. It does not add cached
viewer loading, a GPU renderer, automatic batch resumption or classification
changes. Earlier experimental v1 cache folders are not imported into v2.
