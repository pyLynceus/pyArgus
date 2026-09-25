"""The grid handling behind comparing a DTM with a vendor's DEM.

`reference/grid_compare.py` holds the reading and averaging a DTM
comparison stands on. A median from such a comparison is only worth
anything if the two rasters are laid on top of each other correctly,
and the ways to get that wrong are quiet ones -- the first pass at a
real comparison ran as a throwaway, registered the grids half a coarse
cell differently, and reported a median 0.02 ft off:

* an Esri ASCII grid stores its rows NORTH to SOUTH and a GeoTIFF
  usually does too, so a reader that forgets to flip one of them
  compares the site with a mirror image of itself -- which still
  produces a plausible median and a slightly worse rmse;
* a GeoTIFF tiepoint is the UPPER-LEFT CORNER of pixel (0, 0), not its
  centre, so a half-pixel error hides in any comparison of two grids
  at different resolutions;
* a vendor raster at 0.25 ft against a 3 ft DTM means sampling one
  pixel per cell compares a point against a 144-pixel block mean. On
  real data that alone LOWERED the rmse, which looks like an
  improvement and is not one.

So these assert against a planted answer: a plane whose elevation
depends on BOTH easting and northing, which a flip or a shift cannot
survive, offset by a known constant that the comparison must recover
exactly. No client data.
"""
import numpy as np
import pytest

tifffile = pytest.importorskip("tifffile")

from reference import grid_compare as check  # noqa: E402

FINE, COARSE = 0.25, 3.0          # the vendor's cell and ours
X0, Y0 = 1000.0, 2000.0           # fine grid's south-west cell CENTRE
ROWS, COLS = 96, 120              # 24 x 30 ft: 8 x 10 coarse cells
OFFSET = 0.5                      # the answer the comparison must find


def plane(x, y):
    """Elevation that depends on both axes, so a flip cannot hide."""
    return 0.01 * x + 0.02 * y


def write_geotiff(path, array, x0, y0, cell):
    """North-up, row 0 NORTH, tiepoint at the upper-left CORNER."""
    upper_left = (x0 - cell / 2.0, y0 + (array.shape[0] - 1) * cell
                  + cell / 2.0)
    tifffile.imwrite(
        path, np.flipud(array).astype(np.float64),
        extratags=[(33550, "d", 3, (cell, cell, 0.0), True),
                   (33922, "d", 6, (0.0, 0.0, 0.0, upper_left[0],
                                    upper_left[1], 0.0), True)])
    return path


def write_asc(path, array, x0, y0, cell, nodata=-9999.0):
    """Esri ASCII grid: corner coordinates, NORTH row written first."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"ncols {array.shape[1]}\nnrows {array.shape[0]}\n"
                     f"xllcorner {x0:.6f}\nyllcorner {y0:.6f}\n"
                     f"cellsize {cell:.6f}\nNODATA_value {nodata:g}\n")
        for row in range(array.shape[0] - 1, -1, -1):
            handle.write(" ".join("-9999" if not np.isfinite(v)
                                  else f"{v:.9f}" for v in array[row]) + "\n")
    return path


@pytest.fixture
def world(tmp_path):
    """One plane, sampled at both resolutions, ours lifted by OFFSET."""
    fx = X0 + np.arange(COLS) * FINE
    fy = Y0 + np.arange(ROWS) * FINE
    fine = plane(fx[None, :], fy[:, None])
    tif = write_geotiff(tmp_path / "theirs.tif", fine, X0, Y0, FINE)

    cx0, cy0 = X0 - FINE / 2, Y0 - FINE / 2          # coarse SW CORNER
    ccx = cx0 + (np.arange(10) + 0.5) * COARSE
    ccy = cy0 + (np.arange(8) + 0.5) * COARSE
    coarse = plane(ccx[None, :], ccy[:, None]) + OFFSET
    asc = write_asc(tmp_path / "ours.asc", coarse, cx0, cy0, COARSE)
    return tif, asc, fine, coarse


def test_an_ascii_grid_comes_back_south_row_first(world, tmp_path):
    _, asc, _, coarse = world
    grid, x0, y0, cell = check.read_asc(asc)
    assert np.allclose(grid, coarse), "the ASC rows were not flipped to y-up"
    assert (x0, y0, cell) == (X0 - FINE / 2, Y0 - FINE / 2, COARSE)


def test_a_geotiffs_tiepoint_is_a_corner_not_a_centre(world):
    tif, _, fine, _ = world
    grid, x0, y0, cell = check.read_geotiff(tif)
    assert np.allclose(grid, fine), "the GeoTIFF rows were not flipped to y-up"
    assert (x0, y0, cell) == pytest.approx((X0, Y0, FINE)), (
        "a half-cell error between the tiepoint corner and the pixel centre")


def test_the_comparison_recovers_exactly_what_was_planted(world):
    tif, asc, _, _ = world
    theirs, fx0, fy0, fcell = check.read_geotiff(tif)
    mine, x0, y0, cell = check.read_asc(asc)
    mean, count = check._block_mean(theirs, fx0, fy0, fcell, mine.shape,
                                    x0 + cell / 2, y0 + cell / 2, cell)
    assert set(np.unique(count)) == {144}, (
        f"each 3 ft cell must average 12x12 quarter-foot pixels, got "
        f"{np.unique(count)}")
    assert np.allclose(mine - mean, OFFSET, atol=1e-9), (
        "the planted offset did not come back: the grids are misaligned")


def test_a_flipped_raster_does_not_pass_unnoticed(world):
    """The check that matters: a mirror image must not look fine.

    A y-flip leaves the elevations in range and the histogram shaped
    much the same, so nothing downstream complains -- the planted plane
    is what makes it visible.
    """
    tif, asc, _, _ = world
    theirs, fx0, fy0, fcell = check.read_geotiff(tif)
    mine, x0, y0, cell = check.read_asc(asc)
    mean, _ = check._block_mean(np.flipud(theirs), fx0, fy0, fcell,
                                mine.shape, x0 + cell / 2, y0 + cell / 2,
                                cell)
    spread = float(np.nanmax(mine - mean) - np.nanmin(mine - mean))
    assert spread > 0.4, (
        f"a flipped raster produced a nearly constant difference "
        f"({spread:.3f} ft of spread): this test cannot tell a flip from a "
        f"correct comparison, so it guards nothing")


def test_a_cell_with_no_pixel_under_it_is_not_zero(world, tmp_path):
    """Empty must be NaN, or a hole reads as a disagreement the size of
    the site's whole elevation."""
    tif, asc, _, _ = world
    theirs, fx0, fy0, fcell = check.read_geotiff(tif)
    mine, x0, y0, cell = check.read_asc(asc)
    theirs[:24, :] = np.nan                      # the vendor has no data here
    mean, count = check._block_mean(theirs, fx0, fy0, fcell, mine.shape,
                                    x0 + cell / 2, y0 + cell / 2, cell)
    assert np.all(count[:2, :] == 0)
    assert np.all(np.isnan(mean[:2, :])), (
        "an empty cell came back as a number; the difference there would be "
        "the whole elevation of the site")
    assert np.allclose((mine - mean)[2:, :], OFFSET, atol=1e-9)

