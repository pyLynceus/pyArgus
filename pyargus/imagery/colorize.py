"""Colorize a cloud from oriented imagery: pick, verify, sample.

The TerraPhoto-shaped decision, kept explainable:

* Each point is colored from the photo that sees it CLOSEST TO ITS
  IMAGE CENTER, chosen among the k nearest camera footprints. Center
  distance favors nadir geometry and the best-corrected part of the
  lens, and it is one number a surveyor can argue with.
* The cloud itself referees occlusion: per photo, its assigned points
  render a min-range depth grid (``occlusion_grid`` pixels per cell),
  and a point deeper than its cell's minimum by more than
  ``occlusion_tol`` map units is behind something the photo saw. It
  stays uncolored and is counted, rather than being painted with the
  roof it is hiding under.

  Two limits of that test, both measured by the review panel and
  neither hidden: (1) the depth grid holds only the points ASSIGNED to
  this photo, so an occluder whose own best photo is a different one
  never enters the grid and paint-through can still happen -- the
  guarantee is "occlusion by what this photo colored", not "by the
  whole cloud"; (2) an 8-px cell straddling a depth edge mixes
  occluder and background, so a thin halo of genuinely visible ground
  just outside a shadow is marked occluded (about one cell projected
  to the ground, ~0.7 ft at Summerville). An occluded point does not
  fall back to its second-best photo either. All three are v1
  behavior, pinned by tests so they cannot change unnoticed.
* Sampling is bilinear on the full-resolution JPEG; LAS RGB is
  16-bit, so 8-bit samples are shifted left 8 bits -- writing them raw
  produces a near-black cloud in every viewer.

Image files are matched to EO rows by CASE-INSENSITIVE bare filename
(real deliveries mix cases -- pyLynceus measured 132 of 366 frames
lower-cased), shallower files winning so preview subfolders never
shadow deliveries. EO rows whose image is missing are dropped WITH A
COUNT: colorizing from the nadir folder alone is legitimate, doing it
silently is not.
"""

from pathlib import Path

import numpy as np

from pyargus.formats import eo as eo_mod
from pyargus.imagery import camera as camera_mod

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".tif", ".tiff", ".png")


def _pillow():
    try:
        from PIL import Image
    except ImportError:
        raise ImportError(
            "reading imagery needs Pillow; install with "
            "pip install pyargus[imagery]") from None
    # Pillow's decompression-bomb guard stays ON: survey frames are
    # ~20 Mpx against its ~179 Mpx default, so raising it would only
    # disarm the guard for a corrupt header in the middle of a
    # thousand-image batch.
    return Image


def find_images(directory):
    """Case-insensitive basename -> path for every image under
    ``directory``; shallower files win, so a vendor's preview folder
    never shadows the delivery.

    The result also carries ``collisions``: the names that matched
    more than one file. Two DIFFERENT images sharing a basename
    (per-flight numbering that restarts, a re-exported copy) would
    otherwise mean every EO row for that name samples one exposure
    through the other's pose -- confidently wrong colors rather than
    missing ones -- so prepare() refuses when a name in use is
    ambiguous.
    """
    directory = Path(directory)
    found, collisions = {}, {}
    candidates = [p for p in directory.rglob("*")
                  if p.suffix.lower() in _IMAGE_SUFFIXES]
    candidates.sort(key=lambda p: (len(p.parts), str(p).lower()))
    for path in candidates:
        key = path.name.lower()
        if key in found:
            collisions.setdefault(key, [found[key]]).append(path)
        else:
            found[key] = path
    return _ImageIndex(found, collisions)


class _ImageIndex(dict):
    """A basename -> path map that remembers ambiguous names."""

    def __init__(self, mapping, collisions):
        super().__init__(mapping)
        self.collisions = collisions


def load_rgb(path):
    """(H, W, 3) uint8 array from an image file."""
    image = _pillow().open(path)
    return np.asarray(image.convert("RGB"))


def check_image_sizes(paths, cameras):
    """Every image must match its camera's calibrated grid.

    Checked UP FRONT, from the JPEG headers alone (Pillow reads size
    lazily), because the alternative is a traceback after nine minutes
    of decoding at image 900.
    """
    Image = _pillow()
    for path, cam in zip(paths, cameras):
        with Image.open(path) as handle:
            width, height = handle.size
        if width != cam.width_px or height != cam.height_px:
            raise ValueError(
                f"{Path(path).name} is {width}x{height} but the "
                f"calibration for camera {cam.name!r} says "
                f"{cam.width_px}x{cam.height_px}; wrong imagery, wrong "
                f"sidecar, or a resized copy")


def bilinear(rgb, col, row):
    """Sample (H, W, 3) uint8 at fractional (col, row) -> (N, 3) float."""
    c0 = np.floor(col).astype(int)
    r0 = np.floor(row).astype(int)
    fc = (col - c0)[:, None]
    fr = (row - r0)[:, None]
    top = rgb[r0, c0].astype(float) * (1 - fc) + rgb[r0, c0 + 1] * fc
    bot = rgb[r0 + 1, c0].astype(float) * (1 - fc) + rgb[r0 + 1, c0 + 1] * fc
    return top * (1 - fr) + bot * fr


class Plan:
    """The assignment: which photo colors which point, and where."""

    def __init__(self, n_points, n_images):
        self.image = np.full(n_points, -1, dtype=np.int32)
        self.col = np.zeros(n_points, dtype=np.float32)
        self.row = np.zeros(n_points, dtype=np.float32)
        self.range = np.zeros(n_points, dtype=np.float32)
        self._r2 = np.full(n_points, np.inf, dtype=np.float32)
        self.n_images = n_images


def footprint_centers(origins, rotations, ground_z):
    """Where each photo's optical axis meets the ground plane.

    Returns (centers (M, 2), usable mask). A photo looking level or
    upward cannot meet the ground and is unusable for colorizing it.
    """
    axis = -rotations[:, :, 2]                       # ground-space look
    usable = axis[:, 2] < -1e-6
    t = np.where(usable, (ground_z - origins[:, 2]) / np.where(
        usable, axis[:, 2], -1.0), 0.0)
    centers = origins[:, :2] + axis[:, :2] * t[:, None]
    return centers, usable


def plan_colorization(xyz, origins, rotations, cameras, *, neighbors=8,
                      margin=2.0, chunk_size=2_000_000):
    """Assign each point its best photo (most-centered visible pixel
    among the ``neighbors`` nearest footprints). Occlusion is judged
    later, per photo. Returns a Plan."""
    from scipy.spatial import cKDTree

    xyz = np.asarray(xyz, dtype=float)
    n_images = len(origins)
    ground_z = float(np.median(xyz[:, 2]))
    centers, usable = footprint_centers(origins, rotations, ground_z)
    usable_idx = np.flatnonzero(usable)
    if usable_idx.size == 0:
        raise ValueError("no photo looks at the ground; check the EO "
                         "Direction vectors")
    tree = cKDTree(centers[usable_idx])
    k = min(neighbors, usable_idx.size)

    plan = Plan(xyz.shape[0], n_images)
    half = {}
    for i in usable_idx:
        cam = cameras[i]
        # the score is the off-axis ANGLE (pixels / focal length), not
        # raw pixels: raw pixel distance is f * tan(angle), so a
        # shorter-focal camera would report a smaller number for the
        # same geometry and win every contest against a longer lens
        half[i] = ((cam.width_px - 1) / 2.0, (cam.height_px - 1) / 2.0,
                   float(cam.focal_px))

    for start in range(0, xyz.shape[0], chunk_size):
        stop = min(start + chunk_size, xyz.shape[0])
        pts = xyz[start:stop]
        _, near = tree.query(pts[:, :2], k=k)
        near = near.reshape(len(pts), -1)
        flat_img = usable_idx[near.ravel()]
        flat_pt = np.repeat(np.arange(len(pts)), near.shape[1])
        order = np.argsort(flat_img, kind="stable")
        flat_img = flat_img[order]
        flat_pt = flat_pt[order]
        bounds = np.searchsorted(flat_img, np.arange(n_images + 1))
        for i in usable_idx:
            lo, hi = bounds[i], bounds[i + 1]
            if lo == hi:
                continue
            pt = flat_pt[lo:hi]
            cam = cameras[i]
            col, row, in_front = cam.project(rotations[i], origins[i],
                                             pts[pt])
            ok = in_front & cam.contains(col, row, margin=margin)
            if not ok.any():
                continue
            pt = pt[ok]
            col, row = col[ok], row[ok]
            hc, hr, focal = half[i]
            r2 = (((col - hc) ** 2 + (row - hr) ** 2)
                  / (focal * focal)).astype(np.float32)
            better = r2 < plan._r2[start + pt]
            if not better.any():
                continue
            sel = pt[better]
            plan._r2[start + sel] = r2[better]
            plan.image[start + sel] = i
            plan.col[start + sel] = col[better]
            plan.row[start + sel] = row[better]
            plan.range[start + sel] = np.linalg.norm(
                pts[sel] - origins[i], axis=1)
    return plan


def apply_plan(plan, images_by_index, cameras, *, occlusion_tol=3.0,
               occlusion_grid=8, progress=None):
    """Occlusion-check and sample every assigned point.

    ``images_by_index``: image path per EO row. Returns
    (rgb (N, 3) uint16, occluded mask, stats dict). Uncolored points
    keep (0, 0, 0) and plan.image == -1 or occluded True.

    ``progress(done, total, name)`` is called once per image that is
    opened, in order, with the count of images that will be opened --
    the loop decodes a JPEG per image and is the whole runtime, so a
    caller without it watches a silent process for minutes.
    """
    n = plan.image.shape[0]
    rgb = np.zeros((n, 3), dtype=np.uint16)
    colored = np.zeros(n, dtype=bool)
    occluded = np.zeros(n, dtype=bool)
    used = np.zeros(plan.n_images, dtype=np.int64)

    order = np.argsort(plan.image, kind="stable")
    assigned = order[plan.image[order] >= 0]
    bounds = np.searchsorted(plan.image[assigned], np.arange(plan.n_images + 1))
    total = int(np.sum(np.diff(bounds) > 0))
    done = 0
    for i in range(plan.n_images):
        lo, hi = bounds[i], bounds[i + 1]
        if lo == hi:
            continue
        idx = assigned[lo:hi]
        col = plan.col[idx].astype(float)
        row = plan.row[idx].astype(float)
        rng = plan.range[idx].astype(float)

        # the cloud referees itself: min range per coarse pixel cell
        cam = cameras[i]
        cells_w = cam.width_px // occlusion_grid + 1
        key = (row.astype(int) // occlusion_grid) * cells_w \
            + (col.astype(int) // occlusion_grid)
        nearest = np.full(key.max() + 1, np.inf)
        np.minimum.at(nearest, key, rng)
        hidden = rng > nearest[key] + occlusion_tol
        occluded[idx[hidden]] = True
        idx, col, row = idx[~hidden], col[~hidden], row[~hidden]
        if idx.size == 0:
            continue

        done += 1
        if progress is not None:
            progress(done, total, Path(images_by_index[i]).name)
        image = load_rgb(images_by_index[i])
        sample = bilinear(image, col, row)
        rgb[idx] = (np.clip(np.rint(sample), 0, 255).astype(np.uint16)) << 8
        colored[idx] = True
        used[i] = idx.size

    stats = {
        "n_points": n,
        "n_colored": int(colored.sum()),
        "n_occluded": int(occluded.sum()),
        # "no candidate photo saw it": the candidates are the nearest
        # footprints, so this is not quite "outside every frame" -- a
        # frame whose footprint center is far away is never asked
        "n_unseen": int((plan.image < 0).sum()),
        "n_images_used": int((used > 0).sum()),
    }
    return rgb, occluded, stats


def prepare(eo, cameras_by_tag, image_paths, *, default_tag=None):
    """Resolve EO rows against image files and calibrations.

    Returns a context dict: ``origins``/``rotations`` per usable row,
    ``cameras``/``paths``/``tags`` lists aligned with them, and the
    drop count. EO rows without an image file are dropped and counted
    -- colorizing from one camera folder is legitimate, doing it
    silently is not.
    """
    collisions = getattr(image_paths, "collisions", None) or {}
    ambiguous = sorted({name for name in eo["filename"]
                        if name.lower() in collisions})
    if ambiguous:
        first = collisions[ambiguous[0].lower()]
        raise ValueError(
            f"{len(ambiguous)} EO row(s) name an image that exists more "
            f"than once under the imagery directory, e.g. {ambiguous[0]}: "
            f"{first[0]} and {first[1]}. Which exposure that row means is "
            f"a guess, and guessing wrong paints the cloud from the wrong "
            f"photo. Point --images at one flight's imagery.")
    keep, cams, paths, tags = [], [], [], []
    for j, name in enumerate(eo["filename"]):
        path = image_paths.get(name.lower())
        if path is None:
            continue
        tag = eo_mod.camera_tag(name) or default_tag
        cam = cameras_by_tag.get(tag)
        if cam is None:
            raise ValueError(
                f"no camera calibration for tag {tag!r} (image {name}); "
                f"a .cal sidecar per camera folder, or --cal, is required "
                f"-- the distortion is worth ~30 px at the corner")
        keep.append(j)
        cams.append(cam)
        paths.append(path)
        tags.append(tag)
    if not keep:
        raise ValueError("none of the EO rows' images exist under the "
                         "imagery directory; wrong --images path?")
    keep = np.array(keep)
    return {
        "origins": eo["origin"][keep],
        "rotations": eo_mod.rotations_from_direction_up(
            eo["direction"][keep], eo["up"][keep]),
        "cameras": cams,
        "paths": paths,
        "tags": tags,
        "n_eo_rows": len(eo["filename"]),
        "n_eo_dropped": len(eo["filename"]) - len(keep),
    }


def colorize(xyz, eo, cameras_by_tag, image_paths, *, neighbors=8,
             margin=2.0, occlusion_tol=3.0, occlusion_grid=8,
             default_tag=None, progress=None):
    """The whole bridge for in-memory arrays. Returns (rgb, stats).

    ``eo`` is formats.eo.read_eo_csv output; ``cameras_by_tag`` maps
    camera-role tags (formats.eo.camera_tag) to Camera objects, with
    ``default_tag`` naming the entry used for untagged filenames;
    ``image_paths`` maps LOWER-CASE image basenames to paths (see
    find_images). Callers that need the per-point assignment (which
    photo colored what) compose prepare -> plan_colorization ->
    apply_plan themselves; this is that composition and nothing more.
    """
    ctx = prepare(eo, cameras_by_tag, image_paths, default_tag=default_tag)
    check_image_sizes(ctx["paths"], ctx["cameras"])
    plan = plan_colorization(xyz, ctx["origins"], ctx["rotations"],
                             ctx["cameras"], neighbors=neighbors,
                             margin=margin)
    rgb, occluded, stats = apply_plan(
        plan, ctx["paths"], ctx["cameras"], occlusion_tol=occlusion_tol,
        occlusion_grid=occlusion_grid, progress=progress)
    stats["n_eo_rows"] = ctx["n_eo_rows"]
    stats["n_eo_dropped"] = ctx["n_eo_dropped"]
    return rgb, stats
