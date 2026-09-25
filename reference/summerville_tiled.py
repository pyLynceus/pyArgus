"""Tiled ground classification, checked against the plain command.

The claim tiling makes is EQUALITY with ``pyargus classify-ground``
run without ``--tiled``, and this measures exactly that: both commands'
own code paths (classify.job's two drivers) on the same file, their
written classifications compared row by row.

The first version of this script answered a different question. It
compared the tiled run with a whole-cloud mask it built for itself,
under a labeling rule the plain command does not use (it let non-last
returns be ground), so its "0 mismatches" said nothing about the
command. And its tiles' halo boxes covered the whole project, so it
exercised no seam either: a tile whose box spans the project IS the
whole-cloud run.

So the seams here are made real on purpose. At window 60 the halo is
1,260 ft, which swallows most of Summerville's 1,841 x 1,687 ft, so
this runs at window 30 (halo 330 ft, SMRF's own reach) with 600 ft
cores: all 12 boxes stop short of the project, the largest at about
half of it. The script refuses to report anything unless that holds.
``sh151_tiled_strip.py`` runs the same equality at the survey-feet
defaults on a real 41.4M-point strip.

Then the arithmetic of the DEFAULT plan on that strip, which is where
tiling's honest limits show.

Z: stays read-only; outputs go to a local temp directory.

Run by hand: python -m reference.summerville_tiled
"""

import glob
import tempfile
import time
from pathlib import Path

import numpy as np

from pyargus.classify import job as ground_job
from pyargus.classify import tiles as tiles_mod
from pyargus.formats import las as las_mod

ROOT = Path("Z:/Users/BJordan/Summerville_SS")
CLOUD = ROOT / "Summerville_SS.las"
PARAMS = dict(cell=3.0, slope=0.15, window=30.0, threshold=1.5, scalar=1.25)
TILE = 600.0
STRIP_GLOB = "Z:/Users/BJordan/SH 151/LIDAR/**/*.las"


def classes(path):
    return las_mod.read_points(path, fields=("classification",))[
        "classification"]


def main():
    results = {}
    info = las_mod.cloud_info(CLOUD)
    print(f"cloud:   {info['point_count']:,} points, "
          f"{info['maxs'][0] - info['mins'][0]:,.0f} x "
          f"{info['maxs'][1] - info['mins'][1]:,.0f} ft")

    with tempfile.TemporaryDirectory() as temp:
        whole_out, tiled_out = Path(temp) / "whole.las", Path(temp) / "tiled.las"
        t0 = time.perf_counter()
        whole = ground_job.classify_ground_whole(CLOUD, whole_out, **PARAMS)
        whole_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        tiled = ground_job.classify_ground_tiled(
            CLOUD, tiled_out, tile_size=TILE, **PARAMS)
        tiled_s = time.perf_counter() - t0
        if (tiled["tiles"] < 4 or tiled["seamed"] < tiled["tiles"]
                or tiled["largest_box"] > 0.6):
            raise AssertionError(
                f"this acceptance must exercise seams: {tiled['seamed']} of "
                f"{tiled['tiles']} tiles have one, largest box "
                f"{100 * tiled['largest_box']:.0f}% of the project")
        a, b = classes(whole_out), classes(tiled_out)
        source = las_mod.read_points(
            CLOUD, fields=("return_number", "number_of_returns",
                           "classification"))
    returns = source
    delivered_noise = np.isin(source["classification"],
                              ground_job.NOISE_CLASSES)
    nonlast = returns["return_number"] != returns["number_of_returns"]
    mismatches = int(np.count_nonzero(a != b))
    print(f"whole:   {whole['ground']:,} ground of {whole['total']:,} "
          f"({100 * whole['ground_fraction']:.2f}%), {whole_s:.0f} s")
    print(f"tiled:   {tiled['tiles']} tiles of {TILE:g} ft, halo "
          f"{tiled['halo']:g}, every box short of the project (largest "
          f"{100 * tiled['largest_box']:.0f}%), {tiled_s:.0f} s")
    print(f"         at most {tiled['max_tile_points']:,} points held in one "
          f"tile; {tiled['points_read']:,} read across all "
          f"({tiled['points_read'] / whole['candidates']:.1f}x the "
          f"candidates)")
    print(f"EQUALITY: {mismatches:,} of {a.size:,} classifications differ "
          f"from the plain command")
    print(f"policy:  non-last returns labeled ground: whole "
          f"{int(np.count_nonzero((a == 2) & nonlast))}, tiled "
          f"{int(np.count_nonzero((b == 2) & nonlast))} "
          f"(of {int(nonlast.sum()):,} non-last returns)")
    # the delivery carries class 7, so this cloud measures the noise
    # policy on real data: none of those points may be called ground,
    # and each must come out of both commands carrying its own class
    noise_as_ground = int(np.count_nonzero((a == 2) & delivered_noise)
                          + np.count_nonzero((b == 2) & delivered_noise))
    kept = int(np.count_nonzero(
        (a == source["classification"]) & delivered_noise))
    print(f"noise:   {int(delivered_noise.sum()):,} delivered class-7/18 "
          f"points; {noise_as_ground} labeled ground by either command; "
          f"{kept:,} came through with their own class")
    results.update(
        delivered_noise=int(delivered_noise.sum()),
        noise_as_ground=noise_as_ground, noise_kept=kept,
        whole_noise=whole["noise"], tiled_noise=tiled["noise"],
        mismatches=mismatches, tiles=tiled["tiles"], seamed=tiled["seamed"],
        halo=tiled["halo"], largest_box=round(tiled["largest_box"], 4),
        area_read=round(tiled["area_read"], 3),
        whole_ground_fraction=whole["ground_fraction"],
        tiled_ground_fraction=tiled["ground_fraction"],
        max_tile_points=tiled["max_tile_points"],
        nonlast_ground=int(np.count_nonzero((a == 2) & nonlast)
                           + np.count_nonzero((b == 2) & nonlast)))

    # --- the DEFAULT plan on one real SH 151 strip ------------------
    strips = sorted(glob.glob(STRIP_GLOB, recursive=True))
    if strips:
        strip = Path(strips[0])
        si = las_mod.cloud_info(strip)
        halo, tile = tiles_mod.resolve_plan(3.0, 60.0)
        xe, ye = tiles_mod.global_edges(si["mins"][:2], si["maxs"][:2], 3.0)
        cells = (xe.size - 1) * (ye.size - 1)
        cost = tiles_mod.plan_summary(
            tiles_mod.plan_tiles(xe, ye, 3.0, halo, tile), xe, ye)
        # a DEM and its slope in float64, two boolean masks
        surface_mb = cells * (8 + 8 + 1 + 1) / 1e6
        print(f"\nscale:   {strip.name}: {si['point_count']:,} points, "
              f"{si['maxs'][0] - si['mins'][0]:,.0f} x "
              f"{si['maxs'][1] - si['mins'][1]:,.0f} ft")
        print(f"         the surface: {cells / 1e6:.2f}M cells, "
              f"{surface_mb:.0f} MB -- small whatever the point count")
        print(f"         the DEFAULT plan (cell 3 / window 60: halo "
              f"{halo:,.0f}, cores {tile:,.0f}): {cost['tiles']} tiles, the "
              f"largest box {100 * cost['largest_box']:.0f}% of the strip "
              f"(~{cost['largest_box'] * si['point_count'] / 1e6:.0f}M "
              f"points at even density) -- what one tile holds is set by "
              f"the box, and at these defaults the box is most of the strip")
        results.update(strip_cells=int(cells), strip_default_tiles=cost["tiles"],
                       strip_default_largest_box=round(cost["largest_box"], 4))
    return results


if __name__ == "__main__":
    main()
