"""The strip-adjustment solver: robust Gauss-Newton over patch misfits.

Unknowns:

* three boresight angles, shared by every strip (they live between the
  IMU and the scanner, which does not change per flight line), and/or
* one offset per strip -- vertical by default, 3D on request.

Gauge: strip 0's offset is fixed at zero, so offsets are RELATIVE to
the first strip and the absolute datum stays where the delivery put it;
tying to the survey datum is the control comparison's job (Phase 2),
not the adjustment's. Boresight roll and pitch need opposing headings
to separate from plain offsets, and yaw needs relief or crossing
lines; when the geometry cannot determine the unknowns, the normal
matrix is near-singular and this solver REFUSES rather than returning
a confident number from an indeterminate system -- residuals are not
accuracy, and a solvable-looking answer from bad geometry is exactly
the failure pyLynceus kept catching.

Each iteration rebuilds correspondences from the corrected
coordinates, solves with Huber reweighting, and stops when the update
is negligible. The result records the patch rms before and after; the
REFEREE is still qa.overlap.strip_dz and the control comparison, run
on the corrected cloud -- the solver's own numbers prove nothing.
"""

from dataclasses import dataclass

import numpy as np

from pyargus.align import patches as patches_mod
from pyargus.align.bundles import corrected_xyz

_HUBER = 1.345
_MAX_CONDITION = 200.0


@dataclass
class AlignmentResult:
    boresight: np.ndarray      # (3,) radians; zeros when not solved
    offsets: np.ndarray        # (S, 3); strip 0 is the gauge, always zero
    n_observations: int
    iterations: int
    rms_before: float          # patch |d| rms at the first build
    rms_after: float           # patch |d| rms after the last correction

    def corrected(self, bundles):
        """Corrected coordinates for each bundle, same order as solved."""
        return [corrected_xyz(b, self.boresight, self.offsets[i])
                for i, b in enumerate(bundles)]


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values)))) if values.size else float("nan")


def solve_alignment(bundles, *, solve_boresight=True, offsets="z", cell=5.0,
                    min_points=8, max_rms=None, min_normal_z=0.7,
                    max_iterations=8, tolerance=1e-10):
    """Adjust strips to each other. Returns an AlignmentResult.

    ``offsets``: "z" (vertical per strip), "xyz", or "none".
    """
    if offsets not in ("z", "xyz", "none"):
        raise ValueError(f'offsets must be "z", "xyz" or "none", got {offsets!r}')
    n_strips = len(bundles)
    if n_strips < 2:
        raise ValueError("alignment needs at least two strips")
    off_dim = {"z": 1, "xyz": 3, "none": 0}[offsets]
    n_beta = 3 if solve_boresight else 0
    n_params = n_beta + off_dim * (n_strips - 1)
    if n_params == 0:
        raise ValueError("nothing to solve: boresight off and offsets none")

    beta = np.zeros(3)
    toff = np.zeros((n_strips, 3))
    rms_before = None
    iterations = 0

    for iteration in range(max_iterations):
        xyz = [corrected_xyz(b, beta, toff[i]) for i, b in enumerate(bundles)]
        obs = []
        for a in range(n_strips):
            for b in range(a + 1, n_strips):
                c = patches_mod.correspondences(
                    bundles[a], bundles[b], xyz[a], xyz[b], a, b,
                    cell=cell, min_points=min_points, max_rms=max_rms,
                    min_normal_z=min_normal_z)
                if c.d.size:
                    obs.append(c)
        if not obs:
            raise ValueError("no usable surface correspondences; strips do "
                             "not overlap at this cell size, or nothing "
                             "planar survives the gates")
        d = np.concatenate([c.d for c in obs])
        if rms_before is None:
            rms_before = _rms(d)

        rows = sum(c.d.size for c in obs)
        if rows < n_params + 2:
            raise ValueError(f"{rows} correspondences cannot determine "
                             f"{n_params} unknowns")
        jac = np.zeros((rows, n_params))
        at = 0
        for c in obs:
            k = c.d.size
            if n_beta:
                jac[at:at + k, :3] = c.j_beta
            if off_dim:
                cols = c.normal[:, 2:3] if off_dim == 1 else c.normal
                if c.a > 0:
                    j0 = n_beta + (c.a - 1) * off_dim
                    jac[at:at + k, j0:j0 + off_dim] = cols
                if c.b > 0:
                    j0 = n_beta + (c.b - 1) * off_dim
                    jac[at:at + k, j0:j0 + off_dim] = -cols
            at += k

        # Huber IRLS around the linearized solve.
        weights = np.ones(rows)
        update = np.zeros(n_params)
        for _ in range(3):
            sq = np.sqrt(weights)[:, None]
            a = jac * sq
            # Observability gate on the COLUMN-SCALED system: raw
            # conditioning mixes radians with map units and hides
            # degeneracy behind unit choice. Measured: a healthy
            # opposing+crossing block scores ~5, two parallel
            # same-heading lines ~2.4e3.
            norms = np.linalg.norm(a, axis=0)
            if np.any(norms < 1e-12):
                raise ValueError(
                    "an unknown has no leverage in these observations; "
                    "this strip geometry does not determine the requested "
                    "unknowns. Refusing to solve.")
            scaled = a / norms
            condition = np.linalg.cond(scaled.T @ scaled)
            if condition > _MAX_CONDITION:
                raise ValueError(
                    f"scaled normal-matrix condition {condition:.1e}: this "
                    f"strip geometry does not determine the requested "
                    f"unknowns (boresight needs opposing headings; yaw "
                    f"needs relief or crossing lines). Refusing to solve.")
            jw = jac * weights[:, None]
            update = np.linalg.solve(jw.T @ jac, jw.T @ d)
            residual = d - jac @ update
            scale = 1.4826 * np.median(np.abs(residual - np.median(residual)))
            if scale <= 0:
                break
            weights = np.minimum(1.0, _HUBER * scale / np.maximum(
                np.abs(residual), 1e-300))

        if n_beta:
            beta = beta + update[:3]
        for s in range(1, n_strips):
            j0 = n_beta + (s - 1) * off_dim
            if off_dim == 1:
                toff[s, 2] += update[j0]
            elif off_dim == 3:
                toff[s] += update[j0:j0 + 3]
        iterations = iteration + 1
        if np.max(np.abs(update)) < tolerance:
            break

    xyz = [corrected_xyz(b, beta, toff[i]) for i, b in enumerate(bundles)]
    final = []
    for a in range(n_strips):
        for b in range(a + 1, n_strips):
            c = patches_mod.correspondences(
                bundles[a], bundles[b], xyz[a], xyz[b], a, b,
                cell=cell, min_points=min_points, max_rms=max_rms,
                min_normal_z=min_normal_z)
            if c.d.size:
                final.append(c.d)
    rms_after = _rms(np.concatenate(final)) if final else float("nan")

    return AlignmentResult(boresight=beta, offsets=toff,
                           n_observations=rows, iterations=iterations,
                           rms_before=rms_before, rms_after=rms_after)
