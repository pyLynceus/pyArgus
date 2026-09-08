"""The Phase-4 proof harness: injected errors must be recovered AND the
strip-dZ referee must confirm on the corrected cloud."""

import numpy as np
import pytest

from pyargus.align import solve_alignment
from pyargus.qa import overlap
from tests.synthetic import misaligned_strip, rolling_terrain

TRUE_BETA = (0.0010, -0.0015, 0.0030)


def flat(x, y):
    return np.full_like(np.asarray(x, dtype=float), 100.0)


def three_line_block(seed, true_boresight=(0, 0, 0), offsets=((0, 0, 0),) * 3,
                     terrain=rolling_terrain):
    """Two opposing lines plus a crossing line -- the geometry that
    makes all three boresight angles observable."""
    specs = [(0.0, (0.0, 0.0), 200.0),
             (np.pi, (200.0, 25.0), 200.0),
             (np.pi / 2, (100.0, -30.0), 90.0)]
    bundles, truths = [], []
    for i, (yaw, origin, length) in enumerate(specs):
        b, g = misaligned_strip(yaw, origin, length, terrain=terrain,
                                true_boresight=true_boresight,
                                true_offset=offsets[i], seed=seed + 10 * i)
        bundles.append(b)
        truths.append(g)
    return bundles, truths


def dz_median(xyz_a, xyz_b):
    a = {"x": xyz_a[:, 0], "y": xyz_a[:, 1], "z": xyz_a[:, 2]}
    b = {"x": xyz_b[:, 0], "y": xyz_b[:, 1], "z": xyz_b[:, 2]}
    return abs(overlap.strip_dz(a, b, cell=5.0, min_points=4).summary()["median"])


def test_vertical_offsets_recovered_and_dz_collapses():
    bundles, _ = three_line_block(1, offsets=((0, 0, 0), (0, 0, 0.05),
                                              (0, 0, -0.03)), terrain=flat)
    assert dz_median(bundles[0].xyz, bundles[1].xyz) > 0.04
    result = solve_alignment(bundles, solve_boresight=False, offsets="z",
                             min_points=6)
    assert abs(result.offsets[1, 2] + 0.05) < 0.005
    assert abs(result.offsets[2, 2] - 0.03) < 0.005
    corrected = result.corrected(bundles)
    assert dz_median(corrected[0], corrected[1]) < 0.005
    assert result.rms_after < result.rms_before


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_boresight_recovered_across_seeds(seed):
    bundles, truths = three_line_block(seed, true_boresight=TRUE_BETA)
    result = solve_alignment(bundles, solve_boresight=True, offsets="z",
                             min_points=6)
    err = result.boresight - np.array(TRUE_BETA)
    assert abs(err[0]) < 2e-4 and abs(err[1]) < 2e-4, err
    assert abs(err[2]) < 1.5e-3, err
    # the referee: the corrected strip 0 lands on the true ground
    corrected = result.corrected(bundles)
    dz = corrected[0][:, 2] - truths[0][:, 2]
    assert np.sqrt(np.mean(dz ** 2)) < 0.06


def test_combined_boresight_and_offsets():
    bundles, _ = three_line_block(
        4, true_boresight=TRUE_BETA,
        offsets=((0, 0, 0), (0, 0, 0.08), (0, 0, -0.05)))
    result = solve_alignment(bundles, min_points=6)
    assert abs(result.boresight[0] - TRUE_BETA[0]) < 2e-4
    assert abs(result.boresight[1] - TRUE_BETA[1]) < 2e-4
    assert abs(result.offsets[1, 2] + 0.08) < 0.01
    assert abs(result.offsets[2, 2] - 0.05) < 0.01
    corrected = result.corrected(bundles)
    assert dz_median(corrected[0], corrected[1]) < 0.01


def test_aligned_strips_yield_near_zero_corrections():
    bundles, _ = three_line_block(5)
    result = solve_alignment(bundles, min_points=6)
    assert np.max(np.abs(result.boresight)) < 1e-4
    assert np.max(np.abs(result.offsets)) < 0.01


def test_outliers_are_downweighted():
    bundles, _ = three_line_block(6, true_boresight=TRUE_BETA)
    # a parked truck: raise a block of strip 1 by 1.5
    xyz = bundles[1].xyz
    hit = ((xyz[:, 0] > 90) & (xyz[:, 0] < 100)
           & (xyz[:, 1] > 30) & (xyz[:, 1] < 40))
    xyz[hit, 2] += 1.5
    result = solve_alignment(bundles, min_points=6)
    err = result.boresight - np.array(TRUE_BETA)
    assert abs(err[0]) < 3e-4 and abs(err[1]) < 3e-4


def test_refuses_underdetermined_geometry():
    # two parallel lines, SAME heading: roll folds into the offset and
    # pitch cancels -- the solver must refuse, not answer.
    b0, _ = misaligned_strip(0.0, (0.0, 0.0), 200.0, terrain=flat, seed=7)
    b1, _ = misaligned_strip(0.0, (0.0, 25.0), 200.0, terrain=flat, seed=8)
    with pytest.raises(ValueError, match="does not determine"):
        solve_alignment([b0, b1], solve_boresight=True, offsets="z",
                        min_points=6)


def test_refuses_no_overlap_and_single_strip():
    b0, _ = misaligned_strip(0.0, (0.0, 0.0), 100.0, seed=9)
    b1, _ = misaligned_strip(0.0, (0.0, 500.0), 100.0, seed=10)
    with pytest.raises(ValueError, match="correspondences"):
        solve_alignment([b0, b1], min_points=6)
    with pytest.raises(ValueError, match="two strips"):
        solve_alignment([b0])
    with pytest.raises(ValueError, match="nothing to solve"):
        solve_alignment([b0, b1], solve_boresight=False, offsets="none")
