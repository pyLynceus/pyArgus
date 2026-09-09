"""Time-dependent corrections: injected drift must be recovered, the
dZ referee must collapse, and constants must demonstrably NOT be
enough on the same data -- otherwise the extra unknowns are theater."""

import numpy as np
import pytest

from pyargus.align import drift as drift_mod
from pyargus.align import solve_alignment
from tests.synthetic import misaligned_strip, rolling_terrain
from tests.test_align import TRUE_BETA, dz_median, flat


def timed_block(seed, drifts=(None, None, None), true_boresight=(0, 0, 0),
                offsets=((0, 0, 0),) * 3, terrain=rolling_terrain):
    """The opposing+crossing block with per-point times; strips start
    at staggered t0 like a real mission."""
    specs = [(0.0, (0.0, 0.0), 200.0, 0.0),
             (np.pi, (200.0, 25.0), 200.0, 30.0),
             (np.pi / 2, (100.0, -30.0), 90.0, 60.0)]
    bundles, truths = [], []
    for i, (yaw, origin, length, t0) in enumerate(specs):
        b, g = misaligned_strip(yaw, origin, length, terrain=terrain,
                                true_boresight=true_boresight,
                                true_offset=offsets[i],
                                true_drift=drifts[i], t0=t0,
                                seed=seed + 10 * i)
        bundles.append(b)
        truths.append(g)
    return bundles, truths


def test_nodes_and_bracket():
    times = np.array([100.0, 130.0, 160.0])
    nodes = drift_mod.nodes_for(times, spacing=25.0)
    assert nodes[0] == 100.0 and nodes[-1] == 160.0
    assert len(nodes) == 4                       # no gap wider than 25 s
    # bracket is the primitive that places every drift observation in
    # the jacobian; pin its (idx, w) against np.interp -- inside the
    # span, at exact node times, and CLAMPED outside both ends
    q = np.array([90.0, 100.0, 110.0, 130.0, 159.9, 160.0, 175.0])
    idx, w = drift_mod.bracket(nodes, q)
    v = np.array([0.0, 1.0, 2.0, 3.0])
    assert idx.min() >= 0 and idx.max() <= len(nodes) - 2
    rec = (1.0 - w) * v[idx] + w * v[idx + 1]
    assert np.allclose(rec, np.interp(q, nodes, v))
    model = drift_mod.DriftModel(node_times=[nodes], values=[v])
    dz = model.offset_at(0, np.array([100.0, 110.0, 160.0]))[:, 2]
    assert np.allclose(dz, [0.0, 0.5, 3.0])
    with pytest.raises(ValueError, match="positive"):
        drift_mod.nodes_for(times, spacing=0.0)


def test_linear_drift_recovered_and_constants_are_not_enough():
    drifts = (None, lambda t: 0.015 * (np.asarray(t) - 30.0), None)
    bundles, truths = timed_block(21, drifts=drifts)
    before = dz_median(bundles[0].xyz, bundles[1].xyz)
    assert before > 0.03                            # the injected wander

    constant = solve_alignment(bundles, solve_boresight=False, offsets="z",
                               min_points=6)
    corrected_const = constant.corrected(bundles)

    result = solve_alignment(bundles, solve_boresight=False,
                             drift_spacing=2.0, min_points=6)
    assert result.drift is not None
    corrected = result.corrected(bundles)
    after = dz_median(corrected[0], corrected[1])
    after_const = dz_median(corrected_const[0], corrected_const[1])
    assert after < 0.01
    # a constant can null the MEDIAN too; the honest contrast is the
    # surface itself: the drift-corrected strip lands on the truth
    dz1 = corrected[1][:, 2] - truths[1][:, 2]
    dz1_const = corrected_const[1][:, 2] - truths[1][:, 2]
    assert np.std(dz1) < 0.03
    assert np.std(dz1_const) > 2.0 * np.std(dz1)
    # recovered drift matches the injected ramp, mean-removed (the
    # gauge absorbs a constant) and over INTERIOR nodes -- end nodes
    # see only half a bracket of data and are legitimately
    # stiffness-damped toward their neighbours
    nt = result.drift.node_times[1]
    values = result.drift.values[1]
    injected = -0.015 * (nt - 30.0)          # solver corrects, so minus
    got = (values - values.mean())[1:-1]
    want = (injected - injected.mean())[1:-1]
    assert np.abs(got - want).max() < 0.01, (got, want)
    # strip 0 is the gauge: its node MEAN is pinned at zero (gauging
    # the wrong strip, or none, moves this)
    assert abs(float(result.drift.values[0].mean())) < 1e-9


def test_sinusoidal_drift_recovered():
    wobble = lambda t: 0.06 * np.sin(2 * np.pi * np.asarray(t) / 6.0)
    bundles, truths = timed_block(22, drifts=(wobble, None, None))
    result = solve_alignment(bundles, solve_boresight=False,
                             drift_spacing=1.0, min_points=6)
    corrected = result.corrected(bundles)
    dz0 = corrected[0][:, 2] - truths[0][:, 2]
    assert np.std(dz0) < 0.025
    lo, hi = result.drift.span(0)
    assert hi - lo > 0.08                        # it really moved


def test_boresight_and_drift_solve_together():
    wobble = lambda t: 0.04 * np.sin(2 * np.pi * np.asarray(t) / 8.0)
    bundles, truths = timed_block(23, drifts=(None, wobble, None),
                                  true_boresight=TRUE_BETA)
    result = solve_alignment(bundles, drift_spacing=2.0, min_points=6)
    err = result.boresight - np.array(TRUE_BETA)
    # pitch couples with drift (along-track dz reads as time within a
    # strip); opposing headings keep it determined but its variance
    # inflates ~3x vs constant mode -- measured, and the tolerance
    # says so
    assert abs(err[0]) < 3e-4 and abs(err[1]) < 6e-4
    corrected = result.corrected(bundles)
    dz1 = corrected[1][:, 2] - truths[1][:, 2]
    assert np.std(dz1) < 0.03


def test_aligned_strips_yield_flat_drift():
    bundles, _ = timed_block(24)
    result = solve_alignment(bundles, solve_boresight=False,
                             drift_spacing=2.0, min_points=6)
    for s in range(3):
        lo, hi = result.drift.span(s)
        assert hi - lo < 0.02, (s, lo, hi)


def test_drift_refusals():
    bundles, _ = timed_block(25)
    with pytest.raises(ValueError, match="vertical"):
        solve_alignment(bundles, drift_spacing=2.0, offsets="xyz",
                        min_points=6)
    stripped = [type(b)(xyz=b.xyz, nav_xyz=b.nav_xyz, rpy=b.rpy)
                for b in bundles]
    with pytest.raises(ValueError, match="times"):
        solve_alignment(stripped, drift_spacing=2.0, min_points=6)
    # non-positive spacing: 0 used to crash with a raw
    # ZeroDivisionError and negative silently solved a 2-node ramp
    for bad in (0.0, -5.0):
        with pytest.raises(ValueError, match="positive"):
            solve_alignment(bundles, drift_spacing=bad, min_points=6)
    # stiffness is what keeps sparsely observed nodes determined;
    # 0/negative would return confident nonsense instead of refusing
    with pytest.raises(ValueError, match="positive"):
        solve_alignment(bundles, drift_spacing=2.0, drift_stiffness=0.0,
                        min_points=6)
    # a node explosion is a refusal, not a memory blowout: stiffness
    # rows regularize but do not observe, so they earn no row credit
    with pytest.raises(ValueError, match="widen"):
        solve_alignment(bundles, drift_spacing=0.005, min_points=6)


def test_degenerate_geometry_refuses_in_drift_mode():
    # same-heading parallel lines over flat terrain cannot determine
    # boresight; the NESTED CONSTANT gate must refuse before stiffness
    # regularization hides the degeneracy (deleting the gate lets this
    # solve "succeed")
    b0, _ = misaligned_strip(0.0, (0.0, 0.0), 200.0, terrain=flat, seed=7)
    b1, _ = misaligned_strip(0.0, (0.0, 25.0), 200.0, terrain=flat, seed=8)
    with pytest.raises(ValueError, match="nested constant"):
        solve_alignment([b0, b1], drift_spacing=2.0, min_points=6)


def test_solution_independent_of_iteration_count():
    # the stiffness/gauge rhs carries the CURRENT penalty residual, so
    # the penalized objective has a true fixed point: the converged
    # curve must not depend on max_iterations, and the tolerance stop
    # must actually fire. (With rhs 0 -- iterated Tikhonov, the panel
    # finding -- the prior decayed every iteration, the curve slid
    # toward the unregularized answer, and every solve burned all
    # max_iterations.) The Huber exemption of stiffness/gauge rows is
    # pinned by documentation only: on clean synthetics the mutation
    # is outcome-invisible (measured); its value is robustness policy.
    wobble = lambda t: 0.06 * np.sin(2 * np.pi * np.asarray(t) / 6.0)
    bundles, _ = timed_block(30, drifts=(wobble, None, None))
    r8 = solve_alignment(bundles, solve_boresight=False, drift_spacing=1.0,
                         min_points=6)
    r24 = solve_alignment(bundles, solve_boresight=False, drift_spacing=1.0,
                          min_points=6, max_iterations=24)
    assert r24.iterations < 24
    for s in range(3):
        assert np.abs(r8.drift.values[s] - r24.drift.values[s]).max() < 1e-6


def test_control_with_drift_anchors_absolute_datum():
    # every strip carries a 0.30 bias plus wander on strip 1: the
    # marks must pull the whole block onto the datum THROUGH the drift
    # solve (strip-to-strip patches can never see the shared bias)
    wobble = lambda t: 0.04 * np.sin(2 * np.pi * np.asarray(t) / 8.0)
    bias = 0.30
    bundles, truths = timed_block(28, drifts=(None, wobble, None),
                                  offsets=((0, 0, bias),) * 3)
    rng = np.random.default_rng(29)
    ce = rng.uniform(30.0, 170.0, 20)
    cn = rng.uniform(-20.0, 20.0, 20)
    control = np.column_stack([ce, cn, rolling_terrain(ce, cn)])
    result = solve_alignment(bundles, solve_boresight=False,
                             drift_spacing=2.0, min_points=6,
                             control=control, control_radius=4.0)
    assert result.absolute and result.drift is not None
    assert result.n_control > 0
    assert result.control_rms_after < 0.02
    corrected = result.corrected(bundles)
    for s in range(3):
        dz = corrected[s][:, 2] - truths[s][:, 2]
        assert abs(float(np.mean(dz))) < 0.02, (s, np.mean(dz))
        # mean correction ~ -0.30 each: the datum is absolute (plane
        # sagitta on this terrain at radius 4 leaves ~0.01-0.03)
        assert abs(result.offsets[s, 2] + bias) < 0.04, (s, result.offsets[s])


def test_unobserved_nodes_follow_their_neighbours():
    # strip 2 (the crossing line) overlaps the others only in the
    # middle of its span; its end nodes see no patches and must stay
    # tied to the observed interior instead of exploding
    bundles, _ = timed_block(26, drifts=(None, None, None))
    result = solve_alignment(bundles, solve_boresight=False,
                             drift_spacing=1.0, min_points=6)
    for s in range(3):
        assert np.max(np.abs(result.drift.values[s])) < 0.05
