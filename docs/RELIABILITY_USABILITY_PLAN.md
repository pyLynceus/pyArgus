# Reliability and usability priorities

Delivered: build identity and job records, original/result versions, per-file
stage attempts, noise preservation, sequential ground batches, compact review
layouts, spatial caches, section stepping, imported linework, saved views and
issues, original/result comparison and offline review export. Optional OpenGL
viewing and bounded CPU tile processing are documented in ACCELERATION.md.

Next work should follow evidence from representative operator reviews:

1. Record usability findings through saved views, issue notes and review exports.
2. Expand renderer acceptance to AMD/Intel hardware and measure access,
   computation and redraw independently.
3. Add restart/resume for interrupted batches while preserving output identity,
   source signatures, completed attempts and explicit review status.
4. Extend active-result version handling consistently to more processing stages.
5. Improve indexed access only where profiling justifies it; preserve counts,
   source indices, exact geometry and stale-cache detection.
6. Continue independent accuracy, terrain and breakline acceptance rather than
   equating a successful job or solver residual with an accepted delivery.

See GUI_STATUS.md and CAPABILITY_ACCEPTANCE.md for current scope. Keep other
checkouts, their environments and original datasets unchanged. Run heavy checks
serially and preserve tested source/build provenance.
