# Optional spatial section cache: experiment and limits

The cache is an access optimization. Acceptance requires identical selected
point identities, XYZ, classifications, line IDs, counts and bounded sampling
relative to the full-scan implementation; a faster but different answer fails.

Use reference.benchmark_section_cache on separately held inputs, with multiple
narrow and broad corridors, repeated and alternate query orders, and explicit
source identities. Record build cost, cache disk usage, query times, file
access and whole-process memory separately. Warm repeated access does not
establish cold-network performance. Source datasets remain unchanged.

Regression tests cover exact-result behavior, changed/damaged cache handling,
source identity checks and fallback. Real operator acceptance remains scoped
to the chosen project and hardware. Project-specific benchmark records are
retained privately and are not included here.

Caches use XY cells and replay points in source order. Broad queries can fall
back to full scans. Building a cache costs a source pass and additional disk
space; repeated small queries are the intended use. Metadata invalidation is
not a cryptographic guarantee if file size and modification time are preserved.

See SECTION_CACHE_GUI.md for build, cancellation, fallback and cleanup;
AUTO_DETAIL.md covers viewer refinement. ACCELERATION.md describes the separate
OpenGL rendering and CPU morphology experiments.
