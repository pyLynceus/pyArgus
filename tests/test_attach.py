import numpy as np
import pytest

pytest.importorskip("pyproj")

from pyargus.align import attach
from pyargus.core import rotation
from pyargus.formats import crs
from pyargus.formats.sbet import RECORD_DTYPE

WEEK = 2385
GEOID = -29.077
FT = 1200.0 / 3937.0


def test_ned_mapping_rederived_from_frame_definitions():
    """roll, -pitch, pi/2 - heading: re-derive it, don't trust it."""
    def r_ned(r, p, h):
        cr, sr = np.cos(r), np.sin(r)
        cp, sp = np.cos(p), np.sin(p)
        ch, sh = np.cos(h), np.sin(h)
        rz = np.array([[ch, -sh, 0], [sh, ch, 0], [0, 0, 1]])
        ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
        rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
        return rz @ ry @ rx

    ned_to_enu = np.array([[0.0, 1, 0], [1, 0, 0], [0, 0, -1]])
    body_swap = np.diag([1.0, -1, -1])  # (fwd,right,down) -> (fwd,left,up)
    rng = np.random.default_rng(2)
    for _ in range(20):
        r, p = rng.uniform(-0.4, 0.4, 2)
        h = rng.uniform(0, 2 * np.pi)
        ours = ned_to_enu @ r_ned(r, p, h) @ body_swap.T
        rr, pp, yy = rotation.angles(ours)
        assert np.isclose(rr, r, atol=1e-12)
        assert np.isclose(pp, -p, atol=1e-12)
        expected_yaw = np.mod(np.pi / 2 - h + np.pi, 2 * np.pi) - np.pi
        assert np.isclose(yy, expected_yaw, atol=1e-12)


def eastbound_scene(heading_offset=0.0, wander=0.4, n_records=601):
    """A straight eastbound line over flat ground, in EPSG:6447 ftUS."""
    import pyproj
    t = 400_000.0 + np.arange(n_records) * 0.1
    e = 1_943_000.0 + (t - t[0]) * 25.0          # 25 ft/s east
    n = np.full(n_records, 1_628_800.0)
    z = np.full(n_records, 950.0)                # ground 650, AGL 300

    inverse = pyproj.Transformer.from_crs("EPSG:6447", "EPSG:6318",
                                          always_xy=True)
    lon, lat = inverse.transform(e, n)
    data = np.zeros(n_records, dtype=RECORD_DTYPE)
    data["time"] = t
    data["lat"] = np.deg2rad(lat)
    data["lon"] = np.deg2rad(lon)
    data["alt"] = z * FT + GEOID
    data["heading"] = np.pi / 2 + heading_offset  # east
    data["wander"] = wander
    return data, e, n, z


def scene_points(sbet, e, n, z, n_points=4000, seed=3):
    rng = np.random.default_rng(seed)
    t = sbet["time"]
    tq = rng.uniform(t[0], t[-1], n_points)
    nav_e = np.interp(tq, t, e)
    nav_n = np.interp(tq, t, n)
    nav_z = np.interp(tq, t, z)
    across = rng.uniform(-100.0, 100.0, n_points)
    # yaw_ours = pi/2 - heading = 0 -> R_nav = I -> X = nav + body
    points = {
        "x": nav_e,
        "y": nav_n + across,
        "z": nav_z - 300.0,
        "gps_time": tq + WEEK * 604800.0 - 1_000_000_000.0,
        "point_source_id": np.where(np.arange(n_points) < n_points // 2,
                                    1, 2).astype(np.uint16),
    }
    return points, across


def test_attach_round_trips_through_real_transforms():
    sbet, e, n, z = eastbound_scene()
    points, across = scene_points(sbet, e, n, z)
    me, mn, mz = crs.sbet_to_map(sbet, "EPSG:6447", vertical=GEOID)
    result = attach.bundles_from_cloud(points, sbet, me, mn, mz)

    assert result.gps_week == WEEK
    assert result.strip_ids == [1, 2]
    assert result.heading_source == "heading"
    assert result.track_errors["heading"] < 0.02
    assert result.track_errors["heading+wander"] > 0.3
    assert abs(result.agl_median - 300.0) < 1.0
    assert result.nadir_median_deg < 25.0

    b0 = result.bundles[0]
    assert np.abs(b0.rpy).max() < 1e-6              # level, yaw_ours = 0
    # navigation recovered through the geographic round trip
    assert np.abs(b0.nav_xyz[:, 2] - 950.0).max() < 0.05
    # body vectors are the constructed scanner fan
    assert np.abs(b0.body_vecs[:, 0]).max() < 0.05
    assert np.abs(b0.body_vecs[:, 2] + 300.0).max() < 0.05
    assert np.abs(b0.body_vecs[:, 1] - across[:2000]).max() < 0.05


def test_missing_geoid_is_caught_by_the_agl_check():
    sbet, e, n, z = eastbound_scene()
    points, _ = scene_points(sbet, e, n, z)
    me, mn, _ = crs.sbet_to_map(sbet, "EPSG:6447", vertical=GEOID)
    with pytest.raises(ValueError, match="below the ground"):
        attach.bundles_from_cloud(points, sbet, me, mn, sbet["alt"])


def test_convention_error_heading_refuses():
    sbet, e, n, z = eastbound_scene(heading_offset=1.2, wander=1.2)
    points, _ = scene_points(sbet, e, n, z)
    me, mn, mz = crs.sbet_to_map(sbet, "EPSG:6447", vertical=GEOID)
    with pytest.raises(ValueError, match="convention"):
        attach.bundles_from_cloud(points, sbet, me, mn, mz)


def test_wrong_trajectory_refuses():
    sbet, e, n, z = eastbound_scene()
    points, _ = scene_points(sbet, e, n, z)
    points = dict(points)
    points["gps_time"] = points["gps_time"] + 5_000.0  # outside the window
    me, mn, mz = crs.sbet_to_map(sbet, "EPSG:6447", vertical=GEOID)
    with pytest.raises(ValueError, match="inside the trajectory"):
        attach.bundles_from_cloud(points, sbet, me, mn, mz)


def banked_southbound_scene(n_records=601):
    """Nonzero roll/pitch, southbound heading: pins every sign in the
    rpy construction and both einsum orders -- the review panel proved
    the eastbound-level scene lets all of them mutate freely."""
    import pyproj
    from pyargus.formats import crs as crs_mod

    ROLL, PITCH, HEADING = 0.05, -0.04, np.pi  # banked, nose down, south
    t = 400_000.0 + np.arange(n_records) * 0.1
    e = np.full(n_records, 1_943_500.0)
    n = 1_629_500.0 - (t - t[0]) * 25.0
    z = np.full(n_records, 950.0)
    inverse = pyproj.Transformer.from_crs("EPSG:6447", "EPSG:6318",
                                          always_xy=True)
    lon, lat = inverse.transform(e, n)
    data = np.zeros(n_records, dtype=RECORD_DTYPE)
    data["time"] = t
    data["lat"] = np.deg2rad(lat)
    data["lon"] = np.deg2rad(lon)
    data["alt"] = z * FT + GEOID
    data["roll"] = ROLL
    data["pitch"] = PITCH
    data["heading"] = HEADING
    data["wander"] = 0.4
    return data, e, n, z, (ROLL, PITCH, HEADING)


def banked_points(sbet, e, n, z, attitude, n_points=3000, seed=8):
    rng = np.random.default_rng(seed)
    roll, pitch, heading = attitude
    r_nav = rotation.matrix(roll, -pitch, np.pi / 2 - heading)
    t = sbet["time"]
    tq = rng.uniform(t[0], t[-1], n_points)
    nav = np.column_stack([np.interp(tq, t, e), np.interp(tq, t, n),
                           np.interp(tq, t, z)])
    body = np.column_stack([rng.uniform(-5, 5, n_points),
                            rng.uniform(-120, 120, n_points),
                            np.full(n_points, -300.0)])
    xyz = nav + body @ r_nav.T
    points = {
        "x": xyz[:, 0], "y": xyz[:, 1], "z": xyz[:, 2],
        "gps_time": tq + WEEK * 604800.0 - 1_000_000_000.0,
        "point_source_id": np.where(np.arange(n_points) % 2 == 0,
                                    1, 2).astype(np.uint16),
    }
    return points, body


def test_banked_scene_pins_the_attitude_signs():
    sbet, e, n, z, attitude = banked_southbound_scene()
    points, body = banked_points(sbet, e, n, z, attitude)
    me, mn, mz = crs.sbet_to_map(sbet, "EPSG:6447", vertical=GEOID)
    result = attach.bundles_from_cloud(points, sbet, me, mn, mz)
    roll, pitch, heading = attitude
    b0 = result.bundles[0]
    assert np.allclose(b0.rpy[:, 0], roll, atol=1e-9)
    assert np.allclose(b0.rpy[:, 1], -pitch, atol=1e-9)
    yaw_gap = np.mod(b0.rpy[:, 2] - (np.pi / 2 - heading) + np.pi,
                     2 * np.pi) - np.pi
    assert np.abs(yaw_gap).max() < 1e-9
    # body vectors reproduce the constructed scanner fan: any sign or
    # transpose mutation in the rpy mapping or einsums breaks this
    even = points["point_source_id"] == 1
    assert np.abs(b0.body_vecs - body[even]).max() < 0.05


def test_apply_corrections_matches_corrected_xyz_on_banked_flight():
    from pyargus.align.bundles import corrected_xyz

    sbet, e, n, z, attitude = banked_southbound_scene()
    points, _ = banked_points(sbet, e, n, z, attitude)
    me, mn, mz = crs.sbet_to_map(sbet, "EPSG:6447", vertical=GEOID)
    result = attach.bundles_from_cloud(points, sbet, me, mn, mz)

    boresight = np.array([0.001, -0.002, 0.003])
    offsets = {1: np.array([0.0, 0.0, 0.0]),
               2: np.array([0.02, -0.01, 0.05])}
    applied, skipped = attach.apply_corrections(
        points, sbet, me, mn, mz, result.heading_source, boresight, offsets)
    assert skipped == 0
    for sid, bundle in zip(result.strip_ids, result.bundles):
        expected = corrected_xyz(bundle, boresight, offsets[sid])
        got = applied[points["point_source_id"] == sid]
        assert np.abs(got - expected).max() < 1e-9
    # and the correction genuinely moved the cloud (not a zero test)
    assert np.abs(applied[:, 2] - points["z"]).max() > 0.05
