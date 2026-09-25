"""The normalized pair: the thing that decides whether eyes can fuse it.

One property matters more than every other here, and it is checkable
exactly: after normalization, a ground point must land on the SAME ROW
in both halves. That is what y-parallax means, and it is the difference
between a pair an operator can work in all afternoon and one that gives
them a headache in a minute.

It is also the property that a plausible-looking implementation gets
subtly wrong. Resampling both frames onto a ground plane at an assumed
height leaves residual parallax wherever the ground is not at that
height, in a direction that is not purely horizontal. So the tests
below deliberately plant points at many different elevations: a
construction that only works at one height fails them, and a
construction that only works at the image centre fails them too.

The second property is that the pair must know what it is worth. A pair
that fuses beautifully and measures nothing is the trap this rig
actually presents, since adjacent frames are 21 ft apart at 343 ft.
"""

import numpy as np
import pytest

from pyargus.imagery import intersect as intersect_mod
from pyargus.imagery import stereo
from pyargus.imagery.camera import Camera

REAL = dict(focal_px=4400.0, width_px=5472, height_px=3648,
            cx_px=2750.0 - (5472 - 1) / 2.0,
            cy_px=1810.0 - (3648 - 1) / 2.0,
            k1=0.03, k2=-0.2, k3=0.3,
            p1=0.0005, p2=0.0015, pixel_mm=0.0024)
GROUND = 1_100.0
FLYING = 1_443.0


def cam():
    return Camera(quarter_turns=3, name="nadir", **REAL)


def attitude(roll=0.0, pitch=0.0, yaw=0.0):
    """A camera-to-ground rotation, degrees, so the two frames can be
    given DIFFERENT attitudes -- which is the whole reason a raw pair
    has y-parallax in the first place."""
    a, b, c = np.radians([roll, pitch, yaw])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0],
                   [0, 0, 1.0]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1.0, 0],
                   [-np.sin(b), 0, np.cos(b)]])
    rx = np.array([[1.0, 0, 0], [0, np.cos(a), -np.sin(a)],
                   [0, np.sin(a), np.cos(a)]])
    return rz @ ry @ rx


def a_pair(base=168.0, tilt=True):
    """Two stations a chosen baseline apart, with unequal attitudes."""
    o_a = np.array([2_600_400.0, 1_200_500.0, FLYING])
    o_b = np.array([2_600_400.0 + base * 0.87, 1_200_500.0 + base * 0.49,
                    FLYING - 3.0])
    r_a = attitude(2.5, -1.4, 31.0) if tilt else attitude(0, 0, 0)
    r_b = attitude(-1.9, 2.2, 29.5) if tilt else attitude(0, 0, 0)
    return o_a, r_a, o_b, r_b


def test_a_normalized_pair_has_no_y_parallax_at_any_height():
    """The property the whole thing exists for."""
    o_a, r_a, o_b, r_b = a_pair()
    size = (700, 520)
    left, right, info = stereo.pair(
        cam(), r_a, o_a, np.zeros((3648, 5472)),
        cam(), r_b, o_b, np.zeros((3648, 5472)),
        ground_z=GROUND, size=size)

    rng = np.random.default_rng(24)
    mid = 0.5 * (o_a + o_b)
    pts = np.column_stack([
        mid[0] + rng.uniform(-120, 120, 400),
        mid[1] + rng.uniform(-120, 120, 400),
        GROUND + rng.uniform(-40, 40, 400)])         # many heights, on purpose
    la, rb = stereo.project_into_pair(info, o_a, o_b, pts, size)
    dy = np.abs(la[:, 1] - rb[:, 1])
    assert np.nanmax(dy) < 1e-6, (
        f"worst y-parallax {np.nanmax(dy):.4g} px: the halves are not "
        f"normalized, and no operator can fuse them")
    # and the x difference IS the depth: it must vary with height
    dx = la[:, 0] - rb[:, 0]
    assert np.ptp(dx) > 5.0, ("horizontal parallax barely changes with "
                              "height, so this pair carries no depth")
    lift = np.polyfit(pts[:, 2], dx, 1)[0]
    assert abs(lift) > 0.05
    # and the pair CONVERGES on the point it was centred on, so both
    # halves show the same scenery rather than two windows separated by
    # the full parallax, which on this rig is over 1,600 px
    at_centre = np.argmin(np.abs(pts[:, 2] - GROUND)
                          + np.hypot(pts[:, 0] - mid[0], pts[:, 1] - mid[1]))
    assert abs(dx[at_centre]) < 60.0, (
        f"the pair is {dx[at_centre]:.0f} px apart at the point it was "
        f"centred on; the halves do not overlap")


def test_a_raw_pair_does_have_y_parallax_so_the_test_above_means_something():
    """Without normalization the same scene is not fusible.

    A property that holds before AND after a transformation pins
    nothing about the transformation.
    """
    o_a, r_a, o_b, r_b = a_pair()
    camera = cam()
    rng = np.random.default_rng(25)
    mid = 0.5 * (o_a + o_b)
    pts = np.column_stack([mid[0] + rng.uniform(-120, 120, 300),
                           mid[1] + rng.uniform(-120, 120, 300),
                           GROUND + rng.uniform(-40, 40, 300)])
    ca, ra, oka = camera.project(r_a, o_a, pts)
    cb, rb, okb = camera.project(r_b, o_b, pts)
    both = oka & okb
    assert both.sum() > 50
    assert np.abs(ra[both] - rb[both]).max() > 50.0, (
        "the raw frames already agree on row, so this scene cannot show "
        "that normalization did anything")


def test_the_pair_reports_what_it_is_worth_and_refuses_a_useless_one():
    """Adjacent frames on this rig fuse perfectly and measure nothing."""
    o_a, r_a, o_b, r_b = a_pair(base=21.0)
    blank = np.zeros((3648, 5472))
    with pytest.raises(intersect_mod.WeakGeometry, match="will not measure"):
        stereo.pair(cam(), r_a, o_a, blank, cam(), r_b, o_b, blank,
                    ground_z=GROUND, size=(200, 200), refuse_below=15.0)

    o_a, r_a, o_b, r_b = a_pair(base=168.0)
    _, _, info = stereo.pair(cam(), r_a, o_a, blank, cam(), r_b, o_b, blank,
                             ground_z=GROUND, size=(200, 200),
                             refuse_below=15.0)
    assert 0.35 < info["base_over_height"] < 0.6
    assert info["angle_deg"] > 20.0
    # One pixel is not the precision: an operator on a floating mark
    # points to a fraction of one. What this asserts is the thing that
    # decides the product -- that a 0.1 ft question needs BETTER than
    # half a pixel here, which is demanding and normal, rather than the
    # four pixels an adjacent pair would allow.
    needed_px = 0.1 / info["height_per_pixel"]
    assert 0.3 < needed_px < 1.0, (
        f"one pixel is {info['height_per_pixel']:.3f} ft of height, so 0.1 ft "
        f"needs pointing to {needed_px:.2f} px")


def test_height_per_pixel_is_far_worse_for_the_neighbouring_frame():
    o_a, _, o_b, _ = a_pair(base=21.0)
    close = stereo.height_per_pixel(o_a, o_b, GROUND, REAL["focal_px"])
    o_a, _, o_b, _ = a_pair(base=168.0)
    wide = stereo.height_per_pixel(o_a, o_b, GROUND, REAL["focal_px"])
    assert close > 1.0, (
        f"adjacent frames should cost over a foot of height per pixel, "
        f"got {close:.3f}")
    assert wide < 0.2, f"a pair eight stations apart got {wide:.3f} ft/px"
    # the relationship, not a pair of thresholds: height per pixel goes
    # as the inverse baseline, so eight times the base is an eighth
    assert close / wide == pytest.approx(168.0 / 21.0, rel=1e-6)


def test_the_resampling_does_not_depend_on_how_far_along_the_ray_we_look():
    """The warp is a rotation and a lens, not a scene.

    If the answer moved with FAR, the construction would secretly be
    assuming a surface, which is the failure mode that leaves residual
    parallax.
    """
    o_a, r_a, o_b, r_b = a_pair()
    image = np.arange(3648 * 5472, dtype=float).reshape(3648, 5472) % 251
    r_norm, _ = stereo.normalized_rotation(o_a, r_a, o_b, r_b)
    first, _ = stereo.resample(cam(), r_a, o_a, image, r_norm,
                               focal_px=4400.0, size=(160, 120))
    original = stereo.FAR
    try:
        stereo.FAR = original * 137.0
        second, _ = stereo.resample(cam(), r_a, o_a, image, r_norm,
                                    focal_px=4400.0, size=(160, 120))
    finally:
        stereo.FAR = original
    good = np.isfinite(first) & np.isfinite(second)
    assert good.mean() > 0.5
    assert np.allclose(first[good], second[good], atol=1e-6)


def test_resampling_reproduces_the_source_where_it_should():
    """A synthetic frame resampled through its OWN rotation, with the
    baseline direction taken out, must come back as itself."""
    camera = cam()
    o = np.array([0.0, 0.0, FLYING])
    r = attitude(0, 0, 0)
    rng = np.random.default_rng(7)
    image = rng.uniform(0, 255, (3648, 5472))
    out, ok = stereo.resample(camera, r, o, image, r,
                              focal_px=camera.focal_px, size=(201, 151))
    # the centre pixel looks straight down the optical axis, which is
    # the principal point in the source
    assert ok[75, 100]
    col = (camera.width_px - 1) / 2.0 + camera.cx_px
    row = (camera.height_px - 1) / 2.0 + camera.cy_px
    assert out[75, 100] == pytest.approx(
        stereo._sample(image, np.array([col]), np.array([row]))[0], abs=1e-9)


def test_an_anaglyph_puts_each_eye_in_its_own_channel():
    left = np.full((6, 8), 200.0)
    right = np.zeros((6, 8))
    out = stereo.anaglyph(left, right)
    assert out.shape == (6, 8, 3)
    assert np.allclose(out[..., 0], 200.0)
    assert np.allclose(out[..., 1], 0.0) and np.allclose(out[..., 2], 0.0)
    flipped = stereo.anaglyph(left, right, mode="cyan-red")
    assert np.allclose(flipped[..., 2], 200.0)
    with pytest.raises(ValueError, match="differ in size"):
        stereo.anaglyph(left, np.zeros((6, 9)))


def test_two_frames_from_one_place_are_refused():
    o = np.array([0.0, 0.0, FLYING])
    with pytest.raises(ValueError, match="no baseline|share a perspective"):
        stereo.normalized_rotation(o, attitude(), o, attitude(0, 0, 5))


def test_pair_selection_will_not_take_a_frame_that_barely_sees_the_target():
    """Geometry is not enough, and the failure is easy to miss.

    A frame with a perfect base-to-height ratio can hold the point ten
    pixels from its own edge, and the rebuilt half comes back half
    black. Measured on real imagery before this existed.
    """
    camera = cam()
    target = np.array([2_600_400.0, 1_200_500.0, GROUND])
    good = 0.5 * (FLYING - GROUND)          # a base-to-height ratio of 0.5

    def margin(rotation, origin):
        col, row, ok = camera.project(rotation, origin, target[None, :])
        if not ok[0]:
            return -1.0
        return float(min(col[0], row[0], camera.width_px - 1 - col[0],
                         camera.height_px - 1 - row[0]))

    origins = [np.array([target[0], target[1], FLYING])]
    rotations = [attitude(0, 0, 0)]
    # two candidates at the SAME ratio, differing only in where the
    # target falls in their own frames. Which attitude does which is
    # verified below rather than assumed: tilting a camera aims it, and
    # getting the sign backwards is exactly how a test ends up asserting
    # the opposite of what it claims.
    for pitch in (0.0, -24.0):
        origins.append(np.array([target[0] - good, target[1], FLYING]))
        rotations.append(attitude(0, pitch, 0))
    origins = np.asarray(origins)

    margins = [margin(rotations[i], origins[i]) for i in (1, 2)]
    inside = 1 + int(np.argmax(margins))
    edge = 1 + int(np.argmin(margins))
    assert max(margins) >= 400 > min(margins), (
        f"the fixture does not present one usable and one edge frame: "
        f"margins {margins}")

    ranked = stereo.choose_partner(camera, rotations, origins, 0, target,
                                   min_margin_px=400)
    picked = {r["index"] for r in ranked}
    assert inside in picked, "the usable partner was rejected"
    assert edge not in picked, (
        f"frame {edge} holds the target {min(margins):.0f} px from its own "
        f"edge and was offered anyway; the rebuilt half would be largely "
        f"empty")
    assert ranked[0]["margin_px"] >= 400
    assert 0.35 <= ranked[0]["base_over_height"] <= 0.75


def test_pair_selection_refuses_an_anchor_that_cannot_hold_a_window():
    camera = cam()
    target = np.array([2_600_400.0, 1_200_500.0, GROUND])
    origins = np.array([[target[0], target[1], FLYING],
                        [target[0] + 170.0, target[1], FLYING]])
    rotations = [attitude(0, -24.0, 0), attitude(0, 0, 0)]
    with pytest.raises(ValueError, match="from its own edge"):
        stereo.choose_partner(camera, rotations, origins, 0, target,
                              min_margin_px=400)
