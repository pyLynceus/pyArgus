"""TIN surfaces, with breaklines the honest way.

The TIN is a scipy Delaunay triangulation with linear interpolation.
Breaklines are enforced SOFTLY: each 3D breakline is densified to a
vertex spacing finer than the triangulation's typical edge and its
vertices join the point set, so triangles hug the break instead of
spanning it. That is what most production "breakline" workflows
actually do at survey point densities. It is NOT a constrained
Delaunay -- a triangle edge is not guaranteed to lie exactly on the
break between densified vertices -- and this module says so rather
than pretending; a true CDT arrives if a delivery ever needs one.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Tin:
    points: np.ndarray            # (N, 3) everything triangulated
    n_breakline_points: int       # how many of them came from breaklines
    _interp: object = None

    def z_at(self, x, y):
        """Linear TIN interpolation; NaN outside the hull, never
        extrapolated."""
        from scipy.interpolate import LinearNDInterpolator

        if self._interp is None:
            self._interp = LinearNDInterpolator(self.points[:, :2],
                                                self.points[:, 2])
        return self._interp(np.asarray(x, dtype=float),
                            np.asarray(y, dtype=float))

    def grid(self, cell, x_edges=None, y_edges=None):
        """Sample the TIN onto a grid (for contours, export, dZ maps).

        Returns (grid, x_edges, y_edges); cells outside the hull NaN.
        """
        from pyargus.core import gridding

        if x_edges is None or y_edges is None:
            x_edges, y_edges = gridding.grid_edges(
                self.points[:, 0], self.points[:, 1], cell)
        cx = (x_edges[:-1] + x_edges[1:]) / 2.0
        cy = (y_edges[:-1] + y_edges[1:]) / 2.0
        gx, gy = np.meshgrid(cx, cy, indexing="ij")
        return self.z_at(gx, gy), x_edges, y_edges


def densify_polyline(vertices, spacing):
    """Resample a 3D polyline so no segment exceeds ``spacing``.

    Original vertices are kept exactly; z interpolates linearly along
    each segment. A breakline's z is trusted as surveyed -- it is not
    re-sampled from the cloud.
    """
    vertices = np.asarray(vertices, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError(f"breakline must be (N, 3), got {vertices.shape}")
    if vertices.shape[0] < 2:
        raise ValueError("breakline needs at least two vertices")
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    out = [vertices[0]]
    for a, b in zip(vertices[:-1], vertices[1:]):
        run = float(np.linalg.norm(b[:2] - a[:2]))
        pieces = max(1, int(np.ceil(run / spacing)))
        for k in range(1, pieces + 1):
            out.append(a + (b - a) * (k / pieces))
    return np.array(out)


def build_tin(ground_xyz, breaklines=(), spacing=None, cell_hint=1.0):
    """Triangulate ground points plus densified breakline vertices.

    ``breaklines`` is an iterable of (N, 3) polylines; ``spacing``
    defaults to the cell hint (densify at least as finely as the
    surface you will sample). Returns a Tin.
    """
    ground_xyz = np.asarray(ground_xyz, dtype=float)
    if ground_xyz.ndim != 2 or ground_xyz.shape[1] != 3:
        raise ValueError(f"ground_xyz must be (N, 3), got {ground_xyz.shape}")
    if ground_xyz.shape[0] < 3:
        raise ValueError("need at least 3 ground points to triangulate")
    if spacing is None:
        spacing = cell_hint
    extra = [densify_polyline(b, spacing) for b in breaklines]
    n_break = int(sum(e.shape[0] for e in extra))
    points = (np.vstack([ground_xyz] + extra) if extra else ground_xyz)
    return Tin(points=points, n_breakline_points=n_break)
