"""Streaming acceptance: the same answers, and a cloud we could not
open before.

Two halves, because "it is faster" is not the claim:

* EQUALITY, on Summerville_SS.las (15.28M points, pf7, three extra
  dimensions, a real CRS). A streamed pass and a whole-file read must
  produce identical arrays and an identical density grid. If they
  ever differ, the streaming path is a second program wearing the
  first one's name.
* SCALE, on "UAS Flight Mission.PointCloud25D.las" -- 349.79M points,
  9.09 GB, the dense image-matching product beside the lidar. The
  whole-file path needs ~13.6 GB of arrays for the default fields
  before laspy's own packed record is counted; that is the delivery
  pyArgus simply could not open. Streamed, it is one chunk at a time.

Peak working set is measured, not asserted from theory, via the Win32
process API. Z: stays read-only throughout.

Run by hand: python -m reference.summerville_streaming
"""

import ctypes
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np

from pyargus.formats import las as las_mod
from pyargus.qa import density as density_mod

ROOT = Path("Z:/Users/BJordan/Summerville_SS")
CLOUD = ROOT / "Summerville_SS.las"
BIG = ROOT / "UAS Flight Mission.PointCloud25D.las"
CELL = 3.0
FIELDS = ("x", "y", "z", "gps_time", "intensity", "classification",
          "point_source_id")


class _Mem(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def _memory_api():
    """K32GetProcessMemoryInfo, declared so it actually works.

    ctypes defaults a function's return type to C int, and
    GetCurrentProcess returns a HANDLE -- so on 64-bit the pseudo
    handle is truncated, every call fails, and an unchecked wrapper
    reports a serene 0 MB. That is how this script claimed a 350M
    point cloud streamed in "+0 MB" three times running. The return
    value is checked here, so a broken measurement raises instead of
    flattering the result.
    """
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    fn = k32.K32GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Mem), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    return k32, fn


def peak_mb():
    """This process's peak working set, in MB. Raises if unavailable."""
    k32, fn = _memory_api()
    m = _Mem()
    m.cb = ctypes.sizeof(_Mem)
    if not fn(k32.GetCurrentProcess(), ctypes.byref(m), m.cb):
        raise OSError("K32GetProcessMemoryInfo failed; refusing to report "
                      "a memory figure this script cannot measure")
    return m.PeakWorkingSetSize / 1e6


def stream_big_in_a_fresh_process():
    """Stream the big cloud in a SUBPROCESS and report its own peak.

    Measuring in this process would be meaningless: the equality half
    above has already read 15M points whole, so the allocator has the
    arena and neither the current nor the peak working set grows when
    the streaming half runs. A number that reads "+0 MB" is true and
    tells the reader nothing. A fresh process attributes its peak to
    the streaming pass and nothing else.
    """
    import json
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "reference.summerville_streaming",
         "--stream-only"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent))
    if out.returncode != 0:
        raise RuntimeError(f"streaming subprocess failed: "
                           f"{(out.stderr or out.stdout)[-800:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def _stream_only():
    """The subprocess entry point: stream, then report peak as JSON."""
    import json

    baseline = peak_mb()
    info = las_mod.cloud_info(BIG)
    t0 = time.perf_counter()
    dens, _, _ = density_mod.density_grid_streamed(
        las_mod.iter_points(BIG, fields=("x", "y")),
        info["mins"][:2], info["maxs"][:2], cell=CELL)
    covered = dens[dens > 0]
    print(json.dumps({
        "seconds": time.perf_counter() - t0,
        "peak_mb": peak_mb(),
        "baseline_mb": baseline,
        "density_median": float(np.median(covered)),
        "covered_cells": int(covered.size),
    }))


def main():
    results = {}

    info = las_mod.cloud_info(CLOUD)
    print(f"cloud:   {info['point_count']:,} points, pf{info['point_format']}"
          f", extra {info['extra_dims']}, "
          f"crs {info['crs'].name if info['crs'] else 'none'}")
    results["header_point_count"] = info["point_count"]

    # --- equality: streamed vs whole, on real data -------------------
    t0 = time.perf_counter()
    whole = las_mod.read_points(CLOUD, fields=FIELDS)
    whole_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    parts = {k: [] for k in FIELDS}
    chunks = 0
    for chunk in las_mod.iter_points(CLOUD, fields=FIELDS):
        chunks += 1
        for k, v in chunk.items():
            parts[k].append(v)
    joined = {k: np.concatenate(v) for k, v in parts.items()}
    stream_s = time.perf_counter() - t0

    identical = all(np.array_equal(whole[k], joined[k]) for k in FIELDS)
    # the two timings are NOT a fair speed comparison: the whole read
    # goes first and pays the cold disk cache for all 0.64 GB
    print(f"equality: {chunks} chunks; every one of {len(FIELDS)} fields "
          f"identical to the whole-file read: {identical} "
          f"({whole_s:.1f} s whole cold, {stream_s:.1f} s streamed warm)")
    results["fields_identical"] = bool(identical)
    del joined, parts

    # --- the same density grid, accumulated ---------------------------
    want, wx, wy = density_mod.density_grid(whole["x"], whole["y"], cell=CELL)
    del whole
    got, gx, gy = density_mod.density_grid_streamed(
        las_mod.iter_points(CLOUD, fields=("x", "y")),
        info["mins"][:2], info["maxs"][:2], cell=CELL)
    grid_same = (np.array_equal(wx, gx) and np.array_equal(wy, gy)
                 and np.array_equal(want, got))
    covered = got[got > 0]
    print(f"density:  streamed grid identical to whole-cloud grid: "
          f"{grid_same}; median {np.median(covered):.2f} pts/unit2 over "
          f"{covered.size:,} cells")
    results["density_grid_identical"] = bool(grid_same)
    results["density_median"] = float(np.median(covered))

    # --- scale: the cloud the whole-file path cannot open -------------
    big = las_mod.cloud_info(BIG)
    whole_gb = big["point_count"] * 39 / 1e9
    print(f"\nbig:     {BIG.name}")
    print(f"         {big['point_count']:,} points, "
          f"{BIG.stat().st_size / 1e9:.2f} GB on disk, "
          f"pf{big['point_format']}")
    print(f"         a whole-file read needs ~{whole_gb:.1f} GB of arrays "
          f"for the default fields, before laspy's packed record")
    results["big_point_count"] = big["point_count"]
    results["big_whole_read_gb"] = float(whole_gb)

    streamed = stream_big_in_a_fresh_process()
    print(f"         STREAMED in {streamed['seconds']:.0f} s at a peak of "
          f"{streamed['peak_mb']:.0f} MB for the whole process "
          f"(interpreter baseline {streamed['baseline_mb']:.0f} MB) -- "
          f"against the ~{whole_gb * 1000:.0f} MB of arrays a whole-file "
          f"read would need before laspy's own record")
    print(f"         median {streamed['density_median']:.2f} pts/unit2 "
          f"over {streamed['covered_cells']:,} cells")
    results["big_stream_seconds"] = float(streamed["seconds"])
    results["big_peak_mb"] = float(streamed["peak_mb"])
    results["big_density_median"] = float(streamed["density_median"])
    results["big_covered_cells"] = int(streamed["covered_cells"])
    return results


if __name__ == "__main__":
    import sys

    if "--stream-only" in sys.argv:
        _stream_only()
    else:
        main()
