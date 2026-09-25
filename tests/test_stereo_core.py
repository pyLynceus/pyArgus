"""The measurement core a stereo review needs: a ray, and where rays meet.

pyArgus could turn a ground point into a pixel and never the other way.
That is enough to PAINT a surface into a photograph and not enough to
MEASURE anything, which is what Bryon asked for: an operator drives a
mark onto ground they can see and the suite records a coordinate.

The inverse gets a test most code cannot have. `project` is already
validated on real data -- 1,083 photographs, 15.3 million points -- so
the inverse is checked against it rather than against a second opinion
of my own: send a grid of pixels out as rays, walk each one to a known
range, project it back, and require the original pixel to a tolerance
far tighter than any pointing error. A round trip that closes to a
billionth of a pixel cannot be accidentally right.

The intersection is checked the other way, from planted geometry with a
known answer, and specifically for the failure that matters here: a
pair of nearly parallel rays still returns a number, and that number is
worthless. On this rig ADJACENT frames are such a pair.
"""

import numpy as np
import pytest

from pyargus.imagery import intersect as it
from pyargus.imagery.camera import Camera

# A TrueView-like nadir camera: the sensor format is the camera's
# published one, the lens terms are invented at the size a real
# calibration has, so the distortion exercised here is a realistic lens.
REAL = dict(focal_px=4400.0, width_px=5472, height_px=3648,
            cx_px=2750.0 - (5472 - 1) / 2.0,
            cy_px=1810.0 - (3648 - 1) / 2.0,
            k1=0.03, k2=-0.2, k3=0.3,
            p1=0.0005, p2=0.0015, pixel_mm=0.0024)


def camera(turns=3):
    return Camera(quarter_turns=turns, name="nadir", **REAL)


def looking_down():
    """Camera-to-ground rotation for a level, north-up nadir frame."""
    return np.array([[1.0, 0.0, 0.0],
                     [0.0, 1.0, 0.0],
                     [0.0, 0.0, 1.0]])


def tilted():
    """A rotation that is not the identity in any axis, so a sign error
    in the inverse cannot cancel itself."""
    a, b, c = np.radians(7.0), np.radians(-4.0), np.radians(23.0)
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0],
                   [0, 0, 1.0]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1.0, 0],
                   [-np.sin(b), 0, np.cos(b)]])
    rx = np.array([[1.0, 0, 0], [0, np.cos(a), -np.sin(a)],
                   [0, np.sin(a), np.cos(a)]])
    return rz @ ry @ rx


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
@pytest.mark.parametrize("rotation", ["level", "tilted"])
def test_a_pixel_becomes_a_ray_and_comes_back_the_same_pixel(turns, rotation):
    cam = camera(turns)
    r_cam = looking_down() if rotation == "level" else tilted()
    origin = np.array([2_600_500.0, 1_200_500.0, 1_441.0])

    cols = np.linspace(40, cam.width_px - 40, 23)
    rows = np.linspace(40, cam.height_px - 40, 17)
    grid = np.array([(c, r) for c in cols for r in rows])
    d, usable = cam.ray(r_cam, grid[:, 0], grid[:, 1])
    assert usable.all(), f"{(~usable).sum()} of {len(grid)} pixels unusable"

    for distance in (50.0, 343.0, 5_000.0):
        xyz = origin + d * distance
        col, row, visible = cam.project(r_cam, origin, xyz)
        assert visible.all()
        assert np.allclose(col, grid[:, 0], atol=1e-7), distance
        assert np.allclose(row, grid[:, 1], atol=1e-7), distance


def test_the_round_trip_would_catch_a_wrong_quarter_turn():
    """The check that the test above is worth running.

    A round trip through a self-consistent pair of transforms can be
    exact while both are wrong together, so this pins that the ray and
    the projection are NOT free to agree with each other: a ray made
    for one rotation must fail to project back under another.
    """
    r_cam, origin = tilted(), np.array([0.0, 0.0, 1_441.0])
    pixel = np.array([[900.0, 2_700.0]])
    d, ok = camera(3).ray(r_cam, pixel[:, 0], pixel[:, 1])
    assert ok.all()
    xyz = origin + d * 343.0
    for wrong in (0, 1, 2):
        col, row, _ = camera(wrong).project(r_cam, origin, xyz)
        assert not np.allclose([col[0], row[0]], pixel[0], atol=1.0), (
            f"quarter_turns={wrong} reproduced the pixel that "
            f"quarter_turns=3 made, so this suite cannot tell them apart")


def test_a_pixel_outside_the_calibrated_field_is_refused_not_guessed():
    """Past the barrel's fold two directions share a pixel."""
    cam = camera(3)
    far = cam.focal_px * cam._r_valid * 3.0
    col = np.array([(cam.width_px - 1) / 2.0 + cam.cx_px + far])
    row = np.array([(cam.height_px - 1) / 2.0 + cam.cy_px])
    _, usable = cam.ray(looking_down(), col, row)
    assert not usable.any()


def test_undistort_inverts_the_forward_distortion_exactly():
    cam = camera(3)
    x = np.linspace(-0.35, 0.35, 41)
    y = np.linspace(-0.25, 0.25, 31)
    xi, yi = np.meshgrid(x, y)
    xi, yi = xi.ravel(), yi.ravel()
    r2 = xi * xi + yi * yi
    radial = 1 + cam.k1 * r2 + cam.k2 * r2**2 + cam.k3 * r2**3
    xd = xi * radial + cam.p1 * (r2 + 2 * xi * xi) + 2 * cam.p2 * xi * yi
    yd = yi * radial + cam.p2 * (r2 + 2 * yi * yi) + 2 * cam.p1 * xi * yi
    back_x, back_y, settled = cam.undistort(xd, yd)
    inside = r2 <= cam._r_valid * cam._r_valid
    assert settled[inside].all()
    assert np.allclose(back_x[inside], xi[inside], atol=1e-11)
    assert np.allclose(back_y[inside], yi[inside], atol=1e-11)


# --- where rays meet -------------------------------------------------

def test_two_rays_meet_where_the_point_was_planted():
    truth = np.array([2_600_500.0, 1_200_500.0, 1_100.0])
    origins = np.array([[2_600_400.0, 1_200_500.0, 1_441.0],
                        [2_600_600.0, 1_200_500.0, 1_441.0]])
    d = truth - origins
    xyz, info = it.intersect(origins, d)
    assert np.allclose(xyz, truth, atol=1e-9)
    assert info["residual"] < 1e-9
    assert info["rays"] == 2
    assert info["max_angle_deg"] == pytest.approx(
        np.degrees(2 * np.arctan(100.0 / 341.0)), abs=1e-6)


def test_rays_that_do_not_meet_report_how_far_apart_they_are():
    origins = np.array([[0.0, 0.0, 100.0], [100.0, 0.0, 100.0]])
    d = np.array([[0.0, 0.0, -1.0], [0.0, 0.3, -1.0]])   # skew
    xyz, info = it.intersect(origins, d)
    assert info["residual"] > 1.0
    assert info["worst_ray"] >= info["residual"]
    assert np.all(np.isfinite(xyz))


def test_adjacent_frames_on_this_rig_are_refused():
    """The measured geometry of the delivery this was built for.

    Stations 21 ft apart at 343 ft above ground: a base-to-height ratio
    of 0.06 and about 3.5 degrees between the rays. Taking the nearest
    neighbour is the obvious thing to do and it is the mistake, so the
    refusal names the angle.
    """
    truth = np.array([0.0, 0.0, 0.0])
    origins = np.array([[0.0, 0.0, 343.0], [21.0, 0.0, 343.0]])
    d = truth - origins
    assert it.max_angle(d / np.linalg.norm(d, axis=1, keepdims=True)) < 4.0
    with pytest.raises(it.WeakGeometry, match="degrees"):
        it.intersect(origins, d, refuse_below=15.0)
    # eight stations apart is the same scene and a usable pair
    wide = np.array([[0.0, 0.0, 343.0], [168.0, 0.0, 343.0]])
    xyz, info = it.intersect(wide, truth - wide, refuse_below=15.0)
    assert np.allclose(xyz, truth, atol=1e-9)
    assert info["max_angle_deg"] > 25.0


def test_one_ray_is_a_direction_and_not_a_point():
    with pytest.raises(ValueError, match="at least two"):
        it.intersect([[0, 0, 1]], [[0, 0, -1]])


def test_the_height_a_pixel_of_pointing_error_costs():
    """The number that decides whether a pair can answer the question.

    Nearly parallel rays must cost far more height per pixel than well
    separated ones, and the prediction for this rig is about a foot at
    adjacent-frame geometry against a few hundredths at eight stations.
    """
    truth = np.array([0.0, 0.0, 0.0])
    close = np.array([[0.0, 0.0, 343.0], [21.0, 0.0, 343.0]])
    wide = np.array([[0.0, 0.0, 343.0], [168.0, 0.0, 343.0]])
    costs = []
    for origins in (close, wide):
        d = truth - origins
        d = d / np.linalg.norm(d, axis=1, keepdims=True)
        costs.append(it.height_sensitivity(origins, d, truth,
                                           pointing_px=0.3,
                                           focal_px=4400.0))
    # Against the closed form rather than a threshold I chose: one pixel
    # of parallax is (H/B) x (H/f) of height, so the cost scales as the
    # inverse base-to-height ratio. Asserting a bare ratio would pass
    # for a sensitivity that is merely monotone; this pins the physics.
    H, GSD, POINTING = 343.0, 343.0 / 4400.0, 0.3
    for origins, base, measured in ((close, 21.0, costs[0]),
                                    (wide, 168.0, costs[1])):
        predicted = (H / base) * GSD * POINTING
        assert measured == pytest.approx(predicted, rel=0.30), (
            f"base {base:g} ft: measured {measured:.4f} ft per {POINTING} px "
            f"against a predicted {predicted:.4f}")
    assert costs[0] > 5 * costs[1]
    assert costs[1] < 0.1, (
        f"a pair eight stations apart should cost under 0.1 ft of height "
        f"per {POINTING} px of pointing, got {costs[1]:.3f}")
