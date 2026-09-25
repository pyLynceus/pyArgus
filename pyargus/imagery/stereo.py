"""Two photographs made fusible: the normalized pair.

Human eyes fuse a stereo pair only when corresponding points sit on the
SAME ROW. Two frames from a moving aircraft never do: each has its own
attitude, and the difference throws corresponding points up and down as
well as across. That vertical difference is y-parallax, and it is not a
detail. A few pixels of it is tiring, a few tens of pixels cannot be
fused at all, and no amount of good geometry underneath rescues it.

The cure is to resample both frames as though they had been taken by
one camera in two positions, with its x-axis along the baseline. Then
every corresponding pair shares a row by construction, and the only
disagreement left is horizontal, which IS the depth. That rebuilt pair
is the normalized (or epipolar) pair, and it is what every display mode
consumes: anaglyph, side by side, page-flipped, or a file for other
software. The display is a choice made at the end; this is the part
that has to be right.

Two things here are worth stating because they are easy to get wrong.

**The warp does not depend on the scene.** Both images are central
projections from their own perspective centres, so mapping one to the
normalized frame is a pure rotation composed with the lens model. No
surface, no height, no DTM enters. Resampling onto a ground plane at
some assumed height is the other approach and it is worse: it leaves
residual parallax wherever the ground is not at that height, in a
direction that is not purely horizontal, which is exactly what cannot
be fused.

**The resampling is done through the forward model that is already
validated.** A point far along the output ray is handed to
``Camera.project``, the same function that colorized 1,083 photographs,
rather than a second implementation of the lens that could disagree
with the first. Projection is scale-invariant along a ray, so the
distance chosen cannot matter, and the test asserts that.

The pair also reports its own geometry, because a pair that fuses
beautifully can still be useless: see ``base_over_height``. On the rig
this was written for, ADJACENT frames fuse perfectly and measure
nothing, at one and a quarter feet of height per pixel of parallax.
"""

import numpy as np

from pyargus.imagery import intersect as intersect_mod

FAR = 1.0e6          # a point this far along a ray is a direction


def normalized_rotation(origin_a, r_a, origin_b, r_b):
    """The common camera-to-ground rotation for a normalized pair.

    x runs along the baseline, so parallax becomes purely horizontal.
    z is the mean viewing direction made perpendicular to x, so the
    rebuilt camera looks where the two real ones were looking and the
    warp stays as small as it can be. y completes a right-handed set,
    matching the photo frame's y-up convention.
    """
    origin_a = np.asarray(origin_a, dtype=float)
    origin_b = np.asarray(origin_b, dtype=float)
    base = origin_b - origin_a
    length = float(np.linalg.norm(base))
    if length < 1e-9:
        raise ValueError("the two frames share a perspective centre; there "
                         "is no baseline and no stereo to be had")
    x = base / length
    look = -(np.asarray(r_a, float)[:, 2] + np.asarray(r_b, float)[:, 2])
    look = look / np.linalg.norm(look)
    z = -look
    z = z - np.dot(z, x) * x
    zn = float(np.linalg.norm(z))
    if zn < 1e-9:
        raise ValueError("the cameras look along their own baseline, so a "
                         "normalized pair cannot be built from them")
    z = z / zn
    y = np.cross(z, x)
    return np.column_stack([x, y, z]), length


def base_over_height(origin_a, origin_b, ground_z):
    """Baseline over height above the ground being looked at."""
    a = np.asarray(origin_a, float)
    b = np.asarray(origin_b, float)
    height = 0.5 * (a[2] + b[2]) - float(ground_z)
    if height <= 0:
        raise ValueError(f"the cameras are not above the ground elevation "
                         f"given ({ground_z:g})")
    return float(np.linalg.norm(b[:2] - a[:2]) / height)


def height_per_pixel(origin_a, origin_b, ground_z, focal_px):
    """Map units of height per pixel of horizontal parallax.

    The number that says whether a pair can answer the question being
    asked of it, before any image is resampled.
    """
    height = 0.5 * (origin_a[2] + origin_b[2]) - float(ground_z)
    base = float(np.linalg.norm(np.asarray(origin_b)[:2]
                                - np.asarray(origin_a)[:2]))
    if base <= 0:
        raise ValueError("no baseline")
    return float(height / base) * float(height) / float(focal_px)


def _sample(image, col, row):
    """Bilinear sample, NaN outside. Works on grey or colour."""
    image = np.asarray(image)
    h, w = image.shape[:2]
    c0 = np.floor(col).astype(np.int64)
    r0 = np.floor(row).astype(np.int64)
    fc = col - c0
    fr = row - r0
    inside = (c0 >= 0) & (c0 < w - 1) & (r0 >= 0) & (r0 < h - 1)
    c0 = np.clip(c0, 0, w - 2)
    r0 = np.clip(r0, 0, h - 2)
    if image.ndim == 3:
        fc = fc[..., None]
        fr = fr[..., None]
    top = image[r0, c0] * (1 - fc) + image[r0, c0 + 1] * fc
    bot = image[r0 + 1, c0] * (1 - fc) + image[r0 + 1, c0 + 1] * fc
    out = (top * (1 - fr) + bot * fr).astype(float)
    return np.where(inside[..., None] if image.ndim == 3 else inside,
                    out, np.nan)


def resample(camera, r_cam, origin, image, r_norm, *, focal_px, size,
             centre=(0.0, 0.0)):
    """One frame rebuilt in the normalized frame ``r_norm``.

    ``size`` is (width, height) in pixels of the output, ``centre`` the
    ideal normalized coordinates the output's middle should look along,
    which is how a review window is pointed somewhere without
    resampling a whole 20 megapixel frame.
    """
    width, height = int(size[0]), int(size[1])
    u = (np.arange(width) - (width - 1) / 2.0) / focal_px + centre[0]
    v = (np.arange(height) - (height - 1) / 2.0) / focal_px + centre[1]
    xn, yn = np.meshgrid(u, v)
    # the photo-frame convention Camera uses: ideal (x, y) looks along
    # (x, -y, -1) in the camera's own axes
    d_cam = np.stack([xn, -yn, -np.ones_like(xn)], axis=-1)
    d_ground = d_cam @ np.asarray(r_norm, float).T
    far = np.asarray(origin, float) + d_ground * FAR
    col, row, ok = camera.project(r_cam, origin,
                                  far.reshape(-1, 3))
    col = col.reshape(height, width)
    row = row.reshape(height, width)
    ok = ok.reshape(height, width) & camera.contains(col, row)
    out = _sample(image, np.where(ok, col, 0.0), np.where(ok, row, 0.0))
    out = np.where(ok[..., None] if out.ndim == 3 else ok, out, np.nan)
    return out, ok


def pair(camera_a, r_a, origin_a, image_a,
         camera_b, r_b, origin_b, image_b, *,
         ground_z, size=(900, 700), focal_px=None, centre_xyz=None,
         refuse_below=None):
    """A normalized stereo pair, plus what it is worth.

    Returns ``(left, right, info)``. ``info`` carries the geometry --
    baseline, base-to-height, height per pixel of parallax, the angle
    between the rays at ``centre_xyz`` -- so a caller can refuse a pair
    before an operator ever looks at it. ``refuse_below`` is that angle
    in degrees.
    """
    r_norm, base = normalized_rotation(origin_a, r_a, origin_b, r_b)
    focal = float(focal_px if focal_px is not None
                  else 0.5 * (camera_a.focal_px + camera_b.focal_px))
    if centre_xyz is None:
        mid = 0.5 * (np.asarray(origin_a, float) + np.asarray(origin_b, float))
        centre_xyz = np.array([mid[0], mid[1], float(ground_z)])
    centre_xyz = np.asarray(centre_xyz, dtype=float)

    # Convergence. Each half is centred on ITS OWN direction to the
    # point of interest, so the target sits in the middle of both and
    # everything else shows parallax relative to it -- which is what an
    # operator driving a floating mark needs. Using one common centre
    # instead leaves the halves separated by the full parallax, which
    # on this rig is 1,600 px: two windows onto different scenery.
    #
    # Only the HORIZONTAL centre may differ. Because the baseline lies
    # along the normalized x-axis, the two cameras' normalized y for
    # any point are identical, and that identity IS the absence of
    # y-parallax. Shifting the halves by different amounts vertically
    # would destroy the one property this module exists to provide, so
    # the vertical centre is shared and taken from the midpoint.
    centres = []
    for origin in (origin_a, origin_b):
        u = (centre_xyz - np.asarray(origin, float)) @ r_norm
        if -u[2] <= 0:
            raise ValueError("the point of interest is behind a camera")
        centres.append((u[0] / -u[2], -u[1] / -u[2]))
    if abs(centres[0][1] - centres[1][1]) > 1e-9:
        raise AssertionError(
            f"the two halves want different vertical centres "
            f"({centres[0][1]:.3e} against {centres[1][1]:.3e}); the "
            f"normalized frame is not built along the baseline")
    centre = (0.5 * (centres[0][0] + centres[1][0]), centres[0][1])

    rays = np.array([centre_xyz - np.asarray(origin_a, float),
                     centre_xyz - np.asarray(origin_b, float)])
    angle = intersect_mod.max_angle(rays)
    if refuse_below is not None and angle < refuse_below:
        raise intersect_mod.WeakGeometry(
            f"these two frames see the point {angle:.2f} degrees apart, "
            f"under the {refuse_below:g} asked for. They will fuse and they "
            f"will not measure: one pixel of parallax is "
            f"{height_per_pixel(origin_a, origin_b, ground_z, focal):.3f} "
            f"map units of height. Choose frames further apart.")

    left, ok_a = resample(camera_a, r_a, origin_a, image_a, r_norm,
                          focal_px=focal, size=size, centre=centres[0])
    right, ok_b = resample(camera_b, r_b, origin_b, image_b, r_norm,
                           focal_px=focal, size=size, centre=centres[1])
    info = {"baseline": float(base),
            "centres": (tuple(float(v) for v in centres[0]),
                        tuple(float(v) for v in centres[1])),
            "origins": (tuple(float(v) for v in np.asarray(origin_a, float)),
                        tuple(float(v) for v in np.asarray(origin_b, float))),
            "size": (int(size[0]), int(size[1])),
            "base_over_height": base_over_height(origin_a, origin_b, ground_z),
            "height_per_pixel": height_per_pixel(origin_a, origin_b,
                                                 ground_z, focal),
            "angle_deg": float(angle),
            "focal_px": focal,
            "centre": (float(centre[0]), float(centre[1])),
            "r_norm": r_norm,
            "coverage": (float(ok_a.mean()), float(ok_b.mean()))}
    return left, right, info


def project_into_pair(info, origin_a, origin_b, xyz, size):
    """Where a ground point lands in each half of a normalized pair.

    The check that the pair is really normalized -- the two rows must
    agree -- and the way a surface gets drawn into both halves.
    """
    r_norm = np.asarray(info["r_norm"], float)
    focal = info["focal_px"]
    width, height = int(size[0]), int(size[1])
    centres = info.get("centres", (info["centre"], info["centre"]))
    out = []
    for origin, centre in zip((origin_a, origin_b), centres):
        d = np.asarray(xyz, float).reshape(-1, 3) - np.asarray(origin, float)
        u = d @ r_norm
        z = -u[:, 2]
        with np.errstate(invalid="ignore", divide="ignore"):
            x = u[:, 0] / z
            y = -u[:, 1] / z
        col = (x - centre[0]) * focal + (width - 1) / 2.0
        row = (y - centre[1]) * focal + (height - 1) / 2.0
        out.append(np.column_stack([col, row]))
    return out[0], out[1]


def ray_from_pair(info, origin, col, row):
    """A pixel in one half of a normalized pair -> a ground direction.

    The inverse of :func:`project_into_pair`. There is no lens here:
    the halves were built distortion-free, so this is the pinhole plus
    the common rotation, and it is exact.
    """
    r_norm = np.asarray(info["r_norm"], float)
    focal = info["focal_px"]
    width, height = info["size"]
    which = 0 if np.allclose(origin, info["origins"][0]) else 1
    centre = info.get("centres", (info["centre"], info["centre"]))[which]
    col = np.atleast_1d(np.asarray(col, dtype=float))
    row = np.atleast_1d(np.asarray(row, dtype=float))
    x = (col - (width - 1) / 2.0) / focal + centre[0]
    y = (row - (height - 1) / 2.0) / focal + centre[1]
    u = np.column_stack([x, -y, -np.ones_like(x)])
    d = u @ r_norm.T
    return d / np.linalg.norm(d, axis=1, keepdims=True)


def measure(info, col, row, disparity, *, refuse_below=None):
    """One ground coordinate from a point and its disparity.

    ``col``/``row`` locate the feature in the LEFT half and
    ``disparity`` is how far right it sits in the other, which is what
    :func:`pyargus.imagery.matching.disparity` returns. The two rays
    are intersected rather than the disparity being inverted
    algebraically, so the answer carries the geometry's own condition
    and can be refused on it.
    """
    o_a, o_b = (np.asarray(o, dtype=float) for o in info["origins"])
    d_a = ray_from_pair(info, o_a, col, row)[0]
    d_b = ray_from_pair(info, o_b, col + disparity, row)[0]
    xyz, report = intersect_mod.intersect([o_a, o_b], [d_a, d_b],
                                          refuse_below=refuse_below)
    report["disparity"] = float(disparity)
    return xyz, report


def choose_partner(camera, rotations, origins, anchor, xyz, *,
                   band=(0.35, 0.75), min_margin_px=400, limit=None):
    """Rank the frames that pair well with ``anchor`` on ``xyz``.

    Geometry alone is not enough and the failure is easy to miss: a
    frame with a perfect base-to-height ratio can hold the point of
    interest ten pixels from its own edge, and the rebuilt half then
    comes back half black. So a candidate must ALSO see the target with
    room around it, and ``min_margin_px`` is that room -- roughly how
    far the review window will reach from the centre.

    Returns a list of dicts, best first, each carrying the numbers a
    caller needs to refuse it: the base, the base-to-height ratio, the
    angle between the rays and the height a pixel of parallax is worth.
    Sorted by how close the ratio sits to the middle of ``band``, which
    trades relief against how differently the two frames see the same
    ground.
    """
    xyz = np.asarray(xyz, dtype=float).reshape(1, 3)
    origins = np.asarray(origins, dtype=float)
    ground_z = float(xyz[0, 2])

    def margin(index):
        col, row, ok = camera.project(rotations[index], origins[index], xyz)
        if not ok[0]:
            return -1.0
        return float(min(col[0], row[0],
                         camera.width_px - 1 - col[0],
                         camera.height_px - 1 - row[0]))

    if margin(anchor) < min_margin_px:
        raise ValueError(
            f"the anchor frame holds the point {margin(anchor):.0f} px from "
            f"its own edge, under the {min_margin_px} asked for; a review "
            f"window there would run off the frame")

    middle = 0.5 * (band[0] + band[1])
    out = []
    for i in range(len(origins)):
        if i == anchor:
            continue
        try:
            ratio = base_over_height(origins[anchor], origins[i], ground_z)
        except ValueError:
            continue
        if not band[0] <= ratio <= band[1]:
            continue
        room = margin(i)
        if room < min_margin_px:
            continue
        rays = np.array([xyz[0] - origins[anchor], xyz[0] - origins[i]])
        out.append({
            "index": int(i),
            "base": float(np.linalg.norm(origins[i][:2] - origins[anchor][:2])),
            "base_over_height": ratio,
            "angle_deg": intersect_mod.max_angle(rays),
            "height_per_pixel": height_per_pixel(origins[anchor], origins[i],
                                                 ground_z, camera.focal_px),
            "margin_px": room})
    out.sort(key=lambda r: (abs(r["base_over_height"] - middle),
                            -r["margin_px"]))
    return out[:limit] if limit else out


def anaglyph(left, right, *, mode="red-cyan"):
    """One image for red/cyan glasses, from a normalized pair.

    Deliberately the dullest possible compositing: the left eye's
    luminance in red, the right eye's in green and blue. Colour is lost
    and that is the price of the cheapest display there is.
    """
    def grey(a):
        a = np.asarray(a, dtype=float)
        return a if a.ndim == 2 else a[..., :3].mean(axis=-1)

    l, r = grey(left), grey(right)
    if l.shape != r.shape:
        raise ValueError(f"the halves differ in size, {l.shape} and {r.shape}")
    out = np.zeros(l.shape + (3,), dtype=float)
    out[..., 0] = np.nan_to_num(l)
    out[..., 1] = np.nan_to_num(r)
    out[..., 2] = np.nan_to_num(r)
    if mode == "cyan-red":
        out = out[..., ::-1]
    return np.clip(out, 0, 255)
