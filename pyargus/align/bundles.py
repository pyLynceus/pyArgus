"""A strip with its trajectory attached: what the solver works on.

The alignment unknowns act through the direct-georeferencing model
(``core.georef``), so every point needs the navigation state it was
shot from: position and attitude in the SAME map frame as the points.
Building that from a real SBET (geographic, ellipsoidal heights) takes
a projection and a geoid and is deliberately not this module's job --
see HANDOFF.md. Synthetic harnesses and any caller that has done the
conversion hand the arrays straight in.
"""

from dataclasses import dataclass, field

import numpy as np

from pyargus.core import rotation


@dataclass
class StripBundle:
    """One strip: points plus per-point navigation state, map frame."""
    xyz: np.ndarray       # (N, 3) point coordinates as georeferenced
    nav_xyz: np.ndarray   # (N, 3) trajectory position at each return
    rpy: np.ndarray       # (N, 3) roll, pitch, yaw (radians)
    _r_nav: np.ndarray = field(default=None, repr=False)
    _body: np.ndarray = field(default=None, repr=False)

    def __post_init__(self):
        self.xyz = np.asarray(self.xyz, dtype=float)
        self.nav_xyz = np.asarray(self.nav_xyz, dtype=float)
        self.rpy = np.asarray(self.rpy, dtype=float)
        if not (self.xyz.shape == self.nav_xyz.shape == self.rpy.shape):
            raise ValueError("xyz, nav_xyz and rpy must share one (N, 3) shape")
        if self.xyz.ndim != 2 or self.xyz.shape[1] != 3:
            raise ValueError(f"expected (N, 3) arrays, got {self.xyz.shape}")

    @property
    def r_nav(self):
        """(N, 3, 3) body-to-map rotation per point (cached)."""
        if self._r_nav is None:
            self._r_nav = rotation.matrices(
                self.rpy[:, 0], self.rpy[:, 1], self.rpy[:, 2])
        return self._r_nav

    @property
    def body_vecs(self):
        """(N, 3) nominal scanner/body-frame ranging vectors (cached).

        b = R_nav^T (X - X_nav): the vector the corrections rotate.
        Fixed at construction -- corrections re-run the forward model on
        the original measurement, they do not re-derive it.
        """
        if self._body is None:
            self._body = np.einsum("nji,nj->ni", self.r_nav,
                                   self.xyz - self.nav_xyz)
        return self._body


def corrected_xyz(bundle, boresight, offset):
    """Apply a small boresight rotation and a strip offset to a bundle.

    X' = X + R_nav (boresight x b) + offset -- the first-order effect of
    perturbing R_bore by [boresight]x in X = X_nav + R_nav R_bore b.
    """
    delta = np.cross(np.asarray(boresight, dtype=float), bundle.body_vecs)
    return (bundle.xyz + np.einsum("nij,nj->ni", bundle.r_nav, delta)
            + np.asarray(offset, dtype=float))
