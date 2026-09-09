"""The strip-adjustment solver: robust Gauss-Newton over patch misfits.

Unknowns:

* three boresight angles, shared by every strip (they live between the
  IMU and the scanner, which does not change per flight line), and/or
* one offset per strip -- vertical by default, 3D on request -- OR,
  with ``drift_spacing``, a piecewise-linear VERTICAL correction in
  time per strip (see align.drift): the TerraMatch-"fluctuating"
  answer to GNSS wander within a line. Drift replaces the constant
  offsets (a constant is the special case of equal nodes), requires
  per-point times on every bundle, and adds stiffness rows tying
  neighboring nodes so unobserved nodes follow their neighbors.
  Solving boresight AND drift at once is allowed but couples pitch
  with the per-strip curves: over smooth terrain, pitch's along-track
  dz signature is a slow function of time that each strip's drift can
  absorb, with only stiffness resisting (measured at Summerville
  scale: 1.2e-3 rad pitch leak, worse than the injected pitch --
  and a constant solve on the same wandering block is just as
  poisoned). The workflow reality requires is the TerraMatch one:
  calibrate boresight on CLEAN lines, then solve drift on the
  wandering flight with solve_boresight=False and the calibration
  held. reference/alignment_proof.py measures all three ways.

Two datum regimes, chosen by whether ``control`` is given:

* WITHOUT control, strip 0 is the gauge: its offset is fixed at zero
  (constant mode) or its nodes are constrained to zero MEAN (drift
  mode) -- relative corrections only, the absolute datum stays where
  the delivery put it. In drift mode the relativity runs deeper:
  patches observe only DIFFERENCES of drift curves, so the
  time-varying common mode of overlapping strips is decided by the
  stiffness prior, which SPLITS a one-strip wander between the strips
  (measured: half and half on a two-strip block). The strip dZ still
  collapses either way; put marks in the solve when it matters which
  strip actually moved.
* WITH control (surveyed marks the strips must pass through), the
  gauge lifts and the marks anchor the absolute datum; strips without
  their own marks inherit it through the strip-to-strip patches.
  Control rows carry ``control_weight``.

Boresight roll and pitch need opposing headings to separate from plain
offsets, and yaw needs relief or crossing lines; when the geometry
cannot determine the unknowns, the normal matrix is near-singular and
this solver REFUSES rather than returning a confident number from an
indeterminate system. The observability gate is COLUMN-SCALED
conditioning (raw conditioning hides degeneracy behind the
radians-vs-feet unit disparity). Drift mode judges observability on
the NESTED CONSTANT system built from the same observations -- the
stiffness rows regularize the drift system itself, dragging degenerate
geometry's conditioning down toward healthy (measured; no safe gate
exists there), while equal nodes ARE a constant, so a geometry that
cannot determine constants cannot determine drift either.

Huber reweighting applies to DATA rows only. Stiffness and gauge rows
keep their weights: a robust loop that downweights stiffness residuals
would un-regularize exactly the segments that drift most.

Each iteration rebuilds correspondences (and control observations)
from the corrected coordinates and stops when the update is
negligible. The result records patch and control rms before and
after; the REFEREE is still qa.overlap.strip_dz and an independent
control comparison on the corrected cloud -- the solver's own numbers
prove nothing.
"""

from dataclasses import dataclass

import numpy as np

from pyargus.align import drift as drift_mod
from pyargus.align import patches as patches_mod
from pyargus.align.bundles import corrected_xyz

_HUBER = 1.345
_MAX_CONDITION = 200.0
# Drift systems are REGULARIZED by their stiffness rows, which drags a
# genuinely degenerate geometry's conditioning down toward a healthy
# one's (measured: healthy 1.1e5 vs parallel-flat-degenerate 2.6e5 --
# no safe gate exists there). Observability is therefore judged on the
# NESTED CONSTANT system built from the same observations (equal nodes
# = a constant, so if constants are indeterminate, drift is too), with
# the proven 200 threshold; the drift solve itself keeps only a
# numerical-breakdown bound.
_MAX_CONDITION_DRIFT_SANITY = 1e12
_GAUGE_WEIGHT = 1e3


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
    drift: object = None       # DriftModel when drift_spacing was solved
                               # (offsets then hold each strip's MEAN dz)

    def corrected(self, bundles):
        """Corrected coordinates for each bundle, same order as solved."""
        out = []
        for i, bundle in enumerate(bundles):
            if self.drift is not None:
                offset = self.drift.offset_at(i, bundle.times)
            else:
                offset = self.offsets[i]
            out.append(corrected_xyz(bundle, self.boresight, offset))
        return out


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values)))) if values.size else float("nan")


def _constant_observability_gate(obs, ctrl_obs, n_strips, n_beta,
                                 control_active, control_weight):
    """Judge drift-mode observability on the nested constant system."""
    off_strips = (list(range(n_strips)) if control_active
                  else list(range(1, n_strips)))
    col_of = {s: n_beta + i for i, s in enumerate(off_strips)}
    n_params = n_beta + len(off_strips)
    rows = sum(c.d.size for c in obs) + sum(co.d.size for co in ctrl_obs)
    jac = np.zeros((rows, n_params))
    weight = np.ones(rows)
    at = 0
    for c in obs:
        k = c.d.size
        if n_beta:
            jac[at:at + k, :3] = c.j_beta
        if c.a in col_of:
            jac[at:at + k, col_of[c.a]] = c.normal[:, 2]
        if c.b in col_of:
            jac[at:at + k, col_of[c.b]] = -c.normal[:, 2]
        at += k
    for co in ctrl_obs:
        k = co.d.size
        if n_beta:
            jac[at:at + k, :3] = co.j_beta
        if co.strip in col_of:
            jac[at:at + k, col_of[co.strip]] = co.normal[:, 2]
        weight[at:at + k] = control_weight
        at += k
    a = jac * np.sqrt(weight)[:, None]
    norms = np.linalg.norm(a, axis=0)
    if np.any(norms < 1e-12):
        raise ValueError(
            "an unknown has no leverage in these observations; this strip "
            "geometry does not determine the requested unknowns. "
            "Refusing to solve.")
    scaled = a / norms
    condition = np.linalg.cond(scaled.T @ scaled)
    if condition > _MAX_CONDITION:
        raise ValueError(
            f"scaled normal-matrix condition {condition:.1e} on the nested "
            f"constant system: this strip geometry does not determine the "
            f"requested unknowns (boresight needs opposing headings; yaw "
            f"needs relief or crossing lines), and adding drift nodes "
            f"cannot help. Refusing to solve.")


def _drift_offsets(model, bundles):
    return [model.offset_at(i, b.times) for i, b in enumerate(bundles)]


def solve_alignment(bundles, *, solve_boresight=True, offsets="z", cell=5.0,
                    min_points=8, max_rms=None, min_normal_z=0.7,
                    control=None, control_weight=10.0, control_radius=6.0,
                    control_min_points=10, drift_spacing=None,
                    drift_stiffness=1.0, max_iterations=8,
                    tolerance=1e-10):
    """Adjust strips to each other -- and, when ``control`` is given,
    to surveyed marks. Returns an AlignmentResult.

    ``offsets``: "z" (vertical per strip), "xyz", or "none".
    ``control``: (M, 3) surveyed easting/northing/elevation marks in
    the same frame and units as the strips.
    ``drift_spacing`` (seconds): solve a piecewise-linear vertical
    correction in time per strip instead of constants; needs
    per-point ``times`` on every bundle. ``drift_stiffness`` weights
    the smoothness penalty on the curve's rate of change (scaled by
    1/sqrt(node step), so the strength does not depend on the spacing
    chosen); it acts on the accumulated curve, not the per-iteration
    update. Both must be positive.
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

    drift_active = drift_spacing is not None
    if drift_active:
        if drift_spacing <= 0:
            raise ValueError(f"drift_spacing must be positive seconds, "
                             f"got {drift_spacing}")
        if drift_stiffness <= 0:
            raise ValueError(
                f"drift_stiffness must be positive, got {drift_stiffness}: "
                f"the stiffness rows are what keep sparsely observed nodes "
                f"determined, and without them the solver would return "
                f"confident nonsense instead of refusing")
        if offsets != "z":
            raise ValueError('drift solving is vertical: offsets must stay '
                             '"z" (the default)')
        if any(b.times is None for b in bundles):
            raise ValueError("drift solving needs per-point times on every "
                             "bundle (attach supplies them; synthetic "
                             "bundles must carry times=)")
        node_times = [drift_mod.nodes_for(b.times, drift_spacing)
                      for b in bundles]
        node_col = []
        at = 3 if solve_boresight else 0
        for nt in node_times:
            node_col.append(at)
            at += len(nt)
        n_node_params = at - (3 if solve_boresight else 0)

    off_dim = {"z": 1, "xyz": 3, "none": 0}[offsets]
    n_beta = 3 if solve_boresight else 0
    if drift_active:
        n_params = n_beta + n_node_params
        col_of = {}
    else:
        off_strips = (list(range(n_strips)) if control_active and off_dim
                      else list(range(1, n_strips)))
        col_of = {s: n_beta + i * off_dim for i, s in enumerate(off_strips)}
        n_params = n_beta + off_dim * len(off_strips)
    if n_params == 0:
        raise ValueError("nothing to solve: boresight off and offsets none")

    beta = np.zeros(3)
    toff = np.zeros((n_strips, 3))
    model = (drift_mod.DriftModel(node_times=node_times,
                                  values=[np.zeros(len(nt))
                                          for nt in node_times])
             if drift_active else None)
    rms_before = None
    control_rms_before = None
    n_control_obs = 0
    iterations = 0

    for iteration in range(max_iterations):
        if drift_active:
            per_point = _drift_offsets(model, bundles)
            xyz = [corrected_xyz(b, beta, per_point[i])
                   for i, b in enumerate(bundles)]
        else:
            xyz = [corrected_xyz(b, beta, toff[i])
                   for i, b in enumerate(bundles)]
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
        if drift_active:
            _constant_observability_gate(obs, ctrl_obs, n_strips, n_beta,
                                         control_active, control_weight)
        d_data = np.concatenate([c.d for c in obs]
                                + [co.d for co in ctrl_obs])
        if rms_before is None:
            rms_before = _rms(np.concatenate([c.d for c in obs]))
            if ctrl_obs:
                control_rms_before = _rms(
                    np.concatenate([co.d for co in ctrl_obs]))

        n_data = d_data.size
        aux_rows = 0
        if drift_active:
            aux_rows += sum(len(nt) - 1 for nt in node_times)
            if not control_active:
                aux_rows += 1
        rows = n_data + aux_rows
        # stiffness rows regularize but do not OBSERVE, so drift mode
        # gets no row credit for them (with the credit the node count
        # cancels algebraically and no spacing ever refuses)
        needed = n_params + 2 if drift_active else n_params + 2 - aux_rows
        if n_data < needed:
            hint = (f"; widen drift_spacing (currently {drift_spacing} s)"
                    if drift_active else "")
            raise ValueError(f"{n_data} observations cannot determine "
                             f"{n_params} unknowns{hint}")
        jac = np.zeros((rows, n_params))
        rhs = np.zeros(rows)
        rhs[:n_data] = d_data
        base_weight = np.ones(rows)
        huber_row = np.zeros(rows, dtype=bool)
        huber_row[:n_data] = True

        def place_strip(row_slice, strip, cols, t=None, sign=1.0):
            """Offset/drift columns for one strip over a row block."""
            if drift_active:
                nt = node_times[strip]
                idx, w = drift_mod.bracket(nt, t)
                base = node_col[strip]
                k = row_slice.stop - row_slice.start
                r = np.arange(row_slice.start, row_slice.stop)
                colz = cols[:, 0] if cols.ndim == 2 else cols
                jac[r, base + idx] += sign * colz * (1.0 - w)
                jac[r, base + idx + 1] += sign * colz * w
            elif off_dim and strip in col_of:
                j0 = col_of[strip]
                jac[row_slice, j0:j0 + off_dim] += sign * cols

        at = 0
        for c in obs:
            k = c.d.size
            sl = slice(at, at + k)
            if n_beta:
                jac[sl, :3] = c.j_beta
            cols = c.normal[:, 2:3] if (off_dim == 1 or drift_active) \
                else c.normal
            place_strip(sl, c.a, cols, t=c.t_a, sign=+1.0)
            place_strip(sl, c.b, cols, t=c.t_b, sign=-1.0)
            at += k
        for co in ctrl_obs:
            k = co.d.size
            sl = slice(at, at + k)
            if n_beta:
                jac[sl, :3] = co.j_beta
            cols = co.normal[:, 2:3] if (off_dim == 1 or drift_active) \
                else co.normal
            place_strip(sl, co.strip, cols, t=co.t, sign=+1.0)
            base_weight[sl] = control_weight
            at += k
        if drift_active:
            for s, nt in enumerate(node_times):
                base = node_col[s]
                # weight ~ 1/sqrt(step): the summed squared penalty then
                # approximates an integral of the squared rate of change,
                # so refining drift_spacing does not dilute the smoothing
                w_s = drift_stiffness / np.sqrt(nt[1] - nt[0])
                vals = model.values[s]
                for k in range(len(nt) - 1):
                    jac[at, base + k] = -w_s
                    jac[at, base + k + 1] = w_s
                    # the rhs carries the CURRENT penalty residual, so the
                    # pseudo-observation constrains the accumulated curve.
                    # With rhs 0 it would constrain each iteration's
                    # increment instead -- iterated Tikhonov, where the
                    # prior decays every iteration and the answer depends
                    # on max_iterations (panel finding, measured).
                    rhs[at] = -w_s * (vals[k + 1] - vals[k])
                    at += 1
            if not control_active:
                base = node_col[0]
                count = len(node_times[0])
                jac[at, base:base + count] = _GAUGE_WEIGHT / count
                rhs[at] = -_GAUGE_WEIGHT * float(model.values[0].mean())
                at += 1
        assert at == rows

        # Huber IRLS around the linearized solve (data rows only).
        weights = base_weight.copy()
        update = np.zeros(n_params)
        for _ in range(3):
            sq = np.sqrt(weights)[:, None]
            a = jac * sq
            norms = np.linalg.norm(a, axis=0)
            if np.any(norms < 1e-12):
                raise ValueError(
                    "an unknown has no leverage in these observations; "
                    "this strip geometry does not determine the requested "
                    "unknowns. Refusing to solve.")
            scaled = a / norms
            condition = np.linalg.cond(scaled.T @ scaled)
            gate = (_MAX_CONDITION_DRIFT_SANITY if drift_active
                    else _MAX_CONDITION)
            if condition > gate:
                raise ValueError(
                    f"scaled normal-matrix condition {condition:.1e}: this "
                    f"strip geometry does not determine the requested "
                    f"unknowns (boresight needs opposing headings; yaw "
                    f"needs relief or crossing lines). Refusing to solve.")
            # solve in the SCALED space the condition gate measured;
            # the unscaled normal matrix can be orders of magnitude
            # worse conditioned than the gated one
            update = np.linalg.solve(
                scaled.T @ scaled,
                scaled.T @ (rhs * np.sqrt(weights))) / norms
            residual = rhs - jac @ update
            data_res = residual[huber_row]
            scale = 1.4826 * np.median(np.abs(data_res
                                              - np.median(data_res)))
            if scale <= 0:
                break
            robust = np.ones(rows)
            robust[huber_row] = np.minimum(
                1.0, _HUBER * scale / np.maximum(np.abs(data_res), 1e-300))
            weights = base_weight * robust

        if n_beta:
            beta = beta + update[:3]
        if drift_active:
            for s in range(n_strips):
                count = len(node_times[s])
                base = node_col[s]
                model.values[s] = model.values[s] + update[base:base + count]
        else:
            for s in col_of:
                j0 = col_of[s]
                if off_dim == 1:
                    toff[s, 2] += update[j0]
                elif off_dim == 3:
                    toff[s] += update[j0:j0 + 3]
        iterations = iteration + 1
        if np.max(np.abs(update)) < tolerance:
            break

    if drift_active:
        per_point = _drift_offsets(model, bundles)
        xyz = [corrected_xyz(b, beta, per_point[i])
               for i, b in enumerate(bundles)]
        for s in range(n_strips):
            toff[s, 2] = float(model.values[s].mean())
    else:
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
                           n_observations=n_data, iterations=iterations,
                           rms_before=rms_before, rms_after=rms_after,
                           absolute=bool(control_active
                                         and (off_dim or drift_active)),
                           n_control=n_control_obs,
                           control_rms_before=control_rms_before,
                           control_rms_after=control_rms_after,
                           drift=model)
