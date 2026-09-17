"""Tiled SMRF: the same answer as the whole cloud, in bounded memory.

The contract is EQUALITY. A tiled run that merely looks reasonable is
worthless -- the whole point is classifying a block nobody can hold,
and nobody can check that by eye. So the tests build a scene hard
enough to have real seams (a building deliberately straddling one) and
demand the tiled ground mask match the whole-cloud mask exactly.
"""

import numpy as np
import pytest

from pyargus.classify import ground as ground_mod
from pyargus.classify import tiles as tiles_mod
from pyargus.core import gridding

CELL, SLOPE, WINDOW = 3.0, 0.15, 30.0
THRESHOLD, SCALAR = 1.5, 1.25
SPAN = 900.0


def scene(seed=0, n=200_000):
    """Rolling terrain, canopy, and buildings -- one of them sitting on
    the x = 450 seam, which is where tiling goes wrong if it is going
    to."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, SPAN, n)
    y = rng.uniform(0.0, SPAN, n)
    z = (100.0 + 0.02 * x + 8.0 * np.sin(x / 90.0)
         + 5.0 * np.cos(y / 70.0) + rng.normal(0.0, 0.05, n))
    for cx, cy, w, h in ((200, 250, 60, 22), (450, 400, 90, 26),
                         (600, 640, 80, 30)):
        inside = (np.abs(x - cx) < w / 2) & (np.abs(y - cy) < w / 2)
        z[inside] += h
    canopy = (x > 700) & (y < 300) & (rng.random(n) < 0.6)
    z[canopy] += rng.uniform(3.0, 28.0, int(canopy.sum()))
    return x, y, z


def reader_for(x, y, z):
    def read(bounds):
        (x0, y0), (x1, y1) = bounds
        m = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
        return x[m], y[m], z[m]
    return read


def test_required_halo_is_the_cascades_own_reach():
    """One opening of radius r reaches 2r cells and the rounds compose,
    so the cascade r = 1..R reaches R(R+1) cells."""
    assert tiles_mod.required_halo(3.0, 30.0) == 10 * 11 * 3.0
    assert tiles_mod.required_halo(3.0, 60.0) == 20 * 21 * 3.0
    assert tiles_mod.required_halo(1.0, 18.0) == 18 * 19 * 1.0
    with pytest.raises(ValueError, match="cell must be positive"):
        tiles_mod.required_halo(0.0, 18.0)
    with pytest.raises(ValueError, match="at least one cell"):
        tiles_mod.required_halo(3.0, 1.0)


def test_tiles_cover_the_grid_exactly_once():
    x_edges, y_edges = tiles_mod.global_edges((0.0, 0.0), (SPAN, SPAN),
                                              CELL)
    tiles = tiles_mod.plan_tiles(x_edges, y_edges, CELL, 60.0, 300.0)
    covered = np.zeros((x_edges.size - 1, y_edges.size - 1), dtype=int)
    for tile in tiles:
        cx0 = int(round((tile.core[0][0] - x_edges[0]) / CELL))
        cy0 = int(round((tile.core[0][1] - y_edges[0]) / CELL))
        cx1 = int(round((tile.core[1][0] - x_edges[0]) / CELL))
        cy1 = int(round((tile.core[1][1] - y_edges[0]) / CELL))
        covered[cx0:cx1, cy0:cy1] += 1
        # the halo contains the core, and never leaves the grid
        assert tile.halo[0][0] <= tile.core[0][0]
        assert tile.halo[1][1] >= tile.core[1][1]
        assert tile.halo[0][0] >= x_edges[0]
        assert tile.halo[1][0] <= x_edges[-1]
    assert (covered == 1).all(), "cores must tile the grid exactly once"


def test_tiled_surface_equals_the_whole_cloud_surface():
    """The contract, on a scene with a building across the seam."""
    x, y, z = scene()
    whole = ground_mod.smrf(x, y, z, cell=CELL, slope=SLOPE,
                            window=WINDOW, threshold=THRESHOLD,
                            scalar=SCALAR)
    surface = tiles_mod.tiled_surface(
        reader_for(x, y, z), (x.min(), y.min()), (x.max(), y.max()),
        cell=CELL, slope=SLOPE, window=WINDOW, tile_size=300.0,
        halo=60.0)
    sx = min(surface.dem.shape[0], whole.dem.shape[0])
    sy = min(surface.dem.shape[1], whole.dem.shape[1])
    assert np.allclose(surface.dem[:sx, :sy], whole.dem[:sx, :sy])
    tiled = ground_mod.classify_against(surface, x, y, z,
                                        threshold=THRESHOLD, scalar=SCALAR)
    assert np.array_equal(tiled, whole.ground)


def test_without_a_halo_the_seams_are_wrong():
    """The halo is load-bearing, not decoration: prove the failure it
    prevents, or nothing pins its existence."""
    x, y, z = scene()
    whole = ground_mod.smrf(x, y, z, cell=CELL, slope=SLOPE,
                            window=WINDOW, threshold=THRESHOLD,
                            scalar=SCALAR)
    # the public call REFUSES a halo this small, so assemble the
    # no-halo surface by hand to show what the guard is guarding
    read = reader_for(x, y, z)
    x_edges, y_edges = tiles_mod.global_edges((x.min(), y.min()),
                                              (x.max(), y.max()), CELL)
    dem = np.full((x_edges.size - 1, y_edges.size - 1), np.nan)
    for tile in tiles_mod.plan_tiles(x_edges, y_edges, CELL, 0.0, 300.0):
        tx, ty, tz = read(tile.core)
        if tx.size == 0:
            continue
        c0 = int(round((tile.core[0][0] - x_edges[0]) / CELL))
        r0 = int(round((tile.core[0][1] - y_edges[0]) / CELL))
        c1 = int(round((tile.core[1][0] - x_edges[0]) / CELL))
        r1 = int(round((tile.core[1][1] - y_edges[0]) / CELL))
        local = ground_mod.ground_surface(
            tx, ty, tz, x_edges[c0:c1 + 1], y_edges[r0:r1 + 1],
            cell=CELL, slope=SLOPE, window=WINDOW)
        dem[c0:c1, r0:r1] = local.dem
    sx = min(dem.shape[0], whole.dem.shape[0])
    sy = min(dem.shape[1], whole.dem.shape[1])
    worst = np.nanmax(np.abs(dem[:sx, :sy] - whole.dem[:sx, :sy]))
    assert worst > 5.0, f"expected a seam error, got {worst}"

    with pytest.raises(ValueError, match="cannot be right"):
        tiles_mod.tiled_surface(
            read, (x.min(), y.min()), (x.max(), y.max()), cell=CELL,
            slope=SLOPE, window=WINDOW, tile_size=300.0, halo=0.0)


def test_a_halo_under_two_windows_refuses():
    x, y, z = scene(n=20_000)
    with pytest.raises(ValueError, match="cannot be right"):
        tiles_mod.tiled_surface(
            reader_for(x, y, z), (x.min(), y.min()), (x.max(), y.max()),
            cell=CELL, slope=SLOPE, window=WINDOW, tile_size=300.0,
            halo=2.0 * WINDOW - 1.0)


def test_one_tile_reproduces_the_plain_call():
    """A tile_size larger than the project is just SMRF."""
    x, y, z = scene(seed=2, n=60_000)
    whole = ground_mod.smrf(x, y, z, cell=CELL, slope=SLOPE,
                            window=WINDOW, threshold=THRESHOLD,
                            scalar=SCALAR)
    surface = tiles_mod.tiled_surface(
        reader_for(x, y, z), (x.min(), y.min()), (x.max(), y.max()),
        cell=CELL, slope=SLOPE, window=WINDOW, tile_size=10_000.0,
        halo=60.0)
    tiled = ground_mod.classify_against(surface, x, y, z,
                                        threshold=THRESHOLD, scalar=SCALAR)
    assert np.array_equal(tiled, whole.ground)


def test_an_empty_tile_does_not_abort_the_run():
    """Real projects have empty corners; one must not end the job."""
    rng = np.random.default_rng(5)
    n = 40_000
    x = rng.uniform(0.0, 300.0, n)          # data only in one corner
    y = rng.uniform(0.0, 300.0, n)
    z = 100.0 + 0.01 * x + rng.normal(0.0, 0.05, n)
    surface = tiles_mod.tiled_surface(
        reader_for(x, y, z), (0.0, 0.0), (900.0, 900.0),
        cell=CELL, slope=SLOPE, window=WINDOW, tile_size=300.0,
        halo=60.0)
    assert np.isfinite(surface.dem).all()   # inpainted, not NaN
    assert surface.dem.shape[0] >= 300 // int(CELL)


def test_no_points_anywhere_refuses():
    empty = (np.empty(0), np.empty(0), np.empty(0))
    with pytest.raises(ValueError, match="no tile held any points"):
        tiles_mod.tiled_surface(lambda bounds: empty, (0.0, 0.0),
                                (300.0, 300.0), cell=CELL, slope=SLOPE,
                                window=WINDOW, tile_size=150.0, halo=60.0)


LONG, WIDE = 2400.0, 600.0     # a corridor, never a square: see below


def corridor(seed=11, n=150_000):
    """A rectangular, MULTI-RETURN scene -- the shape of every real
    delivery here (Summerville 1,841 x 1,687; an SH 151 strip 10,572 x
    1,125). Square scenes let a swapped x/y lattice pass unnoticed, and
    single-return scenes hid a labeling policy that differed between
    the two commands for every non-last return.

    Returns (x, y, z, return_number, number_of_returns, lift) where
    ``lift`` is each first return's height above its last return (NaN
    for last returns)."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, LONG, n)
    y = rng.uniform(0.0, WIDE, n)
    z = (100.0 + 0.02 * x + 8.0 * np.sin(x / 90.0)
         + 5.0 * np.cos(y / 70.0) + rng.normal(0.0, 0.05, n))
    # buildings across the x = 900 and x = 1500 seams, and one on the
    # y = 300 seam
    for cx, cy, w, h in ((900, 150, 70, 24), (1500, 300, 90, 28),
                         (2100, 450, 60, 22)):
        inside = (np.abs(x - cx) < w / 2) & (np.abs(y - cy) < w / 2)
        z[inside] += h
    canopy = (x > 1700) & (x < 2000) & (y < 250) & (rng.random(n) < 0.6)
    z[canopy] += rng.uniform(3.0, 28.0, int(canopy.sum()))
    # a first return above a third of the pulses: half of them grass
    # and brush just above the ground -- inside the threshold, which is
    # exactly where a policy that lets non-last returns be ground
    # disagrees with one that does not -- and half up in the canopy
    pulse = rng.random(n) < 0.33
    k = int(pulse.sum())
    lift = np.where(rng.random(k) < 0.5, rng.uniform(0.1, 1.2, k),
                    rng.uniform(5.0, 30.0, k))
    fx = x[pulse] + rng.normal(0.0, 0.05, k)
    fy = y[pulse] + rng.normal(0.0, 0.05, k)
    fx = np.clip(fx, 0.0, LONG)
    fy = np.clip(fy, 0.0, WIDE)
    rn = np.ones(n, dtype=np.uint8)
    nr = np.ones(n, dtype=np.uint8)
    rn[pulse], nr[pulse] = 2, 2
    return (np.concatenate([x, fx]), np.concatenate([y, fy]),
            np.concatenate([z, z[pulse] + lift]),
            np.concatenate([rn, np.ones(k, dtype=np.uint8)]),
            np.concatenate([nr, np.full(k, 2, dtype=np.uint8)]),
            np.concatenate([np.full(n, np.nan), lift]))


def write_las(path, x, y, z, rn=None, nr=None):
    laspy = pytest.importorskip("laspy")
    header = laspy.LasHeader(version="1.4", point_format=6)
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([0.0, 0.0, 0.0])
    data = laspy.LasData(header)
    data.x, data.y, data.z = x, y, z
    ones = np.ones(x.size, dtype=np.uint8)
    data.return_number = ones if rn is None else rn
    data.number_of_returns = ones if nr is None else nr
    data.write(str(path))
    return path


def ground_of(path):
    laspy = pytest.importorskip("laspy")
    return np.asarray(laspy.read(str(path)).classification) == 2


def cli_args(src):
    return ["classify-ground", str(src), "--cell", str(CELL),
            "--slope", str(SLOPE), "--window", str(WINDOW),
            "--threshold", str(THRESHOLD), "--scalar", str(SCALAR)]


def test_cli_tiled_matches_the_whole_cloud_command(tmp_path):
    """End to end through `pyargus classify-ground --tiled`, against
    the same command without it -- on a multi-return corridor, at the
    DEFAULT halo, with tiles whose boxes stop well short of the project
    so every seam is real."""
    from pyargus import cli

    x, y, z, rn, nr, lift = corridor()
    # the scene must exercise the policy, or this test proves nothing
    # about it: plenty of first returns sit inside the threshold
    assert np.count_nonzero(lift < THRESHOLD) > 10_000
    src = write_las(tmp_path / "cloud.las", x, y, z, rn, nr)

    plain, tiled = tmp_path / "plain.las", tmp_path / "tiled.las"
    assert cli.main(cli_args(src) + ["--out", str(plain)]) == 0
    assert cli.main(cli_args(src) + ["--out", str(tiled), "--tiled",
                                     "--tile-size", "300"]) == 0
    a, b = ground_of(plain), ground_of(tiled)
    assert a.sum() > 0
    assert np.array_equal(a, b), int((a != b).sum())
    # and neither lets a non-last return be ground
    assert not a[rn != nr].any()


def test_any_return_is_honoured_by_both_commands(tmp_path):
    from pyargus import cli

    x, y, z, rn, nr, _ = corridor(seed=12, n=80_000)
    src = write_las(tmp_path / "cloud.las", x, y, z, rn, nr)
    runs = {}
    for name, extra in (("last", []), ("any", ["--any-return"]),
                        ("any_tiled", ["--any-return", "--tiled",
                                       "--tile-size", "300"])):
        out = tmp_path / f"{name}.las"
        assert cli.main(cli_args(src) + ["--out", str(out)] + extra) == 0
        runs[name] = ground_of(out)
    assert (runs["any"] != runs["last"]).sum() > 1_000
    assert runs["any"][rn != nr].any()
    assert np.array_equal(runs["any"], runs["any_tiled"])


def test_tile_options_without_tiled_refuse(tmp_path):
    from pyargus import cli

    x, y, z = scene(n=2_000)
    src = write_las(tmp_path / "cloud.las", x, y, z)
    for extra in (["--halo", "90"], ["--tile-size", "300"]):
        with pytest.raises(SystemExit, match="only with --tiled"):
            cli.main(cli_args(src) + ["--out", str(tmp_path / "o.las")]
                     + extra)


def _shrink_header_max(path, by):
    """Make the header lie the way a crop that forgot to update it does:
    MaxX and MaxY (LAS 1.4 public header, bytes 179 and 195) pulled in
    while the points stay where they are."""
    import struct

    raw = bytearray(path.read_bytes())
    for offset in (179, 195):
        value, = struct.unpack_from("<d", raw, offset)
        struct.pack_into("<d", raw, offset, value - by)
    path.write_bytes(bytes(raw))


def test_a_stale_header_refuses_and_rescan_recovers(tmp_path):
    """The tiled grid comes from the header; if the header is short of
    the points, the points past it were classified against the edge of
    a surface that never saw them, silently. Both commands now refuse,
    and --rescan takes the extent from the points instead."""
    from pyargus import cli

    x, y, z, rn, nr, _ = corridor(seed=13, n=60_000)
    src = write_las(tmp_path / "cloud.las", x, y, z, rn, nr)
    _shrink_header_max(src, 50.0)
    for extra in ([], ["--tiled", "--tile-size", "300"]):
        with pytest.raises(SystemExit, match="--rescan"):
            cli.main(cli_args(src) + ["--out", str(tmp_path / "x.las")]
                     + extra)
    assert not (tmp_path / "x.las").exists()
    assert not (tmp_path / "x.las.partial").exists()

    plain, tiled = tmp_path / "plain.las", tmp_path / "tiled.las"
    assert cli.main(cli_args(src) + ["--out", str(plain), "--rescan"]) == 0
    assert cli.main(cli_args(src) + ["--out", str(tiled), "--rescan",
                                     "--tiled", "--tile-size", "300"]) == 0
    assert np.array_equal(ground_of(plain), ground_of(tiled))


def test_global_edges_follow_their_own_axes():
    """x from the x range, y from the y range: a transposed lattice
    survived every square test scene."""
    x_edges, y_edges = tiles_mod.global_edges((0.0, 0.0), (LONG, WIDE),
                                              CELL)
    assert x_edges.size - 1 == int(LONG / CELL)
    assert y_edges.size - 1 == int(WIDE / CELL)


def test_resolve_plan_fills_the_defaults_and_refuses_a_thin_halo():
    halo, tile = tiles_mod.resolve_plan(CELL, WINDOW)
    assert halo == tiles_mod.required_halo(CELL, WINDOW)
    assert tile == max(6.0 * halo, 50.0 * CELL)
    assert tiles_mod.resolve_plan(CELL, WINDOW, 90.0, 300.0) == (90.0, 300.0)
    with pytest.raises(ValueError, match="cannot be right"):
        tiles_mod.resolve_plan(CELL, WINDOW, 2.0 * WINDOW - 1.0)


def test_tiled_surface_runs_at_the_default_halo():
    """Every other equality test names its halo, so a default quietly
    changed to something thin would pass them all. Pin what was USED."""
    x, y, z, *_ = corridor(seed=14, n=40_000)
    held = {}
    tiles_mod.tiled_surface(reader_for(x, y, z), (0.0, 0.0), (LONG, WIDE),
                            cell=CELL, slope=SLOPE, window=WINDOW,
                            tile_size=300.0, stats=held)
    assert held["halo"] == tiles_mod.required_halo(CELL, WINDOW)
    assert held["tiles"] > 1


def test_window_points_are_half_open_on_interior_edges():
    """A point exactly on an interior window edge belongs to the NEXT
    cell. Survey coordinates are quantized, so they land on 3-ft lines
    all the time; the first version read the edge inclusively and gave
    the tile a minimum the whole-cloud grid does not have there."""
    rng = np.random.default_rng(3)
    n = 60_000
    x = rng.integers(0, int(LONG / CELL) + 1, n) * CELL   # on grid lines
    y = rng.integers(0, int(WIDE / CELL) + 1, n) * CELL
    z = rng.uniform(0.0, 50.0, n)
    x_edges, y_edges = tiles_mod.global_edges((0.0, 0.0), (LONG, WIDE),
                                              CELL)
    whole = gridding.min_grid(x, y, z, x_edges, y_edges)
    nx, ny = x_edges.size - 1, y_edges.size - 1
    for hx0, hy0, hx1, hy1 in ((100, 50, 220, 130),     # interior
                               (0, 0, 60, 40),          # a corner
                               (700, 150, nx, ny)):     # the far edges
        wx, wy, wz = tiles_mod.window_points(reader_for(x, y, z),
                                             x_edges, y_edges,
                                             hx0, hy0, hx1, hy1)
        local = gridding.min_grid(wx, wy, wz, x_edges[hx0:hx1 + 1],
                                  y_edges[hy0:hy1 + 1])
        np.testing.assert_array_equal(local, whole[hx0:hx1, hy0:hy1])


def test_the_job_says_what_it_costs(tmp_path):
    """Passes are one per tile plus the write (plus a rescan); the most
    points one tile held is measured, not assumed; a one-tile plan says
    it saved nothing."""
    from pyargus.classify import job as ground_job

    x, y, z, rn, nr, _ = corridor(seed=15, n=40_000)
    src = write_las(tmp_path / "cloud.las", x, y, z, rn, nr)
    said = []
    params = dict(cell=CELL, slope=SLOPE, window=WINDOW,
                  threshold=THRESHOLD, scalar=SCALAR)
    stats = ground_job.classify_ground_tiled(
        src, tmp_path / "t.las", tile_size=300.0, log=said.append, **params)
    assert stats["passes"] == stats["tiles"] + 1
    assert any(f"{stats['passes']} passes" in line for line in said)
    assert stats["seamed"] == stats["tiles"] > 1
    assert 0 < stats["max_tile_points"] < np.count_nonzero(rn == nr)
    assert stats["area_read"] > 1.0

    again = ground_job.classify_ground_tiled(
        src, tmp_path / "r.las", tile_size=300.0, rescan=True,
        log=said.append, **params)
    assert again["passes"] == again["tiles"] + 2

    said.clear()
    one = ground_job.classify_ground_tiled(
        src, tmp_path / "o.las", tile_size=100_000.0, log=said.append,
        **params)
    assert one["tiles"] == 1 and one["seamed"] == 0
    assert any("saves nothing" in line for line in said)


def test_cli_tiled_refuses_writing_over_its_input(tmp_path):
    laspy = pytest.importorskip("laspy")
    from pyargus import cli

    src = tmp_path / "c.las"
    header = laspy.LasHeader(version="1.4", point_format=6)
    data = laspy.LasData(header)
    data.x, data.y, data.z = (np.zeros(4) for _ in range(3))
    data.write(str(src))
    with pytest.raises(SystemExit, match="new file"):
        cli.main(["classify-ground", str(src), "--out", str(src),
                  "--tiled", "--force"])
