"""The colorization bridge, pinned against independent derivations.

Every geometric claim is re-derived here from first principles --
similar triangles for the pinhole, np.rot90 index algebra for the
quarter turns, Agisoft's own normalised polynomial for the lens -- so
a sign, swap or convention mutation in the production chain cannot
hide behind a matching mutation in the tests. The review panel earned
several of these: the suite used to factorize the lens model, testing
distortion only at quarter_turns=0 and the turns only with a perfect
lens, which left the SHIPPED configuration (turns=3 with a real .cal)
covered nowhere.
"""

import json

import numpy as np
import pytest

from pyargus.formats import eo as eo_mod
from pyargus.imagery import camera as camera_mod
from pyargus.imagery import colorize as colorize_mod
from pyargus.imagery.camera import Camera

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

# a genuine Summerville nadir sidecar
SUMMERVILLE_CAL = {
    "CalibratedFocalLength": 4420.17, "ImageWidth": 5472,
    "ImageHeight": 3648, "CalibratedCX": 2.83, "CalibratedCY": -18.65,
    "CalibratedK1": 0.040299, "CalibratedK2": -0.236400,
    "CalibratedK3": 0.348867, "CalibratedP1": 0.00009366,
    "CalibratedP2": -0.00069740,
}


def nadir_rotation():
    return eo_mod.rotations_from_direction_up(
        np.array([[0.0, 0.0, -1.0]]), np.array([[0.0, 1.0, 0.0]]))[0]


def simple_camera(width=64, height=48, focal_px=1000.0, **kw):
    return Camera(focal_px=focal_px, width_px=width, height_px=height, **kw)


def photo_frame_size(cam):
    if cam.quarter_turns % 2:
        return cam.height_px, cam.width_px
    return cam.width_px, cam.height_px


# --- EO reading and the rotation ------------------------------------

def test_eo_reader_parses_lp360_and_ignores_angle_columns(tmp_path):
    path = tmp_path / "eo.csv"
    path.write_text(
        "Timestamp, Filename, Origin(Easting[m], Northing[m], Height[m]),"
        " Direction(Easting, Northing, Height), Up(Easting, Northing,"
        " Height), Roll(X)[deg], Pitch(Y)[deg], Yaw(Z)[deg], Omega[deg],"
        " Phi[deg], Kappa[deg]\n"
        "100.5,IMG_N_0001.JPG,1000.0,2000.0,300.0,0.0,0.0,-1.0,"
        "0.0,1.0,0.0,179.6,3.7,32.1,-0.35,-3.71,327.86\n"
        "102.0,IMG_N_0002.JPG,1010.0,2000.0,300.0,0.0,0.0,-1.0,"
        "0.0,1.0,0.0,99,99,99,99,99,99\n")
    eo = eo_mod.read_eo_csv(path)
    assert eo["filename"] == ["IMG_N_0001.JPG", "IMG_N_0002.JPG"]
    assert np.allclose(eo["origin"][0], [1000.0, 2000.0, 300.0])
    assert np.allclose(eo["time"], [100.5, 102.0])
    # eleven columns suffice: pyLynceus's adjusted_eo.csv has no angles
    bare = tmp_path / "adjusted_eo.csv"
    bare.write_text("100.5,a.jpg,0,0,10,0,0,-1,0,1,0\n")
    assert eo_mod.read_eo_csv(bare)["filename"] == ["a.jpg"]
    short = tmp_path / "short.csv"
    short.write_text("1,a.jpg,0,0,10\n")
    with pytest.raises(ValueError, match="11 columns"):
        eo_mod.read_eo_csv(short)
    empty = tmp_path / "empty.csv"
    empty.write_text("Timestamp, junk\n")
    with pytest.raises(ValueError, match="no EO rows"):
        eo_mod.read_eo_csv(empty)


def test_rotation_from_direction_up_on_real_summerville_numbers():
    # a genuine nadir row from eo_Photos_C250926_134000_122SN030.csv
    d = np.array([[-0.051644529, -0.039665477, -0.997877494]])
    u = np.array([[-0.532316365, 0.846523528, -0.006099477]])
    r = eo_mod.rotations_from_direction_up(d, u)[0]
    assert np.allclose(r.T @ r, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(r), 1.0)
    assert np.allclose(r[:, 2], -d[0] / np.linalg.norm(d[0]), atol=1e-9)
    assert abs(np.dot(r[:, 1], r[:, 2])) < 1e-12


def test_rotation_refusals_cover_the_noise_band():
    with pytest.raises(ValueError, match="zero-length direction"):
        eo_mod.rotations_from_direction_up(np.zeros((1, 3)),
                                           np.array([[0.0, 1.0, 0.0]]))
    with pytest.raises(ValueError, match="zero-length up"):
        eo_mod.rotations_from_direction_up(np.array([[0.0, 0.0, -1.0]]),
                                           np.zeros((1, 3)))
    with pytest.raises(ValueError, match="parallel"):
        eo_mod.rotations_from_direction_up(np.array([[0.0, 0.0, -1.0]]),
                                           np.array([[0.0, 0.0, 5.0]]))
    # the NOISE BAND, not just exact parallelism: an up vector a
    # hair off the optical axis leaves roll decided by the export's
    # 9th decimal (measured: 0.29 deg swing per half-ulp at 1e-7)
    with pytest.raises(ValueError, match="rounding noise"):
        eo_mod.rotations_from_direction_up(
            np.array([[0.0, 0.0, -1.0]]), np.array([[0.0, 1e-7, 1.0]]))
    ok = eo_mod.rotations_from_direction_up(
        np.array([[0.0, 0.0, -1.0]]), np.array([[0.0, 1e-3, 1.0]]))
    assert ok.shape == (1, 3, 3)


def test_camera_tag():
    assert eo_mod.camera_tag("250926_134000_N_0015.JPG") == "N"
    assert eo_mod.camera_tag("250926_134000_p_0015.jpg") == "P"
    assert eo_mod.camera_tag("0001.png") is None


# --- the lens model, in Agisoft's own terms -------------------------

def stored_axes_from_rot90(quarter_turns, width, height):
    """How the stored grid's (col, row) axes sit in the photo frame.

    Derived ONLY from the definition ``stored = np.rot90(photo, -q)``,
    by watching where two neighbouring photo pixels land. Returns the
    matrix M with (x_ag, y_ag) = M @ (x_photo, y_photo_up), which is
    what Agisoft's model needs -- and is derived here without touching
    the production rotation.
    """
    w_p, h_p = (height, width) if quarter_turns % 2 else (width, height)
    idx = np.arange(w_p * h_p).reshape(h_p, w_p)
    stored = np.rot90(idx, -quarter_turns)
    where = {int(v): (r, c) for (r, c), v in np.ndenumerate(stored)}
    r0, c0 = where[idx[1, 1]]
    r_dc, c_dc = where[idx[1, 2]]       # +1 photo column
    r_dr, c_dr = where[idx[2, 1]]       # +1 photo row
    # stored col/row change per photo col/row step
    a, c = c_dc - c0, r_dc - r0         # d(stored col, row)/d(photo col)
    b, d = c_dr - c0, r_dr - r0         # d(stored col, row)/d(photo row)
    # photo col runs with +x_photo; photo row runs with -y_photo_up
    return np.array([[a, -b], [c, -d]], dtype=float)


@pytest.mark.parametrize("quarter_turns", [0, 1, 2, 3])
def test_projection_matches_agisoft_native_model(tmp_path, quarter_turns):
    """The whole chain against Agisoft's own equations, with the real
    Summerville lens AND a nonzero principal point AND every quarter
    turn -- the combination the panel proved was covered nowhere."""
    path = tmp_path / "a.JPG.cal"
    path.write_text(json.dumps([SUMMERVILLE_CAL]))
    cam = camera_mod.read_cal(path, quarter_turns=quarter_turns,
                              name="test")

    rng = np.random.default_rng(3)
    d = np.array([[0.0, 0.0, -1.0]])
    up = np.array([[0.0, 1.0, 0.0]])
    r = eo_mod.rotations_from_direction_up(d, up)[0]
    origin = np.array([0.0, 0.0, 300.0])
    pts = np.column_stack([rng.uniform(-150, 150, 500),
                           rng.uniform(-100, 100, 500),
                           rng.uniform(0.0, 30.0, 500)])
    col, row, visible = cam.project(r, origin, pts)
    assert visible.all()

    # ground truth: photo-frame camera coordinates, rotated into the
    # stored grid by the np.rot90 definition, then Agisoft's model
    u = (pts - origin) @ r
    m = stored_axes_from_rot90(quarter_turns, cam.width_px, cam.height_px)
    ag = np.stack([u[:, 0], u[:, 1]], axis=1) @ m.T
    z = -u[:, 2]
    xn, yn = ag[:, 0] / z, ag[:, 1] / z
    r2 = xn * xn + yn * yn
    radial = 1 + SUMMERVILLE_CAL["CalibratedK1"] * r2 \
        + SUMMERVILLE_CAL["CalibratedK2"] * r2 ** 2 \
        + SUMMERVILLE_CAL["CalibratedK3"] * r2 ** 3
    p1 = SUMMERVILLE_CAL["CalibratedP1"]
    p2 = SUMMERVILLE_CAL["CalibratedP2"]
    xd = xn * radial + p1 * (r2 + 2 * xn * xn) + 2 * p2 * xn * yn
    yd = yn * radial + p2 * (r2 + 2 * yn * yn) + 2 * p1 * xn * yn
    f = SUMMERVILLE_CAL["CalibratedFocalLength"]
    want_col = (cam.width_px - 1) / 2.0 + SUMMERVILLE_CAL["CalibratedCX"] \
        + xd * f
    want_row = (cam.height_px - 1) / 2.0 + SUMMERVILLE_CAL["CalibratedCY"] \
        + yd * f
    assert np.abs(col - want_col).max() < 1e-6
    assert np.abs(row - want_row).max() < 1e-6
    # and the lens is doing real work: a distortion-free camera lands
    # tens of pixels away, so this is not an accidentally-trivial test
    plain = Camera(focal_px=f, width_px=cam.width_px,
                   height_px=cam.height_px, quarter_turns=quarter_turns)
    pc, pr, _ = plain.project(r, origin, pts)
    assert np.hypot(pc - col, pr - row).max() > 20.0


def test_nadir_projection_matches_similar_triangles():
    cam = simple_camera()
    r = nadir_rotation()
    h = 100.0
    origin = np.array([10.0, 20.0, h])
    dx, dy = 3.0, -2.0
    pts = np.array([[10.0 + dx, 20.0 + dy, 0.0],
                    [10.0, 20.0, 0.0],
                    [10.0, 20.0, 2 * h]])       # behind the camera
    col, row, visible = cam.project(r, origin, pts)
    assert visible.tolist() == [True, True, False]
    scale_px = cam.focal_px / h
    assert np.isclose(col[1], (cam.width_px - 1) / 2.0)
    assert np.isclose(row[1], (cam.height_px - 1) / 2.0)
    assert np.isclose(col[0], (cam.width_px - 1) / 2.0 + dx * scale_px)
    assert np.isclose(row[0], (cam.height_px - 1) / 2.0 - dy * scale_px)


def test_barrel_foldback_is_refused_and_far_points_masked():
    """A barrel lens extrapolated past its fold sweeps back through the
    frame: a point 62 deg off-axis lands on a perfectly ordinary pixel
    and then wins the most-centered contest. The panel reproduced that
    end to end, so the fold is computed and points beyond it masked."""
    # k1 = -0.15: the model folds at an ideal radius of 1.49, safely
    # outside this frame's corner (0.897), so the camera is usable
    cam = Camera(focal_px=3666.0, width_px=5472, height_px=3648,
                 k1=-0.15, name="barrel")
    assert np.isclose(cam._r_valid, np.sqrt(1.0 / 0.45), rtol=1e-3)
    r = nadir_rotation()
    origin = np.array([0.0, 0.0, 100.0])
    # tan(65.6 deg) = 2.2, well past the fold: the folded radius has
    # shrunk back to 0.603, so it lands at column 4946 of 5472 -- a
    # perfectly ordinary pixel, which is exactly the trap
    beyond = np.array([[220.0, 0.0, 0.0]])
    col, row, visible = cam.project(r, origin, beyond)
    assert not visible[0]
    assert cam.contains(col, row)[0], "the guard is what rejects it"
    inside = np.array([[10.0, 5.0, 0.0], [60.0, 20.0, 0.0]])
    assert cam.project(r, origin, inside)[2].all()
    # a lens whose model cannot even reach its own frame corner (the
    # panel's own k1 = -0.30 at this focal length) is a corrupt or
    # mis-transplanted calibration, not a wide lens
    with pytest.raises(ValueError, match="folds back"):
        Camera(focal_px=3666.0, width_px=5472, height_px=3648, k1=-0.30,
               name="broken")


def test_read_cal_refuses_malformed_values_and_multi_camera(tmp_path):
    good = dict(SUMMERVILLE_CAL)
    path = tmp_path / "a.JPG.cal"
    path.write_text(json.dumps([good]))
    cam = camera_mod.read_cal(path)
    assert cam.quarter_turns == 3                 # TrueView default
    assert np.isclose(cam.focal_mm, 4420.17 * 0.0024)
    # an ABSENT key is a term the calibration did not fit
    lean = {k: v for k, v in good.items() if k != "CalibratedP2"}
    (tmp_path / "b.JPG.cal").write_text(json.dumps([lean]))
    assert camera_mod.read_cal(tmp_path / "b.JPG.cal").p2 == 0.0
    # a PRESENT but unreadable one is a corrupt sidecar, and silently
    # zeroing K1 alone is ~70 px at the frame corner
    for bad_value in (None, "n/a", "0,040299"):
        broken = dict(good, CalibratedK1=bad_value)
        p = tmp_path / "c.JPG.cal"
        p.write_text(json.dumps([broken]))
        with pytest.raises(ValueError, match="CalibratedK1 is present"):
            camera_mod.read_cal(p)
    two = tmp_path / "d.JPG.cal"
    two.write_text(json.dumps([good, good]))
    with pytest.raises(ValueError, match="2 calibrations"):
        camera_mod.read_cal(two)
    with pytest.raises(ValueError, match="not a TrueView"):
        (tmp_path / "e.cal").write_text(json.dumps({"foo": 1}))
        camera_mod.read_cal(tmp_path / "e.cal")


def test_find_cal_prefers_the_image_s_own_sidecar(tmp_path):
    """A flattened multi-camera delivery must not hand every camera the
    first lens in the folder (measured by the panel: port silently
    inherited the nadir focal length)."""
    flat = tmp_path / "flat"
    flat.mkdir()
    nadir = dict(SUMMERVILLE_CAL, CalibratedFocalLength=4420.17)
    port = dict(SUMMERVILLE_CAL, CalibratedFocalLength=4419.11)
    (flat / "a_N_0001.JPG").write_bytes(b"")
    (flat / "a_N_0001.JPG.cal").write_text(json.dumps([nadir]))
    (flat / "a_P_0001.JPG").write_bytes(b"")
    (flat / "a_P_0001.JPG.cal").write_text(json.dumps([port]))
    got = camera_mod.read_cal(camera_mod.find_cal(flat / "a_P_0001.JPG"))
    assert np.isclose(got.focal_px, 4419.11)
    # a delivery with ONE shared sidecar still resolves
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "img.JPG").write_bytes(b"")
    (shared / "camera.cal").write_text(json.dumps([nadir]))
    assert camera_mod.find_cal(shared / "img.JPG").name == "camera.cal"
    assert camera_mod.find_cal(tmp_path / "nothing" / "x.JPG") is None


def test_quarter_turns_must_be_whole():
    with pytest.raises(ValueError, match="whole number"):
        simple_camera(quarter_turns=1.5)


# --- rendering helpers for the recovery tests -----------------------

def render_nadir_image(cam, origin, ground_color):
    """The image a distortion-free nadir camera would record over flat
    ground z=0, colored by ``ground_color(x, y)``. Rendered in the
    PHOTO frame by closed-form inverse projection, then turned into the
    STORED grid with np.rot90 -- an independent statement of what
    quarter_turns means."""
    w, h = photo_frame_size(cam)
    cols, rows = np.meshgrid(np.arange(w), np.arange(h))
    x_px = cols - (w - 1) / 2.0
    y_px = -(rows - (h - 1) / 2.0)
    gx = origin[0] + x_px * origin[2] / cam.focal_px
    gy = origin[1] + y_px * origin[2] / cam.focal_px
    photo = ground_color(gx, gy)
    return np.rot90(photo, -cam.quarter_turns)


def checker(gx, gy, cell=10.0):
    """A distinct flat color per ground cell, no gradients."""
    ix = np.floor(gx / cell).astype(int) % 4
    iy = np.floor(gy / cell).astype(int) % 4
    out = np.zeros(ix.shape + (3,), dtype=np.uint8)
    out[..., 0] = 40 + 50 * ix
    out[..., 1] = 30 + 40 * iy
    out[..., 2] = 200 - 30 * ((ix + iy) % 4)
    return out


def write_png(path, array):
    Image.fromarray(array).save(path)


def eo_for(names, origins, direction=(0.0, 0.0, -1.0), up=(0.0, 1.0, 0.0)):
    origins = np.atleast_2d(np.asarray(origins, dtype=float))
    n = len(names)
    return {"time": np.arange(n, dtype=float), "filename": list(names),
            "origin": origins,
            "direction": np.tile(np.asarray(direction, float), (n, 1)),
            "up": np.tile(np.asarray(up, float), (n, 1))}


@pytest.mark.parametrize("quarter_turns", [0, 1, 2, 3])
def test_checkerboard_recovered_exactly(tmp_path, quarter_turns):
    cam = simple_camera(width=600, height=400, focal_px=1000.0,
                        quarter_turns=quarter_turns)
    origin = np.array([50.0, 80.0, 100.0])
    stored = render_nadir_image(cam, origin, checker)
    assert stored.shape[:2] == (cam.height_px, cam.width_px)
    write_png(tmp_path / "0001.png", stored)

    w_p, h_p = photo_frame_size(cam)
    half_w = w_p / 2 * origin[2] / cam.focal_px
    half_h = h_p / 2 * origin[2] / cam.focal_px
    gx, gy = np.meshgrid(np.arange(-60.0, 161.0, 10.0) + 5.0,
                         np.arange(0.0, 161.0, 10.0) + 5.0)
    keep = ((np.abs(gx - 50.0) < half_w - 4.0)
            & (np.abs(gy - 80.0) < half_h - 4.0))
    xyz = np.column_stack([gx[keep], gy[keep], np.zeros(keep.sum())])
    assert xyz.shape[0] >= 6
    rgb, stats = colorize_mod.colorize(
        xyz, eo_for(["0001.png"], origin), {None: cam},
        colorize_mod.find_images(tmp_path))
    assert stats["n_colored"] == xyz.shape[0]
    want = checker(xyz[:, 0], xyz[:, 1]).astype(np.uint16) << 8
    assert np.array_equal(rgb, want)


def test_bilinear_weights_are_pinned_by_a_gradient(tmp_path):
    """A flat-color scene cannot see a col/row weight swap; a gradient
    can. (The panel proved the swap survived the whole suite.)"""
    rgb = np.zeros((6, 8, 3), dtype=np.uint8)
    rgb[..., 0] = np.arange(8)[None, :] * 10        # varies with COLUMN
    rgb[..., 1] = np.arange(6)[:, None] * 20        # varies with ROW
    rgb[..., 2] = 7
    got = colorize_mod.bilinear(rgb, np.array([2.25]), np.array([3.75]))
    assert np.allclose(got[0], [22.5, 75.0, 7.0])
    # corners exactly, and a pure-column query must not move with row
    assert np.allclose(colorize_mod.bilinear(rgb, np.array([0.0]),
                                             np.array([0.0]))[0],
                       [0.0, 0.0, 7.0])
    a = colorize_mod.bilinear(rgb, np.array([5.5]), np.array([1.0]))[0]
    b = colorize_mod.bilinear(rgb, np.array([5.5]), np.array([4.0]))[0]
    assert np.isclose(a[0], b[0]) and not np.isclose(a[1], b[1])


def test_most_centered_beats_nearest(tmp_path):
    """The headline rule is 'closest to the image CENTER', not 'nearest
    camera'. Every earlier scene had both metrics agreeing, so the
    nearest-range mutant survived -- this geometry separates them."""
    cam = simple_camera(width=200, height=200, focal_px=400.0)
    red = np.zeros((200, 200, 3), dtype=np.uint8)
    red[..., 0] = 250
    blue = np.zeros((200, 200, 3), dtype=np.uint8)
    blue[..., 2] = 250
    write_png(tmp_path / "red.png", red)
    write_png(tmp_path / "blue.png", blue)
    # red is CLOSER (lower) but sees the point off-axis; blue is higher
    # and directly overhead, so it is the most-centered view
    origins = np.array([[6.0, 0.0, 40.0], [0.0, 0.0, 120.0]])
    xyz = np.array([[0.0, 0.0, 0.0]])
    rgb, _ = colorize_mod.colorize(
        xyz, eo_for(["red.png", "blue.png"], origins), {None: cam},
        colorize_mod.find_images(tmp_path))
    assert np.linalg.norm(xyz[0] - origins[0]) < np.linalg.norm(
        xyz[0] - origins[1])                      # red really is nearer
    assert rgb[0, 2] == 250 << 8 and rgb[0, 0] == 0


def test_center_score_is_an_angle_not_a_pixel_count(tmp_path):
    """Across cameras the score must be off-axis ANGLE. In raw pixels a
    short-focal camera reports a smaller number for a WORSE view, so it
    would win contests it should lose."""
    wide = simple_camera(width=400, height=400, focal_px=200.0)
    narrow = simple_camera(width=400, height=400, focal_px=800.0)
    for name, val in (("a_W_0001.png", 250), ("a_N_0001.png", 60)):
        img = np.zeros((400, 400, 3), dtype=np.uint8)
        img[..., 1] = val
        write_png(tmp_path / name, img)
    # narrow sees the point 3 deg off-axis, wide sees it 6 deg off --
    # but in pixels that is 42 (narrow) against 21 (wide), so a
    # pixel-based score picks the wide camera's worse view
    d_narrow = 100.0 * np.tan(np.radians(3.0))
    d_wide = 100.0 * np.tan(np.radians(6.0))
    origins = np.array([[d_wide, 0.0, 100.0], [d_narrow, 0.0, 100.0]])
    assert 800 * np.tan(np.radians(3.0)) > 200 * np.tan(np.radians(6.0))
    xyz = np.array([[0.0, 0.0, 0.0]])
    rgb, _ = colorize_mod.colorize(
        xyz, eo_for(["a_W_0001.png", "a_N_0001.png"], origins),
        {"W": wide, "N": narrow}, colorize_mod.find_images(tmp_path))
    assert rgb[0, 1] == 60 << 8, "the narrower, better-centred view wins"


def test_occluded_points_stay_uncolored(tmp_path):
    cam = simple_camera(width=200, height=160, focal_px=400.0)
    gray = np.full((160, 200, 3), 128, dtype=np.uint8)
    write_png(tmp_path / "0001.png", gray)
    gx, gy = np.meshgrid(np.arange(-3.0, 3.01, 0.1),
                         np.arange(-3.0, 3.01, 0.1))
    roof = np.column_stack([gx.ravel(), gy.ravel(),
                            np.full(gx.size, 50.0)])
    under = np.array([[0.0, 0.0, 0.0]])
    open_ground = np.array([[8.0, 6.0, 0.0]])
    xyz = np.vstack([roof, under, open_ground])
    rgb, stats = colorize_mod.colorize(
        xyz, eo_for(["0001.png"], [0.0, 0.0, 100.0]), {None: cam},
        colorize_mod.find_images(tmp_path), occlusion_tol=3.0)
    assert stats["n_occluded"] >= 1
    assert np.all(rgb[len(roof)] == 0)                   # under the roof
    assert np.all(rgb[len(roof) + 1] == 128 << 8)        # in the open
    assert np.all(rgb[0] == 128 << 8)                    # the roof itself


def test_occlusion_cells_do_not_alias_across_rows(tmp_path):
    """The depth grid's row stride comes from the image WIDTH. On a
    non-square frame a height-derived stride aliases distant cells onto
    each other; every earlier occlusion scene was square."""
    cam = simple_camera(width=240, height=80, focal_px=400.0)
    write_png(tmp_path / "0001.png",
              np.full((80, 240, 3), 90, dtype=np.uint8))
    # a tall pole near one edge of the frame and open ground elsewhere:
    # with a wrong stride the pole's short range lands in the same key
    # as ground several rows away and occludes it
    pole = np.column_stack([np.full(60, 12.0), np.full(60, 6.0),
                            np.linspace(40.0, 60.0, 60)])
    gx, gy = np.meshgrid(np.arange(-12.0, 12.1, 1.0),
                         np.arange(-4.0, 4.1, 1.0))
    ground = np.column_stack([gx.ravel(), gy.ravel(),
                              np.zeros(gx.size)])
    xyz = np.vstack([pole, ground])
    rgb, stats = colorize_mod.colorize(
        xyz, eo_for(["0001.png"], [0.0, 0.0, 100.0]), {None: cam},
        colorize_mod.find_images(tmp_path))
    ground_rgb = rgb[len(pole):]
    # only the ground directly under the pole may be shadowed
    hidden = np.flatnonzero(~ground_rgb.any(axis=1))
    assert hidden.size <= 4, (hidden.size, ground[hidden])


def test_chunked_planning_matches_one_pass(tmp_path):
    """The production path chunks at 2M points, so no test ever ran the
    chunk boundary; a per-chunk competition bug would be invisible."""
    cam = simple_camera(width=300, height=300, focal_px=500.0)
    for name, val in (("a.png", 40), ("b.png", 200)):
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        img[..., 2] = val
        write_png(tmp_path / name, img)
    rng = np.random.default_rng(5)
    xyz = np.column_stack([rng.uniform(-20, 40, 500),
                           rng.uniform(-20, 20, 500),
                           np.zeros(500)])
    eo = eo_for(["a.png", "b.png"], np.array([[0.0, 0.0, 100.0],
                                              [20.0, 0.0, 100.0]]))
    ctx = colorize_mod.prepare(eo, {None: cam},
                               colorize_mod.find_images(tmp_path))
    whole = colorize_mod.plan_colorization(xyz, ctx["origins"],
                                           ctx["rotations"], ctx["cameras"])
    chunked = colorize_mod.plan_colorization(
        xyz, ctx["origins"], ctx["rotations"], ctx["cameras"],
        chunk_size=7)
    assert (whole.image == chunked.image).all()
    assert np.allclose(whole.col, chunked.col)
    assert (whole.image >= 0).sum() > 100


def test_case_insensitive_matching_and_dropped_rows(tmp_path):
    cam = simple_camera()
    img = np.full((48, 64, 3), 99, dtype=np.uint8)
    write_png(tmp_path / "shot.png", img)                # lower case
    eo = eo_for(["SHOT.PNG", "MISSING.PNG"],
                np.array([[0.0, 0.0, 100.0], [500.0, 0.0, 100.0]]))
    xyz = np.array([[0.0, 0.0, 0.0]])
    rgb, stats = colorize_mod.colorize(
        xyz, eo, {None: cam}, colorize_mod.find_images(tmp_path))
    assert stats["n_eo_dropped"] == 1
    assert np.all(rgb[0] == 99 << 8)
    with pytest.raises(ValueError, match="none of the EO rows"):
        colorize_mod.colorize(xyz, eo_for(["nope.png", "no.png"],
                                          np.array([[0.0, 0.0, 100.0]] * 2)),
                              {None: cam},
                              colorize_mod.find_images(tmp_path))


def test_duplicate_basenames_refuse(tmp_path):
    """Two files with one name means every EO row for that name samples
    one exposure through the other's pose -- confidently wrong colors,
    not missing ones."""
    cam = simple_camera()
    for folder, val in (("flight1", 20), ("flight2", 220)):
        d = tmp_path / folder
        d.mkdir()
        write_png(d / "0001.png",
                  np.full((48, 64, 3), val, dtype=np.uint8))
    index = colorize_mod.find_images(tmp_path)
    assert index.collisions
    eo = eo_for(["0001.png"], [0.0, 0.0, 100.0])
    with pytest.raises(ValueError, match="more than once"):
        colorize_mod.colorize(np.zeros((1, 3)), eo, {None: cam}, index)


def test_missing_calibration_refuses(tmp_path):
    write_png(tmp_path / "a_N_0001.png",
              np.zeros((48, 64, 3), dtype=np.uint8))
    eo = eo_for(["a_N_0001.png"], [0.0, 0.0, 100.0])
    with pytest.raises(ValueError, match="calibration"):
        colorize_mod.colorize(np.zeros((1, 3)), eo, {},
                              colorize_mod.find_images(tmp_path))


def test_wrong_image_size_refuses_before_any_decoding(tmp_path):
    cam = simple_camera(width=64, height=48)
    write_png(tmp_path / "0001.png",
              np.zeros((10, 10, 3), dtype=np.uint8))    # wrong size
    eo = eo_for(["0001.png"], [0.0, 0.0, 100.0])
    with pytest.raises(ValueError, match="calibration for camera"):
        colorize_mod.colorize(np.array([[0.0, 0.0, 0.0]]), eo,
                              {None: cam},
                              colorize_mod.find_images(tmp_path))


def test_paint_through_limit_is_real_and_pinned(tmp_path):
    """The occlusion test sees only the points ASSIGNED to a photo, so
    an occluder whose own best photo is a different one does not
    shadow anything. Pinned as KNOWN v1 behavior: if a future change
    fixes it, this test fails and the docs must follow."""
    cam = simple_camera(width=400, height=400, focal_px=300.0)
    for name, val in (("side.png", 250), ("over.png", 30)):
        img = np.zeros((400, 400, 3), dtype=np.uint8)
        img[..., 0] = val
        write_png(tmp_path / name, img)
    # a wall of points at x=30, z=45, and a ground point at x=60 that
    # the side camera can only see through the wall
    wall = np.column_stack([np.full(200, 30.0),
                            np.linspace(-2.0, 2.0, 200),
                            np.full(200, 45.0)])
    hidden = np.array([[60.0, 0.0, 0.0]])
    xyz = np.vstack([wall, hidden])
    origins = np.array([[0.0, 0.0, 90.0], [30.0, 0.0, 120.0]])
    eo = eo_for(["side.png", "over.png"], origins)
    rgb, stats = colorize_mod.colorize(
        xyz, eo, {None: cam}, colorize_mod.find_images(tmp_path))
    plan_cam = rgb[-1]
    # the wall belongs to the overhead photo, so it never enters the
    # side photo's depth grid and the hidden point gets painted
    assert plan_cam.any(), "hidden point uncolored -- occlusion improved?"
