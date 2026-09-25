"""What the solver does with an error it CANNOT represent.

Every other alignment test injects a boresight and per-strip offsets --
the solver's own unknowns -- and demands recovery. Those prove it can
invert its own model. They cannot catch the failure that matters in
production: a real misalignment that is not in the model's span at all.

A navigation time lag is the case chosen here because it is ordinary.
Points get paired with the trajectory at t + lag, so the cloud carries
an error built from aircraft velocity and attitude rate, and there is
no boresight and no constant offset anywhere in it.

The findings below are measured, not assumed, and they are not
comfortable:

* The solver never refuses. It returns a confident answer with a
  patch rms that improves handsomely, both times.
* It converts the timing error into a BORESIGHT, whose fitted value
  tracks lag * speed / range. A calibration that changes with flight
  altitude is not a calibration -- carried to the next flight it is
  simply wrong.
* When the lag differs between lines, correcting it makes the cloud's
  vertical accuracy about four times WORSE, while the strip-overlap
  referee barely moves.

That last one is the reason CLAUDE.md requires post-adjustment
strip_dz AND independent checkpoint residuals before an alignment is
believed. Here strip overlap says "fine" and the truth says otherwise,
which is exactly the case the two-referee rule exists to catch.
"""

import numpy as np
import pytest

from pyargus.align import solve_alignment
from pyargus.qa import overlap
from tests.synthetic import lagged_strip

# Two opposing lines plus a crossing line: the geometry that makes all
# three boresight angles observable, so a refusal here would be about
# the ERROR being unmodeled rather than about weak geometry.
SPECS = [(0.0, (0.0, 0.0), 200.0),
         (np.pi, (200.0, 25.0), 200.0),
         (np.pi / 2, (100.0, -30.0), 90.0)]

SPEED = 25.0
AGL = 100.0
CELL = 5.0
MIN_POINTS = 6


def lagged_block(lags, seed=0, agl=AGL, speed=SPEED):
    bundles, truths = [], []
    for i, (yaw, origin, length) in enumerate(SPECS):
        bundle, ground = lagged_strip(yaw, origin, length, lag=lags[i],
                                      agl=agl, speed=speed, seed=seed + 10 * i)
        bundles.append(bundle)
        truths.append(ground)
    return bundles, truths


def vertical_rms(xyzs, truths):
    """RMS |dz| against constructed truth -- the referee that does NOT
    come out of the solver's own model."""
    return float(np.sqrt(np.concatenate(
        [(x[:, 2] - t[:, 2]) ** 2 for x, t in zip(xyzs, truths)]).mean()))


def horizontal_rms(xyzs, truths):
    return float(np.sqrt(np.concatenate(
        [((x[:, :2] - t[:, :2]) ** 2).sum(axis=1)
         for x, t in zip(xyzs, truths)]).mean()))


def dz_rmse(xyz_a, xyz_b):
    """The internal referee: strip-to-strip agreement."""
    result = overlap.strip_dz(
        {"x": xyz_a[:, 0], "y": xyz_a[:, 1], "z": xyz_a[:, 2]},
        {"x": xyz_b[:, 0], "y": xyz_b[:, 1], "z": xyz_b[:, 2]},
        cell=CELL, min_points=4)
    return result.summary()["rmse"]


def test_a_nav_lag_is_absorbed_as_boresight_not_refused():
    """A uniform timing error comes back as a confident boresight.

    The solver has no timing unknown, so it spends the one it has: a
    pitch rotation moves the ground point along-track by roughly
    pitch * range, which imitates a lag's velocity * lag shift. The
    fit is good and the number is fiction.
    """
    lag = 0.02
    bundles, truths = lagged_block((lag,) * 3)

    # the error really is unmodeled: almost purely horizontal
    assert horizontal_rms([b.xyz for b in bundles], truths) > 0.4
    assert vertical_rms([b.xyz for b in bundles], truths) < 0.01

    result = solve_alignment(bundles, offsets="z", cell=CELL,
                             min_points=MIN_POINTS)

    # It did not refuse, and it did not return zero: it invented a
    # boresight pitch of about 0.005 rad -- roughly 0.3 degrees -- on
    # data whose true boresight is exactly zero.
    assert abs(result.boresight[1]) > 4e-3
    # and the patch residual improves, so nothing in the solver's own
    # report suggests anything is wrong
    assert result.rms_after < result.rms_before / 3.0


@pytest.mark.parametrize("agl,speed", [(100.0, 25.0), (400.0, 25.0),
                                       (100.0, 50.0)])
def test_the_fitted_boresight_is_the_lag_in_disguise(agl, speed):
    """Proof that the number is geometry, not calibration.

    A real boresight is a property of the sensor mount and does not care
    how high or how fast you fly. This fitted one tracks
    lag * speed / range across a four-fold change in altitude and a
    doubling of speed, which is the signature of a timing error. Fly the
    same faulty aircraft higher and this "calibration" shrinks.
    """
    lag = 0.02
    bundles, _ = lagged_block((lag,) * 3, agl=agl, speed=speed)
    result = solve_alignment(bundles, offsets="z", cell=CELL,
                             min_points=MIN_POINTS)

    predicted = lag * speed / agl
    assert result.boresight[1] == pytest.approx(predicted, rel=0.15)


def test_strip_overlap_alone_would_pass_a_correction_that_hurts():
    """The two-referee rule, earned.

    Lines processed with different lags disagree, so the solver has
    something to fit and fits it. Afterwards the strips agree slightly
    better with EACH OTHER while the cloud's vertical accuracy against
    truth is about four times worse. An acceptance test reading only
    strip_dz would sign this off.
    """
    bundles, truths = lagged_block((0.02, 0.0, 0.01))

    before_vertical = vertical_rms([b.xyz for b in bundles], truths)
    before_dz = dz_rmse(bundles[0].xyz, bundles[1].xyz)

    result = solve_alignment(bundles, offsets="z", cell=CELL,
                             min_points=MIN_POINTS)
    corrected = result.corrected(bundles)

    after_vertical = vertical_rms(corrected, truths)
    after_dz = dz_rmse(corrected[0], corrected[1])

    # REFEREE 1, strip overlap: no meaningful change, and what change
    # there is looks like an improvement
    assert after_dz <= before_dz
    assert after_dz > 0.75 * before_dz

    # REFEREE 2, constructed truth: materially worse
    assert after_vertical > 3.0 * before_vertical


def test_a_common_lag_is_invisible_to_strip_overlap_before_any_solve():
    """Where the internal referee is blind by construction.

    Give every line the same lag and they are all wrong together. Strip
    overlap compares strips to each other, so it sees a well-behaved
    block: its dz median sits near zero while every point in the
    delivery is half a foot from where it belongs. No amount of
    strip_dz can find a common-mode error; only something outside the
    block can.
    """
    bundles, truths = lagged_block((0.02,) * 3)

    result = overlap.strip_dz(
        {"x": bundles[0].xyz[:, 0], "y": bundles[0].xyz[:, 1],
         "z": bundles[0].xyz[:, 2]},
        {"x": bundles[1].xyz[:, 0], "y": bundles[1].xyz[:, 1],
         "z": bundles[1].xyz[:, 2]}, cell=CELL, min_points=4)

    assert abs(result.summary()["median"]) < 0.05
    assert horizontal_rms([b.xyz for b in bundles], truths) > 0.4
