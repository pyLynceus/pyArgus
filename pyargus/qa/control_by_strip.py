"""The control decomposition: what does EACH strip read at EACH mark?

A merged control report averages every strip into one laser Z per
mark, which is exactly the view that cannot distinguish a
misalignment from a mark problem. This decomposition (born as a
hand-script on the SH 151 case, where it exonerated the lidar in an
afternoon) answers the three questions that identify the mechanism:

* per-strip bias -- does each strip carry its own dz? (misalignment)
* per-mark agreement -- do all strips read the same wrong value?
  (position-locked: the mark, the survey, or a pre-applied warp)
* grade correction -- does the offset survive a local plane fit, or
  was it slope sampling?

Clouds are streamed in chunks and only points near marks are kept, so
a 50 GB strip set costs one pass of I/O and no memory.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def gather_near_marks(las_paths, mark_e, mark_n, *, radius=3.0,
                      ground_class=None, chunk_size=5_000_000):
    """Stream clouds, keeping points within ``radius`` of any mark.

    Returns {strip_label: {mark_index: (x, y, z) arrays}}. Strips are
    labeled by point_source_id when a single file holds several, by
    file stem otherwise. ``ground_class`` filters to one class (None
    keeps everything -- the right default for unclassified strips).
    """
    import laspy

    mark_e = np.asarray(mark_e, dtype=float)
    mark_n = np.asarray(mark_n, dtype=float)
    out = defaultdict(lambda: defaultdict(lambda: [[], [], []]))
    for path in las_paths:
        stem = Path(path).stem
        with laspy.open(str(path)) as reader:
            h = reader.header
            near = ((mark_e >= h.mins[0] - radius)
                    & (mark_e <= h.maxs[0] + radius)
                    & (mark_n >= h.mins[1] - radius)
                    & (mark_n <= h.maxs[1] + radius))
            candidates = np.flatnonzero(near)
            if candidates.size == 0:
                continue
            ce, cn = mark_e[candidates], mark_n[candidates]
            for pts in reader.chunk_iterator(chunk_size):
                x = np.asarray(pts.x)
                y = np.asarray(pts.y)
                z = np.asarray(pts.z)
                psid = np.asarray(pts.point_source_id)
                cls = np.asarray(pts.classification)
                keep_base = np.ones(x.size, dtype=bool)
                if ground_class is not None:
                    keep_base = cls == ground_class
                for k in range(candidates.size):
                    m = (keep_base
                         & (np.abs(x - ce[k]) <= radius)
                         & (np.abs(y - cn[k]) <= radius))
                    if not m.any():
                        continue
                    for sid in np.unique(psid[m]):
                        sm = m & (psid == sid)
                        label = stem if len(las_paths) > 1 else f"{sid}"
                        bucket = out[label][int(candidates[k])]
                        bucket[0].extend(x[sm])
                        bucket[1].extend(y[sm])
                        bucket[2].extend(z[sm])
    return {strip: {mark: tuple(np.array(a) for a in arrays)
                    for mark, arrays in marks.items()}
            for strip, marks in out.items()}


@dataclass
class Cell:
    strip: str
    mark: int
    n: int
    dz_median: float      # median z minus known z
    dz_plane: float       # local plane evaluated AT the mark, minus known
    slope: float          # |grad| of that plane, rise/run


@dataclass
class ControlByStrip:
    cells: list           # Cell records
    mark_ids: list        # printable id per mark index
    known_z: np.ndarray

    def per_strip(self, min_marks=2):
        """{strip: {n, median, nmad}} over marks the strip covers."""
        groups = defaultdict(list)
        for cell in self.cells:
            groups[cell.strip].append(cell.dz_median)
        out = {}
        for strip, values in sorted(groups.items()):
            if len(values) < min_marks:
                continue
            arr = np.array(values)
            med = float(np.median(arr))
            out[strip] = {"n": arr.size, "median": med,
                          "nmad": float(1.4826 * np.median(np.abs(arr - med)))}
        return out

    def per_mark(self):
        """{mark_id: {n_strips, mean_dz, spread, dz_plane}} -- spread
        near zero with mean_dz far from zero is the position-locked
        signature."""
        groups = defaultdict(list)
        planes = defaultdict(list)
        for cell in self.cells:
            groups[cell.mark].append(cell.dz_median)
            planes[cell.mark].append(cell.dz_plane)
        out = {}
        for mark, values in sorted(groups.items()):
            arr = np.array(values)
            out[self.mark_ids[mark]] = {
                "n_strips": arr.size,
                "mean_dz": float(arr.mean()),
                "spread": float(arr.max() - arr.min()),
                "dz_plane": float(np.median(planes[mark])),
            }
        return out


def _plane_at_mark(x, y, z, e, n):
    a = np.column_stack([x - e, y - n, np.ones(x.size)])
    coef, *_ = np.linalg.lstsq(a, z, rcond=None)
    r = z - a @ coef
    med = np.median(r)
    keep = np.abs(r - med) < 3 * (1.4826 * np.median(np.abs(r - med)) + 1e-6)
    if keep.sum() >= 12:
        coef, *_ = np.linalg.lstsq(a[keep], z[keep], rcond=None)
    return float(coef[2]), float(np.hypot(coef[0], coef[1]))


def decompose(gathered, mark_ids, mark_e, mark_n, mark_z, *, min_points=8):
    """Build the decomposition from a gather. Marks with fewer than
    ``min_points`` points from a strip contribute no cell for it."""
    mark_e = np.asarray(mark_e, dtype=float)
    mark_n = np.asarray(mark_n, dtype=float)
    mark_z = np.asarray(mark_z, dtype=float)
    cells = []
    for strip in sorted(gathered):
        for mark, (x, y, z) in sorted(gathered[strip].items()):
            if x.size < min_points:
                continue
            plane_z, slope = _plane_at_mark(x, y, z, mark_e[mark],
                                            mark_n[mark])
            cells.append(Cell(
                strip=strip, mark=mark, n=int(x.size),
                dz_median=float(np.median(z) - mark_z[mark]),
                dz_plane=plane_z - float(mark_z[mark]),
                slope=slope))
    if not cells:
        raise ValueError("no strip has enough points near any mark; "
                         "wrong radius, wrong class filter, or the "
                         "control is not on this cloud")
    return ControlByStrip(cells=cells, mark_ids=list(mark_ids),
                          known_z=mark_z)
