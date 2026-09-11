"""Tiled ground classification, checked against the whole-cloud run.

The claim tiling makes is EQUALITY, and Summerville is where it can be
proved on real data: 15.28M points still fit in memory, so the
whole-cloud answer exists to compare against. A tiled run that merely
looks plausible would be worthless on the block this exists for -- SH
151's 917M points across 22 strips, where nobody can check by eye.

Then the scale half, on one real SH 151 strip (41.4M points, 10,569 ft
of corridor): the surface is an 11 MB raster whatever the point count,
so the job is bounded by the raster rather than the cloud.

Z: stays read-only; outputs go to a local temp directory.

Run by hand: python -m reference.summerville_tiled
"""

import glob
import tempfile
import time
from pathlib import Path

import numpy as np

from pyargus.classify import ground as ground_mod
from pyargus.classify import job as ground_job
from pyargus.classify import tiles as tiles_mod
from pyargus.formats import las as las_mod

ROOT = Path("Z:/Users/BJordan/Summerville_SS")
CLOUD = ROOT / "Summerville_SS.las"
CELL, SLOPE, WINDOW = 3.0, 0.15, 60.0
TILE = 600.0        # small on purpose: a real seam grid, not one tile
THRESHOLD, SCALAR = 1.5, 1.25


def main():
    results = {}
    halo = tiles_mod.required_halo(CELL, WINDOW)
    info = las_mod.cloud_info(CLOUD)
    print(f"cloud:   {info['point_count']:,} points, "
          f"{info['maxs'][0] - info['mins'][0]:,.0f} x "
          f"{info['maxs'][1] - info['mins'][1]:,.0f} ft")
    print(f"halo:    {halo:,.0f} ft (SMRF's own reach, R(R+1) cells at "
          f"cell {CELL:g} / window {WINDOW:g})")
    results["halo"] = halo

    # --- the whole-cloud answer, on the returns that see the ground --
    points = las_mod.read_points(
        CLOUD, fields=("x", "y", "z", "return_number", "number_of_returns"))
    last = points["return_number"] == points["number_of_returns"]
    x, y, z = points["x"], points["y"], points["z"]
    t0 = time.perf_counter()
    whole = ground_mod.smrf(x[last], y[last], z[last], cell=CELL,
                            slope=SLOPE, window=WINDOW,
                            threshold=THRESHOLD, scalar=SCALAR)
    whole_s = time.perf_counter() - t0
    # every point judged against that surface, not just the last returns
    whole_mask = ground_mod.classify_against(
        ground_mod.GroundSurface(
            dem=whole.dem, dem_slope=whole.dem_slope,
            object_cells=whole.object_cells, low_cells=whole.low_cells,
            x_edges=whole.x_edges, y_edges=whole.y_edges),
        x, y, z, threshold=THRESHOLD, scalar=SCALAR)
    print(f"whole:   {whole_mask.sum():,} ground of {x.size:,} "
          f"({100 * whole_mask.mean():.2f}%), {whole_s:.0f} s")
    results["whole_ground_fraction"] = float(whole_mask.mean())

    # --- the same thing, tiled -------------------------------------
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp) / "tiled.las"
        t0 = time.perf_counter()
        # FORCE several tiles. Summerville is 1,841 x 1,687 ft and the
        # default core is six halos (7,560 ft), so the default would
        # run as ONE tile and prove nothing about seams -- the first
        # version of this script did exactly that and reported a
        # meaningless 0.
        stats = ground_job.classify_ground_tiled(
            CLOUD, out, cell=CELL, slope=SLOPE, window=WINDOW,
            threshold=THRESHOLD, scalar=SCALAR, halo=halo,
            tile_size=TILE)
        tiled_s = time.perf_counter() - t0
        tiled_mask = las_mod.read_points(
            out, fields=("classification",))["classification"] == 2
    mismatches = int((tiled_mask != whole_mask).sum())
    print(f"tiled:   {stats['tiles']} tiles of {TILE:g} ft, "
          f"{tiled_s:.0f} s, {tiled_mask.sum():,} ground")
    if stats["tiles"] < 4:
        raise AssertionError("this acceptance must exercise seams; "
                             f"only {stats['tiles']} tile(s) ran")
    print(f"EQUALITY: {mismatches:,} of {x.size:,} points differ from the "
          f"whole-cloud run")
    results["tiles"] = stats["tiles"]
    results["mismatches"] = mismatches
    results["tiled_ground_fraction"] = float(tiled_mask.mean())

    # --- scale: one real SH 151 strip ------------------------------
    strips = sorted(glob.glob("Z:/Users/BJordan/SH 151/LIDAR/**/*.las",
                              recursive=True))
    if strips:
        strip = Path(strips[0])
        si = las_mod.cloud_info(strip)
        xe, ye = tiles_mod.global_edges(si["mins"][:2], si["maxs"][:2], CELL)
        cells = (xe.size - 1) * (ye.size - 1)
        plan = tiles_mod.plan_tiles(xe, ye, CELL, halo, 6.0 * halo)
        print(f"\nscale:   {strip.name}: {si['point_count']:,} points, "
              f"{si['maxs'][0] - si['mins'][0]:,.0f} ft of corridor")
        print(f"         {cells / 1e6:.1f}M cells = {cells * 8 / 1e6:.0f} MB "
              f"per raster, {len(plan)} tiles -- the job is bounded by "
              f"the RASTER, not the {si['point_count'] / 1e6:.0f}M points")
        results["strip_cells"] = int(cells)
        results["strip_tiles"] = len(plan)
    return results


if __name__ == "__main__":
    main()
