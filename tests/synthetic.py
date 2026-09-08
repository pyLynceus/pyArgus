"""Synthetic strips and trajectories with known answers.

Until the reference TrueView 660 dataset is chosen (Phase 0), these are
the only fixtures -- and even after it lands, every mathematical claim
still gets proven here first, where the truth is constructed rather
than measured.
"""

import numpy as np

from pyargus.formats.sbet import RECORD_DTYPE


def planar_strip(n, x_range, y_range, plane=(0.0, 0.0, 100.0), noise=0.0, seed=0):
    """Points on the plane z = a*x + b*y + c inside a rectangle.

    Returns a dict with x, y, z arrays, the same shape formats.las uses.
    """
    a, b, c = plane
    rng = np.random.default_rng(seed)
    x = rng.uniform(*x_range, n)
    y = rng.uniform(*y_range, n)
    z = a * x + b * y + c
    if noise:
        z = z + rng.normal(0.0, noise, n)
    return {"x": x, "y": y, "z": z}


def linear_sbet(n=100, t0=1000.0, dt=0.005, heading0=0.0, heading_rate=0.0):
    """An SBET record array with linear motion and attitude."""
    data = np.zeros(n, dtype=RECORD_DTYPE)
    t = t0 + np.arange(n) * dt
    data["time"] = t
    data["lat"] = 0.594 + 1e-9 * np.arange(n)
    data["lon"] = -1.472 + 1e-9 * np.arange(n)
    data["alt"] = 300.0 + 0.01 * np.arange(n)
    data["roll"] = 0.001 * np.arange(n)
    data["pitch"] = -0.0005 * np.arange(n)
    heading = heading0 + heading_rate * (t - t0)
    data["heading"] = np.mod(heading + np.pi, 2.0 * np.pi) - np.pi
    return data


def write_sbet(path, data):
    data.tofile(path)
    return path


def classification_scene(seed=0, slope_x=0.02):
    """Ground plane, three flat-roofed buildings, floating canopy.

    Returns (points dict, truth) where truth marks the ground points.
    Everything a ground filter needs to get right, with the answer
    constructed: terrain must survive, roofs and canopy must not.
    """
    rng = np.random.default_rng(seed)

    def ground_z(x, y):
        return 50.0 + slope_x * x

    gx = rng.uniform(0, 100, 20000)
    gy = rng.uniform(0, 100, 20000)
    gz = ground_z(gx, gy) + rng.normal(0, 0.03, gx.size)

    roofs = []
    for x0, y0, size, height in ((15, 15, 14, 8.0), (60, 20, 10, 5.0),
                                 (35, 65, 16, 12.0)):
        bx = rng.uniform(x0, x0 + size, 2500)
        by = rng.uniform(y0, y0 + size, 2500)
        bz = ground_z(bx, by) + height + rng.normal(0, 0.05, bx.size)
        roofs.append((bx, by, bz))

    cx = rng.uniform(0, 100, 4000)
    cy = rng.uniform(0, 100, 4000)
    cz = ground_z(cx, cy) + rng.uniform(3.0, 15.0, cx.size)

    x = np.concatenate([gx] + [r[0] for r in roofs] + [cx])
    y = np.concatenate([gy] + [r[1] for r in roofs] + [cy])
    z = np.concatenate([gz] + [r[2] for r in roofs] + [cz])
    truth = np.zeros(x.size, dtype=bool)
    truth[:gx.size] = True
    return {"x": x, "y": y, "z": z}, truth


def rolling_terrain(x, y):
    """Gentle relief: enough slope diversity to observe all three
    boresight angles, smooth enough that 5-unit patches stay planar."""
    return 100.0 + 3.0 * np.sin(x / 25.0) + 2.0 * np.cos(y / 20.0)


def misaligned_strip(yaw, origin, length, *, terrain=rolling_terrain,
                     agl=100.0, swath=60.0, n=6000,
                     true_boresight=(0.0, 0.0, 0.0),
                     true_offset=(0.0, 0.0, 0.0),
                     attitude_noise=0.01, noise=0.02, seed=0):
    """One flight line, georeferenced with the WRONG (identity) boresight.

    Reality's order of events, reproduced: the scanner truly measured
    the terrain, so the body-frame vector satisfies
    G = P + R_nav R_true b; processing that ranging vector with
    R_bore = I (and a trajectory offset error) yields the misaligned
    cloud X = P + R_nav b + offset. Returns (StripBundle, true_ground):
    the bundle is what the solver sees, true_ground what the cloud
    should become once corrected.
    """
    from pyargus.align import StripBundle
    from pyargus.core import rotation

    rng = np.random.default_rng(seed)
    direction = np.array([np.cos(yaw), np.sin(yaw), 0.0])
    perp = np.array([-direction[1], direction[0], 0.0])

    along = rng.uniform(0.0, length, n)
    across = rng.uniform(-swath / 2.0, swath / 2.0, n)
    origin3 = np.array([origin[0], origin[1], 0.0])
    ground = (origin3 + along[:, None] * direction + across[:, None] * perp)
    ground[:, 2] = terrain(ground[:, 0], ground[:, 1]) + rng.normal(0, noise, n)

    nav = origin3 + along[:, None] * direction
    nav[:, 2] = 100.0 + agl
    rpy = np.column_stack([
        rng.normal(0.0, attitude_noise, n),
        rng.normal(0.0, attitude_noise, n),
        yaw + rng.normal(0.0, attitude_noise, n)])

    r_nav = rotation.matrices(rpy[:, 0], rpy[:, 1], rpy[:, 2])
    r_true = rotation.matrix(*true_boresight)
    body = np.einsum("nji,nj->ni", r_nav, ground - nav)   # R_nav^T (G - P)
    body = body @ r_true                                   # R_true^T applied
    xyz = nav + np.einsum("nij,nj->ni", r_nav, body) + np.asarray(true_offset)
    return StripBundle(xyz=xyz, nav_xyz=nav, rpy=rpy), ground
