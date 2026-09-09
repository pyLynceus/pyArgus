"""Phase-6 acceptance: contours and DSM from the real Summerville cloud.

Contours at 1 ft from the delivered class-2 DTM (3-ft cells), DSM from
all returns. The referee is internal consistency: every contour vertex
resampled against the DTM must sit on its level (the marching-squares
interpolation and the grid are the same linear world), and the DSM
must ride at or above the DTM everywhere both exist.

Read-only against Z:; outputs land in reference/reports/summerville
(gitignored). Run: python -m reference.summerville_contours
"""

import time

import numpy as np

from pyargus.core import gridding
from pyargus.formats import dxf, geojson, las
from pyargus.surfaces import contours, dtm
from reference.summerville import CLOUD

OUT = "reference/reports/summerville"
INTERVAL = 1.0
CELL = 3.0


def main():
    results = {}
    print(f"cloud: {CLOUD}")
    points = las.read_points(CLOUD, fields=("x", "y", "z", "classification"))
    ground = points["classification"] == 2

    dtm_grid, xe, ye = dtm.dtm_grid(points["x"][ground], points["y"][ground],
                                    points["z"][ground], CELL)
    finite = dtm_grid[np.isfinite(dtm_grid)]
    print(f"dtm:  {finite.size:,} cells, z {finite.min():.1f}.."
          f"{finite.max():.1f} ft")

    t0 = time.perf_counter()
    lines = contours.contour_grid(dtm_grid, xe, ye, INTERVAL, index_every=5)
    levels = sorted({line.level for line in lines})
    total = sum(np.linalg.norm(np.diff(line.xy, axis=0), axis=1).sum()
                for line in lines)
    results["n_lines"] = len(lines)
    results["n_levels"] = len(levels)
    results["total_length"] = float(total)
    print(f"contours: {len(lines)} lines over {len(levels)} levels "
          f"({levels[0]:g}..{levels[-1]:g}), total {total:,.0f} ft, "
          f"{time.perf_counter() - t0:.0f} s")

    # referee 1: vertices sit on their level against the DTM itself
    errors = []
    for line in lines:
        z = gridding.bilinear_sample(
            np.where(np.isfinite(dtm_grid), dtm_grid, np.nan),
            line.xy[:, 0], line.xy[:, 1], xe, ye)
        errors.append(np.abs(z[np.isfinite(z)] - line.level))
    errors = np.concatenate(errors)
    results["vertex_err_max"] = float(errors.max())
    print(f"vertex-vs-DTM |dz|: median {np.median(errors):.4f}  "
          f"p95 {np.percentile(errors, 95):.4f}  "
          f"max {errors.max():.3f} ft  ({errors.size:,} vertices)")

    # referee 2: DSM rides at or above the DTM. The grids have their
    # OWN origins (grid_edges floors each dataset's min), so compare
    # over the WORLD intersection -- the review panel proved an
    # index-from-zero crop manufactures below-DTM artifacts.
    dsm_grid, xe2, ye2 = dtm.dsm_grid(points["x"], points["y"], points["z"],
                                      CELL)
    ox = int(round((xe[0] - xe2[0]) / CELL))   # dtm origin inside dsm
    oy = int(round((ye[0] - ye2[0]) / CELL))
    assert ox >= 0 and oy >= 0, "all-returns extent should contain ground's"
    nx = min(dtm_grid.shape[0], dsm_grid.shape[0] - ox)
    ny = min(dtm_grid.shape[1], dsm_grid.shape[1] - oy)
    dsm_win = dsm_grid[ox:ox + nx, oy:oy + ny]
    both = np.isfinite(dtm_grid[:nx, :ny]) & np.isfinite(dsm_win)
    diff = (dsm_win - dtm_grid[:nx, :ny])[both]
    results["dsm_dtm_median"] = float(np.median(diff))
    results["below_dtm_cells"] = int((diff < -0.5).sum())
    print(f"dsm-dtm over {diff.size:,} world-aligned cells: "
          f"min {diff.min():+.2f}, median {np.median(diff):+.2f}, "
          f"p95 {np.percentile(diff, 95):.1f} ft, "
          f"below-DTM cells {int((diff < -0.5).sum()):,}")

    import os
    os.makedirs(OUT, exist_ok=True)
    dxf.write_contours_dxf(f"{OUT}/contours_1ft.dxf", lines)
    geojson.write_contours_geojson(f"{OUT}/contours_1ft.geojson", lines)
    dtm.write_esri_ascii(f"{OUT}/dsm.asc", dsm_grid, xe2, ye2)
    print(f"wrote: {OUT}/contours_1ft.dxf, .geojson, dsm.asc")
    return results


if __name__ == "__main__":
    main()
