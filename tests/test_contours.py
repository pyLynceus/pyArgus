import numpy as np
import pytest

from pyargus.surfaces import contours


def plane_grid(nx=60, ny=40, cell=1.0, slope=0.1):
    x_edges = np.arange(nx + 1) * cell
    y_edges = np.arange(ny + 1) * cell
    cx = (x_edges[:-1] + cell / 2.0)[:, None]
    grid = np.broadcast_to(slope * cx, (nx, ny)).copy()
    return grid, x_edges, y_edges


def cone_grid(n=80, cell=1.0):
    x_edges = np.arange(n + 1) * cell
    y_edges = np.arange(n + 1) * cell
    cx = (x_edges[:-1] + cell / 2.0)[:, None]
    cy = (y_edges[:-1] + cell / 2.0)[None, :]
    r = np.hypot(cx - 40.0, cy - 40.0)
    return 100.0 - 0.1 * r, x_edges, y_edges


def test_levels():
    assert np.allclose(contours.contour_levels(0.4, 2.2, 1.0), [1.0, 2.0])
    assert np.allclose(contours.contour_levels(-1.5, 1.5, 0.5),
                       [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5])
    with pytest.raises(ValueError):
        contours.contour_levels(0, 1, 0)


def test_plane_contours_are_exact_straight_lines():
    grid, xe, ye = plane_grid()
    lines = contours.contour_grid(grid, xe, ye, interval=1.0, index_every=5)
    assert lines
    for line in lines:
        # every vertex sits exactly on its level: x = level / slope
        assert np.abs(0.1 * line.xy[:, 0] - line.level).max() < 1e-9
        assert not line.closed
    # one chain per level, not confetti
    levels = [line.level for line in lines]
    assert len(levels) == len(set(levels))
    # index flag: with interval 1 and index_every 5, levels 5.0 only
    for line in lines:
        assert line.is_index == (abs(line.level % 5.0) < 1e-9)


def test_cone_contours_are_closed_circles():
    grid, xe, ye = cone_grid()
    lines = contours.contour_grid(grid, xe, ye, interval=1.0)
    ring = [l for l in lines if abs(l.level - 98.0) < 1e-9]
    assert len(ring) == 1 and ring[0].closed
    radius = np.hypot(ring[0].xy[:, 0] - 40.0, ring[0].xy[:, 1] - 40.0)
    want = (100.0 - 98.0) / 0.1
    assert np.abs(radius - want).max() < 0.75  # sub-cell on a curved surface


def test_contours_stop_at_nodata():
    grid, xe, ye = plane_grid()
    grid = grid.copy()
    grid[20:30, 10:25] = np.nan
    lines = contours.contour_grid(grid, xe, ye, interval=1.0)
    for line in lines:
        inside = ((line.xy[:, 0] > 20.5) & (line.xy[:, 0] < 29.5)
                  & (line.xy[:, 1] > 10.5) & (line.xy[:, 1] < 24.5))
        assert not inside.any()


def test_all_nan_refuses():
    with pytest.raises(ValueError, match="no data"):
        contours.contour_grid(np.full((4, 4), np.nan),
                              np.arange(5.0), np.arange(5.0), 1.0)


def test_chaikin_keeps_endpoints_and_marks_its_cost():
    xy = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]])
    smooth = contours.smooth_chaikin(xy, iterations=2)
    assert np.allclose(smooth[0], xy[0]) and np.allclose(smooth[-1], xy[-1])
    assert smooth.shape[0] > xy.shape[0]
    # the corner was cut: the peak no longer reaches y = 1
    assert smooth[:, 1].max() < 1.0


def test_saddle_cases_follow_the_cell_average_rule():
    """A 2x2 grid is one marching square; diagonal-high corners make
    case 5, and the cell average decides which corners connect. The
    review panel proved this branch was unpinned: a swapped saddle
    table shipped green before this test."""
    # case 5: v00 and v11 above. Level 0.5 -> average 0.5 >= level:
    # the high corners join; crossings pair (left,top) and (bottom,right).
    segs = contours._march(np.array([[1.0, 0.0], [0.0, 1.0]]),
                           np.array([0.5, 1.5]), np.array([0.5, 1.5]), 0.5)
    assert len(segs) == 2
    pairs = [{("L" if a[0] == 0.5 and a[1] not in (0.5, 1.5) else
               "B" if a[1] == 0.5 else "T" if a[1] == 1.5 else "R")
              for a in seg} for seg in segs]
    assert {frozenset(e) for e in pairs} == {frozenset("LT"), frozenset("BR")}
    # level 0.6 -> average 0.5 < level: the low corners join instead.
    segs = contours._march(np.array([[1.0, 0.0], [0.0, 1.0]]),
                           np.array([0.5, 1.5]), np.array([0.5, 1.5]), 0.6)
    assert len(segs) == 2
    pairs = [{("L" if a[0] == 0.5 and a[1] not in (0.5, 1.5) else
               "B" if a[1] == 0.5 else "T" if a[1] == 1.5 else "R")
              for a in seg} for seg in segs]
    assert {frozenset(e) for e in pairs} == {frozenset("LB"), frozenset("RT")}


def test_saddle_case_10_mirrors_case_5():
    xe = ye = np.array([0.5, 1.5])
    # v10 and v01 above: case 10. Level 0.5, average 0.5 >= level.
    segs = contours._march(np.array([[0.0, 1.0], [1.0, 0.0]]),
                           xe, ye, 0.5)
    assert len(segs) == 2
    pairs = [{("L" if a[0] == 0.5 and a[1] not in (0.5, 1.5) else
               "B" if a[1] == 0.5 else "T" if a[1] == 1.5 else "R")
              for a in seg} for seg in segs]
    assert {frozenset(e) for e in pairs} == {frozenset("LB"), frozenset("RT")}
    # level 0.6: average below -> the other diagonal.
    segs = contours._march(np.array([[0.0, 1.0], [1.0, 0.0]]),
                           xe, ye, 0.6)
    pairs = [{("L" if a[0] == 0.5 and a[1] not in (0.5, 1.5) else
               "B" if a[1] == 0.5 else "T" if a[1] == 1.5 else "R")
              for a in seg} for seg in segs]
    assert {frozenset(e) for e in pairs} == {frozenset("LT"), frozenset("BR")}


def test_chaikin_closed_ring_keeps_the_ring_and_cuts_every_corner():
    ring = np.array([[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0],
                     [0.0, 0.0]])
    smooth = contours.smooth_chaikin(ring, iterations=1, closed=True)
    assert np.allclose(smooth[0], smooth[-1])       # still a ring
    assert smooth.shape[0] > ring.shape[0]
    # EVERY corner is cut, the start corner included: no vertex of the
    # smoothed ring coincides with any original corner
    for corner in ring[:-1]:
        assert np.abs(smooth - corner).sum(axis=1).min() > 0.9
    # and the ring stays inside the original square
    assert smooth.min() >= 0.0 and smooth.max() <= 4.0
