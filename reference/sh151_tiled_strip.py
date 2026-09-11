"""Tiled ground equality at real scale, on one SH 151 strip.

Summerville is too small to hold a seam at the survey-feet defaults:
the halo there is 1,260 ft (SMRF's own reach at cell 3 / window 60)
and the project is 1,841 ft across. An SH 151 strip is 10,569 ft of
corridor and 41.4M points, which is where the defaults actually run --
so this is the equality measured where it will be used: the plain
command's driver and the tiled one, their written classifications
compared row by row, at the DEFAULT halo, with 1,500 ft cores so that
every one of the 8 halo boxes stops well short of the strip.

Not in the regression gate: it reads client data and holds the whole
strip for the comparison (several GB, several minutes). Run by hand
and record in RESULTS.md.

Z: stays read-only; outputs go to a local temp directory.

Run by hand: python -m reference.sh151_tiled_strip
"""

import glob
import tempfile
import time
from pathlib import Path

import numpy as np

from pyargus.classify import job as ground_job
from pyargus.formats import las as las_mod

STRIP_GLOB = "Z:/Users/BJordan/SH 151/LIDAR/**/*.las"
PARAMS = dict(cell=3.0, slope=0.15, window=60.0, threshold=1.5, scalar=1.25)
TILE = 1500.0


def main():
    strip = Path(sorted(glob.glob(STRIP_GLOB, recursive=True))[0])
    info = las_mod.cloud_info(strip)
    print(f"strip:   {strip.name}: {info['point_count']:,} points")
    with tempfile.TemporaryDirectory() as temp:
        whole_out, tiled_out = Path(temp) / "whole.las", Path(temp) / "tiled.las"
        t0 = time.perf_counter()
        whole = ground_job.classify_ground_whole(strip, whole_out, **PARAMS)
        whole_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        tiled = ground_job.classify_ground_tiled(
            strip, tiled_out, tile_size=TILE, **PARAMS)
        tiled_s = time.perf_counter() - t0
        if tiled["seamed"] < tiled["tiles"] or tiled["tiles"] < 4:
            raise AssertionError("every tile must have a real seam")
        a = las_mod.read_points(whole_out, fields=("classification",))[
            "classification"]
        b = las_mod.read_points(tiled_out, fields=("classification",))[
            "classification"]
    mismatches = int(np.count_nonzero(a != b))
    print(f"whole:   {whole['ground']:,} ground ({100 * whole['ground_fraction']:.2f}%), "
          f"{whole_s:.0f} s")
    print(f"tiled:   {tiled['tiles']} tiles, halo {tiled['halo']:,.0f}, largest "
          f"box {100 * tiled['largest_box']:.0f}%, at most "
          f"{tiled['max_tile_points']:,} points held, {tiled_s:.0f} s")
    print(f"EQUALITY: {mismatches:,} of {a.size:,} classifications differ")
    return {"mismatches": mismatches, "tiles": tiled["tiles"],
            "halo": tiled["halo"], "largest_box": tiled["largest_box"],
            "max_tile_points": tiled["max_tile_points"],
            "ground": whole["ground"], "total": whole["total"],
            "whole_s": whole_s, "tiled_s": tiled_s}


if __name__ == "__main__":
    main()
