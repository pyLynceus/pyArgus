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


def test_cli_tiled_matches_the_whole_cloud_command(tmp_path):
    """End to end through `pyargus classify-ground --tiled`, against
    the same command without it."""
    laspy = pytest.importorskip("laspy")
    from pyargus import cli

    x, y, z = scene(seed=7, n=120_000)
    header = laspy.LasHeader(version="1.4", point_format=6)
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([0.0, 0.0, 0.0])
    data = laspy.LasData(header)
    data.x, data.y, data.z = x, y, z
    data.return_number = np.ones(x.size, dtype=np.uint8)
    data.number_of_returns = np.ones(x.size, dtype=np.uint8)
    src = tmp_path / "cloud.las"
    data.write(str(src))

    common = ["classify-ground", str(src), "--cell", str(CELL),
              "--slope", str(SLOPE), "--window", str(WINDOW),
              "--threshold", str(THRESHOLD), "--scalar", str(SCALAR)]
    plain = tmp_path / "plain.las"
    tiled = tmp_path / "tiled.las"
    assert cli.main(common + ["--out", str(plain)]) == 0
    assert cli.main(common + ["--out", str(tiled), "--tiled",
                              "--tile-size", "300", "--halo", "60"]) == 0

    a = laspy.read(str(plain)).classification == 2
    b = laspy.read(str(tiled)).classification == 2
    assert a.sum() > 0
    assert np.array_equal(a, b), int((a != b).sum())


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
