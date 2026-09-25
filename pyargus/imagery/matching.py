"""Finding the same ground in both halves, to a fraction of a pixel.

On a normalized pair the correspondence problem collapses. Matching
points already share a row, so the only thing left to find is how far
across the right half a feature has moved, and that one number IS the
depth. Everything here is therefore one-dimensional, which is not a
simplification so much as the payoff for having normalized at all.

Why a fraction of a pixel and not a pixel. On the delivery this was
written for, one pixel of that shift is about 0.15 ft of height, and
the surface is judged at 0.1 ft. Whole-pixel correlation is therefore
not close to good enough, and measuring that badly while reporting a
confident number is worse than refusing.

Three stages, each earning its place:

**Integer search** finds roughly where, by correlation over a band of
shifts. Cheap and robust, and it tells you when there is nothing to
find -- a patch of unmarked asphalt or a shadow correlates about as
well everywhere, and a peak that does not stand out is reported as
such rather than rounded into an answer.

**A parabola through the peak** gets the fraction. Fitting three
correlation values around the best integer shift is the standard trick
and it is worth about a tenth of a pixel, which is already inside what
is needed.

**A local affine in x** earns its place on sloping ground. A surface
that tilts away makes the right patch a stretched copy of the left,
not a shifted one, and a pure shift then splits the difference and
biases the answer in the direction of the slope -- which, on a
normalized pair, is the direction that becomes height. So the patch is
allowed one scale term as well as a shift. This is the piece whose
absence made an earlier measurement of a job's surveyed control marks
read more than a foot low while the horizontal answer was fine: the
error lives along the baseline, and along the baseline is height.

What is deliberately NOT here: any search in y. On a normalized pair
there is none to do, and a matcher that looks for one would find
noise and call it a correspondence.
"""

import numpy as np


class NoMatch(ValueError):
    """The patch does not correspond to anything findable."""


def _patch(image, col, row, half):
    """A square of image about a pixel, as float, or None at the edge."""
    image = np.asarray(image, dtype=float)
    if image.ndim == 3:
        image = image[..., :3].mean(axis=-1)
    c, r = int(round(col)), int(round(row))
    if (c - half < 0 or r - half < 0
            or c + half + 1 > image.shape[1] or r + half + 1 > image.shape[0]):
        return None
    out = image[r - half:r + half + 1, c - half:c + half + 1]
    return out if np.isfinite(out).all() else None


def _ncc(a, b):
    """Normalised cross-correlation of two equal patches."""
    a = a - a.mean()
    b = b - b.mean()
    na = np.sqrt((a * a).sum())
    nb = np.sqrt((b * b).sum())
    if na < 1e-9 or nb < 1e-9:
        return -1.0
    return float((a * b).sum() / (na * nb))


def _sample_row(image, row, cols):
    """Bilinear sample along one row, for non-integer columns."""
    image = np.asarray(image, dtype=float)
    if image.ndim == 3:
        image = image[..., :3].mean(axis=-1)
    r0 = int(np.floor(row))
    fr = row - r0
    c0 = np.floor(cols).astype(np.int64)
    fc = cols - c0
    h, w = image.shape
    ok = (c0 >= 0) & (c0 < w - 1) & (r0 >= 0) & (r0 < h - 1)
    c0 = np.clip(c0, 0, w - 2)
    r0 = min(max(r0, 0), h - 2)
    top = image[r0, c0] * (1 - fc) + image[r0, c0 + 1] * fc
    bot = image[r0 + 1, c0] * (1 - fc) + image[r0 + 1, c0 + 1] * fc
    return np.where(ok, top * (1 - fr) + bot * fr, np.nan)


def _peak(scores, shifts):
    """Subpixel peak by a parabola through the best three."""
    best = int(np.argmax(scores))
    if best == 0 or best == len(scores) - 1:
        return float(shifts[best]), float(scores[best]), False
    y0, y1, y2 = scores[best - 1], scores[best], scores[best + 1]
    bottom = y0 - 2.0 * y1 + y2
    if abs(bottom) < 1e-12:
        return float(shifts[best]), float(y1), False
    offset = 0.5 * (y0 - y2) / bottom
    if not np.isfinite(offset) or abs(offset) > 1.0:
        return float(shifts[best]), float(y1), False
    step = float(shifts[1] - shifts[0])
    return float(shifts[best]) + offset * step, float(y1), True


def disparity(left, right, col, row, *, half=12, search=40,
              min_score=0.55, min_margin=0.15, affine=True):
    """How far right the feature at (col, row) in ``left`` has moved.

    Returns a dict with the subpixel ``disparity``, the correlation
    ``score``, the ``margin`` by which the peak beat the rest of the
    band, and whether the affine stage ran. Raises :class:`NoMatch`
    rather than returning a weak answer, because on a normalized pair a
    wrong disparity is a wrong elevation and nothing about it looks
    wrong afterwards.

    ``min_margin`` is the one that does the real work, and it is set
    where it is because of a measurement rather than a guess. Highway
    pavement is PERIODIC: rumble strips, lane dashes and joints repeat
    every few feet, so correlation against them has many peaks of
    similar height and the tallest is not reliably the right one. Run
    against the surveyed marks on the delivery this was written for,
    correlation picked disparities from several to nearly forty pixels
    away from the one pixel or so the lidar's own ground predicted --
    inconsistent between marks, which a real disagreement between the
    sensors would not be. All but one were refused on this test, and
    the last, at a margin of 0.13, was not, which is why the default is
    above that.

    The conclusion that finding forces is worth stating here rather
    than in a commit message: on this kind of ground an automatic
    matcher is not a substitute for an operator. A human looking at a
    stereo model rejects the wrong rumble-strip period instantly,
    because they can see it is the wrong one; correlation cannot. The
    matcher's job is to refine a position a person has already put in
    roughly the right place, and to say clearly when it cannot.
    """
    template = _patch(left, col, row, half)
    if template is None:
        raise NoMatch(f"the template at ({col:.0f}, {row:.0f}) runs off the "
                      f"left half")
    if np.ptp(template) < 1e-6:
        raise NoMatch("the template is featureless; there is nothing to find")

    shifts = np.arange(-search, search + 1, dtype=float)
    scores = np.full(shifts.shape, -1.0)
    for i, d in enumerate(shifts):
        other = _patch(right, col + d, row, half)
        if other is not None:
            scores[i] = _ncc(template, other)
    if not np.isfinite(scores).any() or scores.max() < -0.5:
        raise NoMatch("no overlap between the halves at this point")

    best, peak_score, fitted = _peak(scores, shifts)
    if peak_score < min_score:
        raise NoMatch(f"the best correlation is {peak_score:.2f}, under the "
                      f"{min_score:g} needed to call it a correspondence")
    # how much the peak stands out: a featureless patch scores well
    # everywhere, and its peak means nothing
    away = np.abs(shifts - best) > max(3.0, half / 2.0)
    if away.any():
        margin = float(peak_score - np.nanmax(scores[away]))
        if margin < min_margin:
            raise NoMatch(
                f"the peak beats the rest of the band by only {margin:.3f}; "
                f"this patch looks the same at many shifts, so the match "
                f"would be a guess")
    else:
        margin = float("nan")

    scale = 1.0
    if affine:
        best, scale = _affine(left, right, col, row, best, half)

    return {"disparity": float(best), "score": float(peak_score),
            "margin": margin, "subpixel": bool(fitted),
            "scale": float(scale), "half": int(half)}


def _affine(left, right, col, row, shift, half, *, iterations=6):
    """One scale term beside the shift, for ground that slopes away.

    A tilted surface makes the right patch a stretched copy rather than
    a shifted one. Solving for shift alone then splits the difference,
    and the residue biases the answer along the baseline -- which is
    the direction that becomes height, so the bias lands entirely in
    the elevation.
    """
    offsets = np.arange(-half, half + 1, dtype=float)
    template = _sample_row(left, row, col + offsets)
    if not np.isfinite(template).all():
        return shift, 1.0
    template = template - template.mean()
    scale = 1.0
    for _ in range(iterations):
        cols = col + shift + offsets * scale
        sample = _sample_row(right, row, cols)
        if not np.isfinite(sample).all():
            return shift, scale
        # numerical derivatives against shift and scale
        step = 0.25
        d_shift = (_sample_row(right, row, cols + step)
                   - _sample_row(right, row, cols - step)) / (2 * step)
        d_scale = d_shift * offsets
        design = np.column_stack([d_shift, d_scale])
        resid = template - (sample - sample.mean())
        good = np.isfinite(design).all(axis=1) & np.isfinite(resid)
        if good.sum() < 6:
            return shift, scale
        try:
            fix, *_ = np.linalg.lstsq(design[good], resid[good], rcond=None)
        except np.linalg.LinAlgError:
            return shift, scale
        if not np.isfinite(fix).all():
            return shift, scale
        shift += float(np.clip(fix[0], -1.0, 1.0))
        scale += float(np.clip(fix[1], -0.05, 0.05))
        if abs(fix[0]) < 1e-4 and abs(fix[1]) < 1e-5:
            break
        if not (0.8 < scale < 1.25):
            return shift, 1.0
    return shift, scale
