"""Subpixel matching, and the measurement that depends on it.

One pixel of disparity is about 0.15 ft of height on the delivery this
was written for, and the surface is judged at 0.1 ft. So a matcher that
is right to the nearest pixel is not nearly right enough, and the tests
below are written against a planted disparity that includes a fraction.

The second thing they pin is the reason the affine stage exists. Ground
that tilts away makes the right patch a STRETCHED copy of the left, not
a shifted one. Solving for a shift alone then splits the difference,
and on a normalized pair the residue lies along the baseline, which is
exactly the direction that becomes elevation -- so the whole error
lands in the height. That is the shape of the bias that made an earlier
pass over this job's control marks read over a foot low while its
horizontal answer was fine.

And the third is refusal. Plain asphalt correlates about as well at
every shift. A matcher that returns its best guess there produces a
confident elevation from nothing, and nothing about it looks wrong
afterwards.
"""

import numpy as np
import pytest

from pyargus.imagery import matching
from pyargus.imagery import stereo


def textured(width=520, height=220, seed=3):
    """An image like a photograph rather than like white noise.

    This matters more than it looks. A real lens and sensor are
    band-limited: there is very little energy near the Nyquist
    frequency, which is exactly why a photograph can be resampled to a
    fraction of a pixel at all. White noise cannot -- interpolating it
    half a pixel destroys most of its contrast -- so a test built on
    noise measures the fixture's resampler and calls it the matcher's
    error. Measured: a there-and-back half-pixel shift of white noise
    here changed the image by half its own standard deviation.
    """
    from scipy import ndimage

    rng = np.random.default_rng(seed)
    base = ndimage.gaussian_filter(rng.normal(0, 1, (height, width)), 1.8)
    base += 0.6 * ndimage.gaussian_filter(rng.normal(0, 1, (height, width)),
                                          5.0)
    base = base / base.std()
    return np.clip(128 + 38 * base, 0, 255)


def shifted(image, dx, scale=1.0):
    """The same scene moved dx to the LEFT, optionally stretched in x.

    A feature at column c in the source appears at c - dx here, so
    matching the source patch into this image should return +dx. Cubic
    resampling, so the fixture is not the thing being measured.
    """
    from scipy import ndimage

    height, width = image.shape
    cols = np.arange(width, dtype=float)
    centre = width / 2.0
    want = centre + (cols - centre) * scale + dx
    rows = np.arange(height, dtype=float)
    grid_r, grid_c = np.meshgrid(rows, want, indexing="ij")
    return ndimage.map_coordinates(image, [grid_r, grid_c], order=3,
                                   mode="reflect")


@pytest.mark.parametrize("planted", [3.0, 7.35, -4.6, 11.82, -9.25])
def test_the_matcher_finds_a_planted_fractional_disparity(planted):
    left = textured()
    right = shifted(left, -planted)          # feature moves +planted right
    got = matching.disparity(left, right, 260, 110, half=14, search=25)
    assert abs(got["disparity"] - planted) < 0.05, (
        f"planted {planted:+.2f}, found {got['disparity']:+.3f}: a tenth of "
        f"a pixel here is about 0.015 ft of height")
    assert got["score"] > 0.9


def test_whole_pixel_matching_would_not_be_good_enough():
    """The reason the subpixel stage exists, stated as a test.

    Rounding to the nearest pixel is wrong by up to half a pixel, which
    on this rig is 0.08 ft of height -- most of a 0.1 ft budget spent
    on arithmetic before the operator has done anything.
    """
    planted = 7.42
    left = textured()
    right = shifted(left, -planted)
    got = matching.disparity(left, right, 260, 110, half=14, search=25)
    rounded = round(got["disparity"])
    assert abs(rounded - planted) > 0.3, (
        f"the planted disparity is too near a whole pixel to show the "
        f"difference: rounding it costs only {abs(rounded-planted):.2f} px")
    assert abs(got["disparity"] - planted) < 0.05


@pytest.mark.parametrize("stretch", [1.03, 1.06])
def test_a_stretched_patch_biases_a_shift_only_match_and_the_affine_fixes_it(
        stretch):
    """Sloping ground, which is where a surface most needs judging.

    The truth here is NOT the planted shift. `shifted` stretches about
    the image centre, so a template taken AT the centre is displaced by
    ``planted / stretch``, and asserting against the bare planted value
    measures the fixture's geometry rather than the matcher's error --
    which is how this test first read as a failure of a stage that was
    right to two thousandths of a pixel.
    """
    planted = 6.0
    centre = 260
    left = textured()
    right = shifted(left, -planted, scale=stretch)
    truth = planted / stretch

    plain = matching.disparity(left, right, centre, 110, half=18, search=25,
                               affine=False)
    fixed = matching.disparity(left, right, centre, 110, half=18, search=25,
                               affine=True)
    plain_err = abs(plain["disparity"] - truth)
    fixed_err = abs(fixed["disparity"] - truth)
    assert fixed_err < plain_err, (
        f"stretch {stretch}: shift-only was off by {plain_err:.4f} px and "
        f"the affine stage by {fixed_err:.4f}; it did not earn its place")
    assert fixed_err < 0.02, f"affine still off by {fixed_err:.4f} px"
    # and it recovers the stretch itself, as the inverse, since it maps
    # the right patch back onto the left one
    assert fixed["scale"] == pytest.approx(1.0 / stretch, abs=0.01)


def test_featureless_ground_is_refused_rather_than_guessed():
    flat = np.full((200, 400), 120.0)
    with pytest.raises(matching.NoMatch):
        matching.disparity(flat, flat, 200, 100, half=12, search=20)

    # a gentle ramp: plenty of contrast, but it looks the same at every
    # horizontal shift, which is the case a score threshold alone misses
    ramp = np.tile(np.linspace(0, 255, 400), (200, 1))
    with pytest.raises(matching.NoMatch, match="same at many shifts|guess"):
        matching.disparity(ramp, ramp, 200, 100, half=12, search=20)


def test_a_template_that_runs_off_the_edge_is_refused():
    left = textured()
    with pytest.raises(matching.NoMatch, match="runs off"):
        matching.disparity(left, left, 4, 110, half=14, search=20)


def test_the_matcher_does_not_invent_a_match_across_unrelated_scenes():
    left = textured(seed=1)
    right = textured(seed=99)
    with pytest.raises(matching.NoMatch):
        matching.disparity(left, right, 260, 110, half=16, search=25)


# --- from a disparity to a coordinate ---------------------------------

def _pair_info():
    """A normalized pair's geometry, without any imagery."""
    from pyargus.imagery.camera import Camera
    real = dict(focal_px=4400.0, width_px=5472, height_px=3648,
                cx_px=17.281, cy_px=-9.092, k1=0.03,
                k2=-0.2, k3=0.3, p1=0.0005,
                p2=0.0015, pixel_mm=0.0024)
    camera = Camera(quarter_turns=3, name="n", **real)
    o_a = np.array([2_600_400.0, 1_200_500.0, 1_443.0])
    o_b = np.array([2_600_560.0, 1_200_560.0, 1_441.0])
    eye = np.eye(3)
    blank = np.zeros((3648, 5472))
    _, _, info = stereo.pair(camera, eye, o_a, blank, camera, eye, o_b, blank,
                             ground_z=1_100.0, size=(900, 700),
                             centre_xyz=(2_600_480.0, 1_200_530.0, 1_100.0))
    return info, o_a, o_b


def test_a_disparity_becomes_the_coordinate_it_came_from():
    """Plant a point, compute its true disparity, measure it back."""
    info, o_a, o_b = _pair_info()
    truth = np.array([[2_600_470.0, 1_200_525.0, 1_103.5],
                      [2_600_495.0, 1_200_541.0, 1_094.0],
                      [2_600_480.0, 1_200_530.0, 1_120.0]])
    la, rb = stereo.project_into_pair(info, o_a, o_b, truth, info["size"])
    for i, point in enumerate(truth):
        assert abs(la[i, 1] - rb[i, 1]) < 1e-6
        d = rb[i, 0] - la[i, 0]
        got, report = stereo.measure(info, la[i, 0], la[i, 1], d)
        assert np.allclose(got, point, atol=1e-6), (
            f"{point} came back as {got}")
        assert report["residual"] < 1e-6
        assert report["max_angle_deg"] > 15.0


def test_the_height_moves_the_way_a_pixel_of_disparity_says_it_should():
    info, o_a, o_b = _pair_info()
    truth = np.array([[2_600_480.0, 1_200_530.0, 1_100.0]])
    la, rb = stereo.project_into_pair(info, o_a, o_b, truth, info["size"])
    d = rb[0, 0] - la[0, 0]
    base, _ = stereo.measure(info, la[0, 0], la[0, 1], d)
    moved, _ = stereo.measure(info, la[0, 0], la[0, 1], d + 1.0)
    assert abs(abs(moved[2] - base[2]) - info["height_per_pixel"]) < 0.02, (
        f"one pixel moved the height {abs(moved[2]-base[2]):.4f} ft but the "
        f"pair predicted {info['height_per_pixel']:.4f}")


def test_a_measurement_from_a_weak_pair_is_refused():
    from pyargus.imagery import intersect as intersect_mod
    info, o_a, o_b = _pair_info()
    truth = np.array([[2_600_480.0, 1_200_530.0, 1_100.0]])
    la, rb = stereo.project_into_pair(info, o_a, o_b, truth, info["size"])
    d = rb[0, 0] - la[0, 0]
    with pytest.raises(intersect_mod.WeakGeometry):
        stereo.measure(info, la[0, 0], la[0, 1], d, refuse_below=60.0)


def test_periodic_ground_is_refused_because_its_peaks_are_all_alike():
    """Highway pavement, which is where this matcher actually runs.

    Rumble strips, lane dashes and joints repeat every few feet, so
    correlation against them has many peaks of similar height and the
    tallest is not reliably the right one. Measured on the delivery
    this was written for: at every surveyed mark it was tried on,
    correlation picked a peak several to nearly forty pixels away from
    the disparity the lidar's own ground predicts. A matcher that
    returns its best guess there produces a confident elevation that is
    feet out.
    """
    rng = np.random.default_rng(4)
    rows, cols = 200, 500
    x = np.arange(cols)
    # a repeating pattern, like a rumble strip, with a little noise
    pattern = 120 + 90 * (np.sin(2 * np.pi * x / 23.0) > 0.4)
    image = np.tile(pattern, (rows, 1)) + rng.normal(0, 3, (rows, cols))

    with pytest.raises(matching.NoMatch, match="same at many shifts|guess"):
        matching.disparity(image, image, 250, 100, half=14, search=60)


def test_the_margin_test_does_not_reject_ordinary_ground():
    """The other half: a threshold that refuses everything is no use."""
    left = textured()
    right = shifted(left, -5.5)
    got = matching.disparity(left, right, 260, 110, half=14, search=25)
    assert got["margin"] > 0.15
    assert abs(got["disparity"] - 5.5) < 0.05
