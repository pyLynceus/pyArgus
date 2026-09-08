"""Strip alignment: the custom core, Phase 4, not yet implemented.

This is the TerraMatch replacement and the reason the suite exists.
The plan of record:

1. Extract planar patches in strip overlaps (eigenvalue test on local
   neighborhoods; keep only patches both strips observe).
2. Match patch correspondences across strips.
3. Solve sparse least squares for the boresight angles and per-strip
   (later, time-dependent) corrections, linearizing
   ``pyargus.core.georef.ground_points`` against the SBET.
4. Rerun the Phase-2 QA. The solver's own residuals prove nothing;
   only the post-adjustment strip_dz maps and checkpoint residuals do.

Nothing in this package returns an answer until that referee exists in
the loop. No module here may import the GUI or any optional format
dependency.
"""
