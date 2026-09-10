"""Colorize a cloud from oriented imagery: pick, verify, sample.

The TerraPhoto-shaped decision, kept explainable:

* Each point is colored from the photo that sees it CLOSEST TO ITS
  IMAGE CENTER, chosen among the k nearest camera footprints. Center
  distance favors nadir geometry and the best-corrected part of the
  lens, and it is one number a surveyor can argue with.
* The cloud itself referees occlusion: per photo, a min-range depth
  grid (``occlusion_grid`` pixels per cell) is rendered from EVERY
  candidate point that lands in that frame -- not merely the points
  the photo went on to color -- and a point deeper than its cell's
  minimum by more than ``occlusion_tol`` map units is behind something
  the photo saw. It is not painted with the roof it is hiding under.
* A point whose most-centered view is blocked FALLS BACK to its next
  most-centered view that is not. Only a point hidden in every
  candidate frame stays uncolored, and that is counted separately from
  "no nearby photo saw it".
* Sampling is bilinear on the full-resolution JPEG; LAS RGB is
  16-bit, so 8-bit samples are shifted left 8 bits -- writing them raw
  produces a near-black cloud in every viewer.

WHY THE DEPTH GRID IS BUILT PHOTO-MAJOR. v1 built each photo's grid
from the points ASSIGNED to that photo, because the planner was
point-major -- a chunk of points at a time, competing over their
nearest footprints -- and that is the only per-photo set such a pass
has in hand. It left a real hole: an occluder whose own best photo was
a different one never entered the grid, so it shadowed nothing, and
the guarantee was "occlusion by what this photo colored" rather than
"by the cloud". The occluder of a point sits within a few feet of it
horizontally, which is exactly the neighbourhood the point's OTHER
candidate photos own, so the hole was not exotic: it opened along
every footprint boundary.

The planner is therefore photo-major now. Candidate (point, photo)
pairs are collected for a BATCH of photos at a time, each photo
renders its grid from all of them, and the most-centered contest runs
over the survivors. Batching is what keeps that affordable: the whole
candidate set is ~122M pairs at Summerville (~490 MB as int32) and a
per-photo grid is ~1.2 MB, so ``memory_budget_mb`` fixes how many
photos share one pass over the cloud, and the only cost of a smaller
budget is repeating the k-nearest query (11 s per pass on 15.28M
points).

Two limits of the occlusion test remain, both measured and neither
hidden: (1) an ``occlusion_grid`` cell straddling a depth edge mixes
occluder and background, so a halo about one cell wide -- ~0.7 ft on
the ground at Summerville -- is marked occluded just outside each
shadow. The fallback softens what that costs: such a point is usually
visible in another candidate frame and is colored from there rather
than dropped. (2) The candidate set is the k nearest footprint
CENTERS, computed against a single plane at the cloud's median z, so
neither the assignment nor the occluders ever reach a frame whose
centre is far away, however much relief brings the point into view.

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
    """The assignment: which photo colors which point, and where.

    ``image`` is -1 where nothing colors the point, and ``occluded``
    then says which of the two reasons applies: True means every
    candidate frame had something in front of it, False means no
    candidate frame contained it at all.

    ``n_best_occluded`` counts the points whose MOST-CENTERED view was
    blocked -- the site's own occlusion, independent of whether a
    fallback view rescued it -- and ``n_recovered`` how many of those
    a fallback did rescue.
    """

    def __init__(self, n_points, n_images):
        self.image = np.full(n_points, -1, dtype=np.int32)
        self.col = np.zeros(n_points, dtype=np.float32)
        self.row = np.zeros(n_points, dtype=np.float32)
        self.range = np.zeros(n_points, dtype=np.float32)
        self.occluded = np.zeros(n_points, dtype=bool)
        self.n_images = n_images
        self.n_best_occluded = 0
        self.n_recovered = 0


class _Contest:
    """Most-centered-wins bookkeeping over one stream of candidates.

    Two of these run side by side in the planner: one over EVERY
    candidate that lands in a frame -- which is the assignment v1 made,
    and is kept because "was the best view blocked?" is the honest
    measure of a site's occlusion -- and one over only the candidates
    the depth grids passed, which is what actually gets sampled. Only
    the contest that will be sampled carries pixel coordinates; the
    other keeps three arrays instead of five.
    """

    def __init__(self, n_points, *, pixels, track_hidden=False):
        self.r2 = np.full(n_points, np.inf, dtype=np.float32)
        self.image = np.full(n_points, -1, dtype=np.int32)
        self.pixels = pixels
        self.col = np.zeros(n_points, dtype=np.float32) if pixels else None
        self.row = np.zeros(n_points, dtype=np.float32) if pixels else None
        self.range = np.zeros(n_points, dtype=np.float32) if pixels else None
        self.hidden = (np.zeros(n_points, dtype=bool) if track_hidden
                       else None)

    def offer(self, ids, r2, image, *, col=None, row=None, rng=None,
              hidden=None):
        """Let one photo's candidates challenge the standing winners.

        Strict ``<`` keeps the tie-break the planner has always had:
        photos are offered in ascending index order, so an exact tie
        goes to the lower image index whatever the batching.
        """
        if ids.size == 0:
            return
        better = r2 < self.r2[ids]
        if not better.any():
            return
        sel = ids[better]
        self.r2[sel] = r2[better]
        self.image[sel] = image
        if self.pixels:
            self.col[sel] = col[better]
            self.row[sel] = row[better]
            self.range[sel] = rng[better]
        if self.hidden is not None:
            self.hidden[sel] = hidden[better]


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


def image_batches(usable_idx, n_points, neighbors, memory_budget_mb):
    """Split the photos into groups that share one pass over the cloud.

    The candidate ids for a batch are what has to be held at once:
    ``n_points * neighbors`` pairs spread over all usable photos, four
    bytes each. A batch is sized so its share fits the budget, with
    half again for the skew between a photo over the block interior
    and one at a turn (measured at Summerville: 389k candidates
    against a 117k mean).
    """
    if memory_budget_mb <= 0:
        raise ValueError(f"memory_budget_mb must be > 0, got "
                         f"{memory_budget_mb!r}")
    n_usable = usable_idx.size
    per_image = max(1.0, n_points * neighbors / n_usable) * 4.0 * 1.5
    size = int(max(1.0, memory_budget_mb * 1e6 / per_image))
    return [usable_idx[s:s + size] for s in range(0, n_usable, size)]


def depth_grid(cam, col, row, rng, occlusion_grid):
    """Min range per coarse pixel cell, plus each point's cell key.

    The row stride comes from the image WIDTH: a height-derived stride
    aliases distant cells onto each other on a non-square frame.
    """
    cells_w = cam.width_px // occlusion_grid + 1
    key = (row.astype(np.int64) // occlusion_grid) * cells_w \
        + (col.astype(np.int64) // occlusion_grid)
    nearest = np.full(int(key.max()) + 1, np.inf)
    np.minimum.at(nearest, key, rng)
    return nearest, key


def plan_colorization(xyz, origins, rotations, cameras, *, neighbors=8,
                      margin=2.0, chunk_size=2_000_000, occlusion_tol=3.0,
                      occlusion_grid=8, fallback=True,
                      memory_budget_mb=256, note=None):
    """Assign each point the most-centered photo that actually sees it.

    Candidates are the ``neighbors`` nearest camera footprints, as
    before. What changed is that occlusion is decided HERE, and from
    every candidate that lands in a frame rather than from the points
    the frame went on to color -- see the module docstring for why
    that needs a photo-major pass and what it costs.

    ``fallback`` (default True) lets a point whose best view is blocked
    take its next-best unblocked candidate. With it off, a point is
    colored by its most-centered view or not at all, which was v1's
    rule; the occlusion test itself is the improved one either way.

    ``memory_budget_mb`` bounds the candidate ids held at once; a
    smaller budget only means more passes of the k-nearest query.
    ``note(text)``, if given, is called once per batch -- the planner
    is minutes of silence on a production cloud otherwise.

    Returns a Plan.
    """
    from scipy.spatial import cKDTree

    if int(occlusion_grid) != occlusion_grid or occlusion_grid < 1:
        raise ValueError(f"occlusion_grid must be a whole number of pixels "
                         f">= 1, got {occlusion_grid!r}")
    occlusion_grid = int(occlusion_grid)
    if not occlusion_tol >= 0:
        raise ValueError(f"occlusion_tol must be >= 0 map units, got "
                         f"{occlusion_tol!r}")

    xyz = np.asarray(xyz, dtype=float)
    n_points = xyz.shape[0]
    n_images = len(origins)
    ground_z = float(np.median(xyz[:, 2])) if n_points else 0.0
    centers, usable = footprint_centers(origins, rotations, ground_z)
    usable_idx = np.flatnonzero(usable)
    if usable_idx.size == 0:
        raise ValueError("no photo looks at the ground; check the EO "
                         "Direction vectors")
    tree = cKDTree(centers[usable_idx])
    k = min(neighbors, usable_idx.size)

    half = {}
    for i in usable_idx:
        cam = cameras[i]
        # the score is the off-axis ANGLE (pixels / focal length), not
        # raw pixels: raw pixel distance is f * tan(angle), so a
        # shorter-focal camera would report a smaller number for the
        # same geometry and win every contest against a longer lens
        half[int(i)] = ((cam.width_px - 1) / 2.0, (cam.height_px - 1) / 2.0,
                        float(cam.focal_px))

    # "the best view, blocked or not" is tracked whichever rule is in
    # force: it is the site's own occlusion, and the fallback's
    # recovery is measured against it
    best = _Contest(n_points, pixels=not fallback, track_hidden=True)
    shown = _Contest(n_points, pixels=True) if fallback else None
    seen = np.zeros(n_points, dtype=bool)

    batches = image_batches(usable_idx, n_points, k, memory_budget_mb)
    for b, batch in enumerate(batches):
        if note is not None:
            note(f"planning: photo batch {b + 1} of {len(batches)} "
                 f"({batch.size} photos)")
        lo_id, hi_id = int(batch[0]), int(batch[-1])
        buckets = {int(i): [] for i in batch}
        for start in range(0, n_points, chunk_size):
            stop = min(start + chunk_size, n_points)
            _, near = tree.query(xyz[start:stop, :2], k=k)
            near = near.reshape(stop - start, -1)
            flat_img = usable_idx[near.ravel()]
            flat_pt = np.repeat(np.arange(start, stop, dtype=np.int32),
                                near.shape[1])
            keep = (flat_img >= lo_id) & (flat_img <= hi_id)
            flat_img, flat_pt = flat_img[keep], flat_pt[keep]
            order = np.argsort(flat_img, kind="stable")
            flat_img, flat_pt = flat_img[order], flat_pt[order]
            bounds = np.searchsorted(flat_img, np.arange(n_images + 1))
            for i in buckets:
                a, z = bounds[i], bounds[i + 1]
                if a != z:
                    buckets[i].append(flat_pt[a:z].copy())

        for i in batch:
            i = int(i)
            pieces = buckets.pop(i)
            if not pieces:
                continue
            ids = pieces[0] if len(pieces) == 1 else np.concatenate(pieces)
            pieces.clear()
            cam = cameras[i]
            pts = xyz[ids]
            col, row, in_front = cam.project(rotations[i], origins[i], pts)
            ok = in_front & cam.contains(col, row, margin=margin)
            if not ok.any():
                continue
            ids, col, row = ids[ok], col[ok], row[ok]
            rng = np.linalg.norm(pts[ok] - origins[i], axis=1)
            seen[ids] = True

            # the cloud referees itself, from every candidate in frame
            nearest, key = depth_grid(cam, col, row, rng, occlusion_grid)
            hidden = rng > nearest[key] + occlusion_tol

            hc, hr, focal = half[i]
            r2 = (((col - hc) ** 2 + (row - hr) ** 2)
                  / (focal * focal)).astype(np.float32)
            rng32 = rng.astype(np.float32)
            best.offer(ids, r2, i, col=col, row=row, rng=rng32,
                       hidden=hidden)
            if shown is not None:
                lit = ~hidden
                shown.offer(ids[lit], r2[lit], i, col=col[lit],
                            row=row[lit], rng=rng32[lit])
        del buckets

    plan = Plan(n_points, n_images)
    blocked = best.hidden & (best.image >= 0)
    if fallback:
        plan.image, plan.col = shown.image, shown.col
        plan.row, plan.range = shown.row, shown.range
    else:
        # v1's rule: the most-centered view or nothing at all
        plan.image = np.where(blocked, np.int32(-1), best.image)
        plan.col, plan.row, plan.range = best.col, best.row, best.range
    plan.occluded = seen & (plan.image < 0)
    plan.n_best_occluded = int(blocked.sum())
    plan.n_recovered = int(plan.n_best_occluded - plan.occluded.sum())
    return plan


def apply_plan(plan, images_by_index, *, progress=None):
    """Sample every point the plan assigned.

    ``images_by_index``: image path per EO row. Returns
    (rgb (N, 3) uint16, occluded mask, stats dict). Uncolored points
    keep (0, 0, 0); ``plan.image == -1`` there, and ``plan.occluded``
    separates "hidden in every candidate frame" from "no candidate
    frame contained it".

    Occlusion is decided in plan_colorization, which is where the
    geometry lives; this function is the radiometry and nothing else.

    ``progress(done, total, name)`` is called once per image that is
    opened, in order, with the count of images that will be opened --
    the loop decodes a JPEG per image and is the whole runtime, so a
    caller without it watches a silent process for minutes.
    """
    n = plan.image.shape[0]
    rgb = np.zeros((n, 3), dtype=np.uint16)
    colored = np.zeros(n, dtype=bool)
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

        done += 1
        if progress is not None:
            progress(done, total, Path(images_by_index[i]).name)
        image = load_rgb(images_by_index[i])
        sample = bilinear(image, col, row)
        rgb[idx] = (np.clip(np.rint(sample), 0, 255).astype(np.uint16)) << 8
        colored[idx] = True
        used[i] = idx.size

    n_occluded = int(plan.occluded.sum())
    stats = {
        "n_points": n,
        "n_colored": int(colored.sum()),
        # hidden in EVERY candidate frame, not merely in the best one
        "n_occluded": n_occluded,
        # how often the most-centered view was blocked, and how many of
        # those a next-best view rescued
        "n_best_occluded": int(plan.n_best_occluded),
        "n_recovered": int(plan.n_recovered),
        # "no candidate photo saw it": the candidates are the nearest
        # footprints, so this is not quite "outside every frame" -- a
        # frame whose footprint center is far away is never asked
        "n_unseen": int((plan.image < 0).sum()) - n_occluded,
        "n_images_used": int((used > 0).sum()),
    }
    return rgb, plan.occluded, stats


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
             fallback=True, memory_budget_mb=256, default_tag=None,
             progress=None, note=None):
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
                             margin=margin, occlusion_tol=occlusion_tol,
                             occlusion_grid=occlusion_grid,
                             fallback=fallback,
                             memory_budget_mb=memory_budget_mb, note=note)
    rgb, occluded, stats = apply_plan(plan, ctx["paths"], progress=progress)
    stats["n_eo_rows"] = ctx["n_eo_rows"]
    stats["n_eo_dropped"] = ctx["n_eo_dropped"]
    return rgb, stats
