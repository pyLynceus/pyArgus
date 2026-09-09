"""The strip-adjustment solver: robust Gauss-Newton over patch misfits.

Unknowns:

* three boresight angles, shared by every strip (they live between the
  IMU and the scanner, which does not change per flight line), and/or
* one offset per strip -- vertical by default, 3D on request.

Two datum regimes, chosen by whether ``control`` is given:

* WITHOUT control, strip 0's offset is fixed at zero (the gauge):
  offsets are RELATIVE to the first strip, the absolute datum stays
  where the delivery put it, and tying to the survey is the control
  comparison's job.
* WITH control (surveyed marks the strips must pass through), the
  gauge lifts: EVERY strip gets an offset unknown, the marks anchor
  the absolute datum, and strips without their own marks inherit it
  through the strip-to-strip patches. Control rows carry
  ``control_weight`` so a handful of marks can steer the datum against
  thousands of patches without drowning the relative geometry.

Boresight roll and pitch need opposing headings to separate from plain
offsets, and yaw needs relief or crossing lines; when the geometry
cannot determine the unknowns, the normal matrix is near-singular and
this solver REFUSES rather than returning a confident number from an
indeterminate system -- residuals are not accuracy, and a
solvable-looking answer from bad geometry is exactly the failure
pyLynceus kept catching.

Each iteration rebuilds correspondences (and control observations)
from the corrected coordinates, solves with Huber reweighting, and
stops when the update is negligible. The result records the patch and
control rms before and after; the REFEREE is still
qa.overlap.strip_dz and an independent control comparison, run on the
corrected cloud -- the solver's own numbers prove nothing.
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
    offsets: np.ndarray        # (S, 3); relative to strip 0 unless absolute
    n_observations: int
    iterations: int
    rms_before: float          # patch |d| rms at the first build
    rms_after: float           # patch |d| rms after the last correction
    absolute: bool = False     # True when control anchored the datum
    n_control: int = 0
    control_rms_before: float = None
    control_rms_after: float = None

    def corrected(self, bundles):
        """Corrected coordinates for each bundle, same order as solved."""
        return [corrected_xyz(b, self.boresight, self.offsets[i])
                for i, b in enumerate(bundles)]


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values)))) if values.size else float("nan")


def solve_alignment(bundles, *, solve_boresight=True, offsets="z", cell=5.0,
                    min_points=8, max_rms=None, min_normal_z=0.7,
                    control=None, control_weight=10.0, control_radius=6.0,
                    control_min_points=10, max_iterations=8,
                    tolerance=1e-10):
    """Adjust strips to each other -- and, when ``control`` is given,
    to surveyed marks. Returns an AlignmentResult.

    ``offsets``: "z" (vertical per strip), "xyz", or "none".
    ``control``: (M, 3) surveyed easting/northing/elevation marks in
    the same frame and units as the strips.
    """
    if offsets not in ("z", "xyz", "none"):
        raise ValueError(f'offsets must be "z", "xyz" or "none", got {offsets!r}')
    n_strips = len(bundles)
    if n_strips < 2:
        raise ValueError("alignment needs at least two strips")
    control_active = control is not None
    if control_active:
        control = np.asarray(control, dtype=float)
        if control.ndim != 2 or control.shape[1] != 3:
            raise ValueError(f"control must be (M, 3) e/n/z, got "
                             f"{control.shape}")
    off_dim = {"z": 1, "xyz": 3, "none": 0}[offsets]
    off_strips = (list(range(n_strips)) if control_active and off_dim
                  else list(range(1, n_strips)))
    n_beta = 3 if solve_boresight else 0
    col_of = {s: n_beta + i * off_dim for i, s in enumerate(off_strips)}
    n_params = n_beta + off_dim * len(off_strips)
    if n_params == 0:
        raise ValueError("nothing to solve: boresight off and offsets none")

    beta = np.zeros(3)
    toff = np.zeros((n_strips, 3))
    rms_before = None
    control_rms_before = None
    n_control_obs = 0
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
        ctrl_obs = []
        if control_active:
            for s in range(n_strips):
                co = patches_mod.control_observations(
                    bundles[s], xyz[s], s, control, radius=control_radius,
                    min_points=control_min_points,
                    min_normal_z=min_normal_z)
                if co.d.size:
                    ctrl_obs.append(co)
            n_control_obs = sum(co.d.size for co in ctrl_obs)
            if n_control_obs == 0:
                raise ValueError(
                    "control was given but no mark has enough planar strip "
                    "points within the control radius; the marks never "
                    "touch the strips. Refusing to anchor a datum to "
                    "nothing.")
        d = np.concatenate([c.d for c in obs]
                           + [co.d for co in ctrl_obs])
        if rms_before is None:
            rms_before = _rms(np.concatenate([c.d for c in obs]))
            if ctrl_obs:
                control_rms_before = _rms(
                    np.concatenate([co.d for co in ctrl_obs]))

        rows = d.size
        if rows < n_params + 2:
            raise ValueError(f"{rows} observations cannot determine "
                             f"{n_params} unknowns")
        jac = np.zeros((rows, n_params))
        base_weight = np.ones(rows)
        at = 0
        for c in obs:
            k = c.d.size
            if n_beta:
                jac[at:at + k, :3] = c.j_beta
            if off_dim:
                cols = c.normal[:, 2:3] if off_dim == 1 else c.normal
                if c.a in col_of:
                    j0 = col_of[c.a]
                    jac[at:at + k, j0:j0 + off_dim] = cols
                if c.b in col_of:
                    j0 = col_of[c.b]
                    jac[at:at + k, j0:j0 + off_dim] = -cols
            at += k
        for co in ctrl_obs:
            k = co.d.size
            if n_beta:
                jac[at:at + k, :3] = co.j_beta
            if off_dim and co.strip in col_of:
                cols = co.normal[:, 2:3] if off_dim == 1 else co.normal
                j0 = col_of[co.strip]
                jac[at:at + k, j0:j0 + off_dim] = cols
            base_weight[at:at + k] = control_weight
            at += k

        # Huber IRLS around the linearized solve.
        weights = base_weight.copy()
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
            weights = base_weight * np.minimum(
                1.0, _HUBER * scale / np.maximum(np.abs(residual), 1e-300))

        if n_beta:
            beta = beta + update[:3]
        for s in off_strips:
            j0 = col_of[s]
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
    control_rms_after = None
    if control_active:
        final_ctrl = []
        for s in range(n_strips):
            co = patches_mod.control_observations(
                bundles[s], xyz[s], s, control, radius=control_radius,
                min_points=control_min_points, min_normal_z=min_normal_z)
            if co.d.size:
                final_ctrl.append(co.d)
        control_rms_after = (_rms(np.concatenate(final_ctrl))
                             if final_ctrl else float("nan"))

    return AlignmentResult(boresight=beta, offsets=toff,
                           n_observations=rows, iterations=iterations,
                           rms_before=rms_before, rms_after=rms_after,
                           absolute=bool(control_active and off_dim),
                           n_control=n_control_obs,
                           control_rms_before=control_rms_before,
                           control_rms_after=control_rms_after)
