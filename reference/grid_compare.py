"""Two ground surfaces compared like for like: the grid handling.

The generic half of a comparison between a pyArgus DTM (an Esri ASCII
grid) and a vendor's finer DEM (a GeoTIFF). The job scripts that run it
against client deliveries are kept outside this public repository; the
pieces here are the ones a test can pin with a planted surface, because
a y-flip or a half-cell tiepoint error still yields a plausible median.

**What such a comparison does and does not check.** A vendor DEM built
from the SAME returns pyArgus classified shares whatever datum the
lidar has, so a difference is a disagreement about *which returns are
ground*, not about elevation truth. Control marks are the only outside
referee.

The trap: a vendor raster at 0.25 ft against a 3 ft DTM means sampling
one pixel per cell compares a point against a 144-pixel block mean and
reports surface roughness as a difference. ``_block_mean`` averages
every fine pixel inside each coarse cell first, so the two sides answer
the same question. Sampling the nearest pixel instead LOWERS the rmse --
an error that looks like an improvement, because it compares a point
against a point instead of a block against a block.

A caution the first real run taught: the median moves by about 0.015 ft
if the two grids are registered half a coarse cell differently, so a
median from this is quoted to two decimals and re-run, never
remembered.
"""

import numpy as np


def read_asc(path):
    """An Esri ASCII grid as (array, x0, y0, cell), north-up, y ascending.

    The file stores rows north to south; the array is flipped so that
    row 0 is the SOUTH row and ``y0`` is its cell-centre baseline, which
    is the orientation the rest of this module works in.
    """
    header, values = {}, []
    with open(path, "r", encoding="utf-8") as handle:
        for _ in range(6):
            key, value = handle.readline().split()
            header[key.lower()] = float(value)
        for line in handle:
            if line.strip():
                values.append(np.fromstring(line, sep=" "))
    grid = np.vstack(values)
    nrows, ncols = int(header["nrows"]), int(header["ncols"])
    if grid.shape != (nrows, ncols):
        raise ValueError(f"{path.name}: header says {nrows}x{ncols}, read "
                         f"{grid.shape[0]}x{grid.shape[1]}")
    grid = np.where(grid == header["nodata_value"], np.nan, grid)
    return (np.flipud(grid), header["xllcorner"], header["yllcorner"],
            header["cellsize"])


def read_geotiff(path):
    """A single-band GeoTIFF as (array, x0, y0, cell), y ascending.

    Only what a vendor DEM needs: the model pixel scale and tiepoint
    tags, an axis-aligned north-up grid, and the nodata tag as a string.
    """
    import tifffile

    with tifffile.TiffFile(path) as handle:
        page = handle.pages[0]
        tags = page.tags
        scale = tags["ModelPixelScaleTag"].value
        tie = tags["ModelTiepointTag"].value
        array = page.asarray().astype(np.float64)
        nodata = tags["GDAL_NODATA"].value if "GDAL_NODATA" in tags else None
    if scale[0] != scale[1]:
        raise ValueError(f"{path.name}: non-square pixels {scale[:2]}")
    if tie[0] or tie[1]:
        raise ValueError(f"{path.name}: tiepoint is not at pixel (0, 0)")
    cell = float(scale[0])
    # The tiepoint is the UPPER-LEFT CORNER of pixel (0, 0); flipping to
    # y-ascending puts the last raster row first, so the new row 0's
    # cell centre sits half a cell above the grid's south edge.
    x0 = float(tie[3]) + cell / 2.0
    y0 = float(tie[4]) - cell * array.shape[0] + cell / 2.0
    if nodata is not None:
        array = np.where(array == float(nodata), np.nan, array)
    array = np.where(array < -1e5, np.nan, array)
    return np.flipud(array), x0, y0, cell


def _block_mean(fine, fx0, fy0, fcell, shape, cx0, cy0, ccell):
    """The fine pixels averaged over each coarse cell.

    Each coarse cell covers the fine pixels whose centres fall inside
    it. The sum and the count are accumulated with ``np.add.at`` over
    the flattened coarse index, so a cell with no fine pixel under it
    comes back NaN rather than zero.
    """
    rows, cols = fine.shape
    fx = fx0 + np.arange(cols) * fcell
    fy = fy0 + np.arange(rows) * fcell
    jx = np.floor((fx - (cx0 - ccell / 2.0)) / ccell).astype(np.int64)
    jy = np.floor((fy - (cy0 - ccell / 2.0)) / ccell).astype(np.int64)
    inside_x = (jx >= 0) & (jx < shape[1])
    inside_y = (jy >= 0) & (jy < shape[0])
    fine = fine[np.ix_(inside_y, inside_x)]
    jx, jy = jx[inside_x], jy[inside_y]
    flat = (jy[:, None] * shape[1] + jx[None, :]).ravel()
    good = np.isfinite(fine).ravel()
    total = np.zeros(shape[0] * shape[1])
    count = np.zeros(shape[0] * shape[1], dtype=np.int64)
    np.add.at(total, flat[good], fine.ravel()[good])
    np.add.at(count, flat[good], 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    return mean.reshape(shape), count.reshape(shape)


def ground_counts(cloud, shape, x0, y0, cell, *, log=print):
    """Class-2 points per DTM cell, streamed from the classified cloud.

    A DTM cell is either MEASURED, because ground points fell in it, or
    FILLED, because ``--max-fill`` reached across a hole to invent it.
    Those are different kinds of number, and a comparison that mixes
    them reports an interpolation as a disagreement about what ground
    is. On the corridor that motivated this, the two largest interior
    disagreements with the vendor's surface -- about 15 ft either way --
    were both cells holding not one class-2 point.
    """
    from pyargus.formats import las as las_mod

    counts = np.zeros(shape[0] * shape[1], dtype=np.int64)
    total = 0
    for chunk in las_mod.iter_points(cloud,
                                     fields=("x", "y", "classification")):
        codes = np.asarray(chunk["classification"])
        keep = codes == 2
        if not keep.any():
            continue
        jx = np.floor((np.asarray(chunk["x"])[keep] - x0) / cell)
        jy = np.floor((np.asarray(chunk["y"])[keep] - y0) / cell)
        jx, jy = jx.astype(np.int64), jy.astype(np.int64)
        good = (jx >= 0) & (jx < shape[1]) & (jy >= 0) & (jy < shape[0])
        np.add.at(counts, jy[good] * shape[1] + jx[good], 1)
        total += int(keep.sum())
    log(f"ground:      {total:,} class-2 points binned onto the DTM grid; "
        f"{int(np.count_nonzero(counts)):,} of {counts.size:,} cells hold "
        f"at least one")
    return counts.reshape(shape)


def ground_agreement(ours, theirs, log=print):
    """Which cells each classification calls ground, cell by cell.

    A median difference says how far apart two surfaces sit; it cannot
    say whether that is the same ground measured differently or
    different ground. This is the other question: of the cells that
    either side calls ground, how many does only one of them call
    ground? A classifier that is merely offset agrees about WHERE the
    ground is; one that is missing returns under canopy does not.
    """
    universe = (ours > 0) | (theirs > 0)
    both = (ours > 0) & (theirs > 0)
    only_ours = (ours > 0) & (theirs == 0)
    only_theirs = (ours == 0) & (theirs > 0)
    total = int(universe.sum())
    result = {"cells_either_calls_ground": total,
              "both": int(both.sum()),
              "only_pyargus": int(only_ours.sum()),
              "only_lp360": int(only_theirs.sum()),
              "agreement": round(float(both.sum() / max(total, 1)), 4)}
    log(f"\n   of {total:,} cells that either classification calls ground:")
    log(f"     both agree      {result['both']:>9,}  "
        f"({100 * result['both'] / max(total, 1):.2f}%)")
    log(f"     only pyArgus    {result['only_pyargus']:>9,}  "
        f"({100 * result['only_pyargus'] / max(total, 1):.2f}%)")
    log(f"     only LP360      {result['only_lp360']:>9,}  "
        f"({100 * result['only_lp360'] / max(total, 1):.2f}%)")
    return result


def _stats(diff):
    """Median, nmad and rmse of a difference, plus the tails.

    An empty selection is a real answer, not a crash: ask for cells
    more than N from the boundary on a narrow corridor and there may be
    none. The percentiles used to index an empty array and die inside
    numpy, several screens away from the band that was empty.
    """
    diff = np.asarray(diff)
    if diff.size == 0:
        return {"n": 0, "median": None, "nmad": None, "rmse": None,
                "p1": None, "p5": None, "p95": None, "p99": None,
                "over_0_5_ft": 0, "over_1_ft": 0, "over_2_ft": 0}
    median = float(np.median(diff))
    nmad = float(1.4826 * np.median(np.abs(diff - median)))
    return {"n": int(diff.size), "median": round(median, 3),
            "nmad": round(nmad, 3),
            "rmse": round(float(np.sqrt(np.mean(diff ** 2))), 3),
            "p1": round(float(np.percentile(diff, 1)), 3),
            "p5": round(float(np.percentile(diff, 5)), 3),
            "p95": round(float(np.percentile(diff, 95)), 3),
            "p99": round(float(np.percentile(diff, 99)), 3),
            "over_0_5_ft": int(np.count_nonzero(np.abs(diff) > 0.5)),
            "over_1_ft": int(np.count_nonzero(np.abs(diff) > 1.0)),
            "over_2_ft": int(np.count_nonzero(np.abs(diff) > 2.0))}
