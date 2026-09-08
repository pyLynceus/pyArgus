"""Surface correspondences between two strips: the observations.

For each grid cell of the overlap where both strips have enough
points, a plane is fitted to strip A's points; the observation is the
signed distance from strip B's local centroid to that plane, along its
normal. Patches that are not planar enough, too steep, too thin, or
absurdly far apart are dropped -- a wall, a canopy tuft, or a moving
vehicle must not become an observation.

Each correspondence carries the pieces the solver needs, derived from
the point nearest the centroid on each side (its navigation state is
exact where an averaged heading could wrap):

    n . (dX_A - dX_B) = d
    dX = -R_nav [b]x dbeta + t_strip
    n . R_nav [b]x dbeta = dbeta . (m x b),  m = R_nav^T n

so the boresight row is (m_B x b_B) - (m_A x b_A), and the offset rows
are +n on A and -n on B.
"""

from dataclasses import dataclass

import numpy as np

from pyargus.core import gridding


@dataclass
class Correspondences:
    """Observations for one strip pair (indices into the solver's list)."""
    a: int
    b: int
    d: np.ndarray        # (K,) signed distance, B relative to A's plane
    normal: np.ndarray   # (K, 3) plane normals, +z up
    j_beta: np.ndarray   # (K, 3) boresight Jacobian rows
    cells: int           # cells considered before the quality gates


def _nearest_to_centroid(xyz, index):
    centroid = xyz[index].mean(axis=0)
    return index[np.argmin(np.sum((xyz[index] - centroid) ** 2, axis=1))]


def correspondences(bundle_a, bundle_b, xyz_a, xyz_b, a, b, *, cell=5.0,
                    min_points=8, max_rms=None, min_normal_z=0.7,
                    max_distance=None):
    """Build patch observations for one pair; xyz_* are the CURRENT
    (possibly corrected) coordinates, while navigation state and body
    vectors come from the bundles.

    ``max_rms`` (plane-fit rms gate) defaults to cell/25; a patch whose
    residual exceeds it is not a surface. ``max_distance`` (blunder
    gate on |d|) defaults to cell/2.
    """
    if max_rms is None:
        max_rms = cell / 25.0
    if max_distance is None:
        max_distance = cell / 2.0

    lo = np.maximum(xyz_a[:, :2].min(axis=0), xyz_b[:, :2].min(axis=0))
    hi = np.minimum(xyz_a[:, :2].max(axis=0), xyz_b[:, :2].max(axis=0))
    if np.any(hi <= lo):
        return Correspondences(a, b, np.empty(0), np.empty((0, 3)),
                               np.empty((0, 3)), 0)
    x_edges = np.arange(np.floor(lo[0] / cell) * cell, hi[0] + cell, cell)
    y_edges = np.arange(np.floor(lo[1] / cell) * cell, hi[1] + cell, cell)
    ncols = len(y_edges) - 1

    def cell_ids(xyz):
        inside = np.all((xyz[:, :2] >= lo) & (xyz[:, :2] <= hi), axis=1)
        idx = np.flatnonzero(inside)
        ix, iy = gridding.cell_indices(xyz[idx, 0], xyz[idx, 1],
                                       x_edges, y_edges)
        return idx, ix * ncols + iy

    idx_a, id_a = cell_ids(xyz_a)
    idx_b, id_b = cell_ids(xyz_b)
    order_a = np.argsort(id_a, kind="stable")
    order_b = np.argsort(id_b, kind="stable")
    ids_a, starts_a = np.unique(id_a[order_a], return_index=True)
    ids_b, starts_b = np.unique(id_b[order_b], return_index=True)
    common, pos_a, pos_b = np.intersect1d(ids_a, ids_b,
                                          return_indices=True)

    d_list, n_list, j_list = [], [], []
    for pa, pb in zip(pos_a, pos_b):
        sl_a = slice(starts_a[pa], starts_a[pa + 1]
                     if pa + 1 < len(starts_a) else len(order_a))
        sl_b = slice(starts_b[pb], starts_b[pb + 1]
                     if pb + 1 < len(starts_b) else len(order_b))
        pts_a = idx_a[order_a[sl_a]]
        pts_b = idx_b[order_b[sl_b]]
        if pts_a.size < min_points or pts_b.size < max(3, min_points // 2):
            continue

        cloud_a = xyz_a[pts_a]
        centroid_a = cloud_a.mean(axis=0)
        centered = cloud_a - centroid_a
        _, svals, vt = np.linalg.svd(centered, full_matrices=False)
        normal = vt[2]
        if normal[2] < 0:
            normal = -normal
        rms = svals[2] / np.sqrt(pts_a.size)
        if rms > max_rms or normal[2] < min_normal_z:
            continue

        centroid_b = xyz_b[pts_b].mean(axis=0)
        d = float(normal @ (centroid_b - centroid_a))
        if abs(d) > max_distance:
            continue

        ia = _nearest_to_centroid(xyz_a, pts_a)
        ib = _nearest_to_centroid(xyz_b, pts_b)
        m_a = bundle_a.r_nav[ia].T @ normal
        m_b = bundle_b.r_nav[ib].T @ normal
        j_beta = (np.cross(m_b, bundle_b.body_vecs[ib])
                  - np.cross(m_a, bundle_a.body_vecs[ia]))

        d_list.append(d)
        n_list.append(normal)
        j_list.append(j_beta)

    k = len(d_list)
    return Correspondences(
        a, b,
        np.array(d_list) if k else np.empty(0),
        np.array(n_list) if k else np.empty((0, 3)),
        np.array(j_list) if k else np.empty((0, 3)),
        int(common.size))
