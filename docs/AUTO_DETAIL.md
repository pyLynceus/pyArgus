# Automatic local detail

1. Load the intended cloud versions (classified/adjusted files have separate
   cache identities from originals).
2. Click **Build view cache** once. This reuses valid section caches or builds
   local caches for all loaded clouds. It needs disk space and scans each
   uncached source once. Existing QA / cross-sections **Clear all section caches**
   also removes these shared caches.
3. Enable **Auto detail (local cache)**. Navigate normally. After approximately
   0.8 seconds without camera movement, a worker samples the current viewport.
   During navigation the overview is displayed; detailed samples replace it
   only if the camera still matches the request. No camera reset occurs.

Auto detail never builds caches or falls back to source-file scans on its own.
Missing, stale, damaged or busy caches report an error and leave the overview.
Build/rebuild the cache, or use manual Refine for a source-scan fallback.
**Stop loading** cancels work and turns Auto detail off, preventing restart.
The Auto detail setting saves with the workspace; older workspaces default off.

Stereo refinement covers the union of both eye viewports, so Anaglyph can stay
on during automatic or manual refinement. Picking still requires normal viewing.
Depth changes also request a new viewport. The bounded display limit remains
150,000 points; full source geometry and classification are unchanged.

## Validation and limits

Queries reuse the source-order chunk layout and seeded priority sampling of
full-scan refinement. XY tile bounds avoid projecting irrelevant points; actual
Z bounds are read from each local cache chunk (not assumed from LAS headers).
This currently reads cached Z columns across all chunks, so it is not a fully
3D indexed renderer. Broad views may see little speedup. File metadata and
cache manifests are checked before/after, with shared cache locking.

Source identities use size and modification time, not content hashes. Cloud
metadata access can still depend on network availability. Initial overview
loading still scans the source. Cache builds can take time and are cancellable
between chunks. Cache refinement does not alter classifications. Optional GPU
rendering is documented separately in ACCELERATION.md.
