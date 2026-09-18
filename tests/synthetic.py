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
                     true_drift=None, t0=0.0, speed=25.0,
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
    # per-point time rides the along-track coordinate (a scanner sweeps
    # forward); true_drift(t) injects the GNSS-wander error the drift
    # solver must recover
    times = t0 + along / speed
    if true_drift is not None:
        xyz = xyz.copy()
        xyz[:, 2] += true_drift(times)
    return StripBundle(xyz=xyz, nav_xyz=nav, rpy=rpy, times=times), ground


def labeled_scene(seed=0, n_ground=20000):
    """A scene with the answer key attached: ground (2), low
    vegetation (3), high vegetation (5), buildings (6), each built to
    have the geometry its class implies -- roofs planar and
    single-return, canopy scattered and multi-return.

    Returns (points dict incl. return fields, labels array).
    """
    rng = np.random.default_rng(seed)

    def ground_z(x, y):
        return 50.0 + 0.02 * x

    parts = []

    gx = rng.uniform(0, 100, n_ground)
    gy = rng.uniform(0, 100, n_ground)
    parts.append((gx, gy, ground_z(gx, gy) + rng.normal(0, 0.03, gx.size),
                  np.ones(gx.size), np.ones(gx.size), 2))

    for x0, y0, size, height in ((10, 10, 15, 12.0), (70, 15, 12, 10.0),
                                 (15, 70, 14, 15.0)):
        bx = rng.uniform(x0, x0 + size, 3000)
        by = rng.uniform(y0, y0 + size, 3000)
        bz = ground_z(bx, by) + height + rng.normal(0, 0.04, bx.size)
        parts.append((bx, by, bz, np.ones(bx.size), np.ones(bx.size), 6))

    for cx0, cy0 in ((45, 45), (80, 70), (40, 85)):
        cx = cx0 + rng.normal(0, 6.0, 4000)
        cy = cy0 + rng.normal(0, 6.0, 4000)
        cz = ground_z(cx, cy) + rng.uniform(9.0, 28.0, cx.size)
        rn = rng.integers(1, 3, cx.size).astype(float)
        parts.append((cx, cy, cz, rn, np.full(cx.size, 2.0), 5))

    # low vegetation on BOTH halves: a spatial holdout must see every
    # class on each side (the first cut of this scene put all of class
    # 3 east of the split and the forest scored 0 on it -- unseen is
    # unlearnable, not misclassified)
    for x0, x1, y0, y1 in ((30, 48, 8, 30), (55, 95, 35, 60)):
        lx = rng.uniform(x0, x1, 1800)
        ly = rng.uniform(y0, y1, 1800)
        lz = ground_z(lx, ly) + rng.uniform(0.4, 2.5, lx.size)
        rn = rng.integers(1, 3, lx.size).astype(float)
        parts.append((lx, ly, lz, rn, np.full(lx.size, 2.0), 3))

    x = np.concatenate([p[0] for p in parts])
    y = np.concatenate([p[1] for p in parts])
    z = np.concatenate([p[2] for p in parts])
    return_number = np.concatenate([p[3] for p in parts]).astype(np.uint8)
    number_of_returns = np.concatenate([p[4] for p in parts]).astype(np.uint8)
    labels = np.concatenate([np.full(p[0].size, p[5], dtype=np.uint8)
                             for p in parts])
    points = {"x": x, "y": y, "z": z, "return_number": return_number,
              "number_of_returns": number_of_returns}
    return points, labels


def lagged_strip(yaw, origin, length, *, lag=0.0, terrain=rolling_terrain,
                 agl=100.0, swath=60.0, n=6000, t0=0.0, speed=25.0,
                 roll_amp=0.02, roll_period=8.0, noise=0.02, seed=0):
    """One flight line georeferenced with a NAVIGATION TIME LAG.

    The error this builds is deliberately OUTSIDE the solver's span, to
    test what it does with a misalignment it cannot represent.

    Reality's order of events: the scanner truly measured the terrain
    from the navigation state at time t, so the ranging vector satisfies
    G = P(t) + R(t) b. Processing pairs that same b with the state at
    t + lag, and the delivered cloud becomes X = P(t+lag) + R(t+lag) b.
    There is no boresight in that and no constant offset either.

    The aircraft rolls, as a real one always does, so the attitude part
    of the lag error varies along the line and the whole thing is not a
    rigid shift. Were attitude constant, a steady-speed lag WOULD
    collapse to a horizontal offset -- which the solver can represent,
    and which would make this a much weaker test.

    Returns (StripBundle, true_ground). The bundle carries the nav
    state that processing BELIEVED -- the lagged one -- because that is
    what a misprocessed delivery hands the solver. ``true_ground`` is
    where the points actually belong, and is the only referee here that
    does not come out of the solver's own model. With ``lag=0`` the
    cloud lands exactly on it.
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

    times = t0 + along / speed

    def nav_at(t):
        """Position and attitude of the aircraft at time t."""
        travelled = (t - t0) * speed
        pos = origin3 + travelled[:, None] * direction
        pos[:, 2] = 100.0 + agl
        phase = 2.0 * np.pi * t / roll_period
        return pos, np.column_stack([
            roll_amp * np.sin(phase),
            0.5 * roll_amp * np.cos(phase),
            np.full(t.shape, yaw)])

    pos_true, rpy_true = nav_at(times)
    r_true = rotation.matrices(rpy_true[:, 0], rpy_true[:, 1], rpy_true[:, 2])
    body = np.einsum("nji,nj->ni", r_true, ground - pos_true)

    pos_used, rpy_used = nav_at(times + lag)
    r_used = rotation.matrices(rpy_used[:, 0], rpy_used[:, 1], rpy_used[:, 2])
    xyz = pos_used + np.einsum("nij,nj->ni", r_used, body)

    return (StripBundle(xyz=xyz, nav_xyz=pos_used, rpy=rpy_used, times=times),
            ground)
