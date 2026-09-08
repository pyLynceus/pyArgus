"""Strip alignment: the custom core, the TerraMatch replacement.

The pieces:

* ``bundles.StripBundle`` -- a strip with per-point navigation state in
  the MAP frame, plus ``corrected_xyz`` applying boresight/offset
  corrections through the georef model.
* ``patches.correspondences`` -- planar-patch point-to-plane misfits in
  strip overlaps: the observations.
* ``solve.solve_alignment`` -- robust Gauss-Newton for shared boresight
  angles and per-strip offsets (gauge: strip 0 fixed). Refuses
  indeterminate geometry instead of returning a confident wrong answer.

Proven by the harness in tests/test_align.py: errors injected through
the forward model must be recovered AND the qa.overlap.strip_dz maps
must collapse -- the solver's own residuals referee nothing.

Applying this to a real SBET still needs the trajectory transformed
into the map frame (projection + geoid); that plumbing is Phase 4.5
and lives outside these modules on purpose. See HANDOFF.md.
"""

from pyargus.align.bundles import StripBundle, corrected_xyz
from pyargus.align.solve import AlignmentResult, solve_alignment

__all__ = ["StripBundle", "corrected_xyz", "AlignmentResult",
           "solve_alignment"]
