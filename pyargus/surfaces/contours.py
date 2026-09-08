"""Contours from a gridded surface: marching squares, joined to lines.

Levels cut the surface sampled at cell centers; crossings interpolate
linearly along square edges, so a contour vertex satisfies its level
exactly on a locally-linear surface (test-pinned against a plane and a
cone). Squares touching a NaN cell are skipped -- contours end at the
data boundary instead of inventing terrain. Saddle squares resolve by
the cell-average rule.

Chaikin smoothing is available for drawing polish and is OFF by
default: smoothing moves vertices off the measured surface, and a
deliverable should say so before it does that.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class ContourLine:
    level: float
    xy: np.ndarray        # (N, 2), in map coordinates
    closed: bool
    is_index: bool


def contour_levels(zmin, zmax, interval):
    if interval <= 0:
        raise ValueError("interval must be positive")
    first = np.ceil(zmin / interval) * interval
    return np.arange(first, zmax + interval * 1e-9, interval)


# Case -> list of (edge_a, edge_b) segments; edges: 0 bottom, 1 right,
# 2 top, 3 left. Saddles (5, 10) are resolved at runtime.
_CASES = {
    0: [], 15: [],
    1: [(3, 0)], 14: [(3, 0)],
    2: [(0, 1)], 13: [(0, 1)],
    3: [(3, 1)], 12: [(3, 1)],
    4: [(1, 2)], 11: [(1, 2)],
    6: [(0, 2)], 9: [(0, 2)],
    7: [(3, 2)], 8: [(3, 2)],
}


def _march(grid, cx, cy, level):
    """Segments of one level: list of ((x1,y1),(x2,y2))."""
    above = grid >= level
    finite = np.isfinite(grid)
    b0 = above[:-1, :-1]
    b1 = above[1:, :-1]
    b2 = above[1:, 1:]
    b3 = above[:-1, 1:]
    ok = (finite[:-1, :-1] & finite[1:, :-1]
          & finite[1:, 1:] & finite[:-1, 1:])
    case = (b0.astype(np.uint8) + 2 * b1 + 4 * b2 + 8 * b3)
    active = np.flatnonzero(ok & (case > 0) & (case < 15))
    ii, jj = np.unravel_index(active, case.shape)

    segments = []
    for i, j in zip(ii, jj):
        v00, v10 = grid[i, j], grid[i + 1, j]
        v11, v01 = grid[i + 1, j + 1], grid[i, j + 1]
        x0, x1 = cx[i], cx[i + 1]
        y0, y1 = cy[j], cy[j + 1]

        def cross(edge):
            if edge == 0:
                a, b = v00, v10
                t = (level - a) / (b - a)
                return (x0 + t * (x1 - x0), y0)
            if edge == 1:
                a, b = v10, v11
                t = (level - a) / (b - a)
                return (x1, y0 + t * (y1 - y0))
            if edge == 2:
                a, b = v01, v11
                t = (level - a) / (b - a)
                return (x0 + t * (x1 - x0), y1)
            a, b = v00, v01
            t = (level - a) / (b - a)
            return (x0, y0 + t * (y1 - y0))

        c = int(case[i, j])
        if c in (5, 10):
            center_above = (v00 + v10 + v11 + v01) / 4.0 >= level
            if c == 5:
                pairs = [(3, 2), (0, 1)] if center_above else [(3, 0), (1, 2)]
            else:
                pairs = [(3, 0), (1, 2)] if center_above else [(3, 2), (0, 1)]
        else:
            pairs = _CASES[c]
        for ea, eb in pairs:
            segments.append((cross(ea), cross(eb)))
    return segments


def _join(segments):
    """Join undirected segments into chains; returns (xy, closed) list."""
    def key(p):
        return (round(p[0], 9), round(p[1], 9))

    links = {}
    for s, (p, q) in enumerate(segments):
        links.setdefault(key(p), []).append(s)
        links.setdefault(key(q), []).append(s)

    used = [False] * len(segments)
    chains = []
    for start in range(len(segments)):
        if used[start]:
            continue
        used[start] = True
        p, q = segments[start]
        chain = [p, q]
        for grow_end in (True, False):
            while True:
                tip = key(chain[-1] if grow_end else chain[0])
                nxt = next((s for s in links.get(tip, ()) if not used[s]),
                           None)
                if nxt is None:
                    break
                used[nxt] = True
                a, b = segments[nxt]
                point = b if key(a) == tip else a
                if grow_end:
                    chain.append(point)
                else:
                    chain.insert(0, point)
        closed = key(chain[0]) == key(chain[-1]) and len(chain) > 3
        chains.append((np.array(chain), closed))
    return chains


def contour_grid(grid, x_edges, y_edges, interval, index_every=5,
                 min_vertices=3):
    """Contours of a cell-centered grid at ``interval``; every
    ``index_every``-th level is an index contour. Returns ContourLines;
    chains shorter than ``min_vertices`` are dropped as grid noise."""
    grid = np.asarray(grid, dtype=float)
    finite = grid[np.isfinite(grid)]
    if finite.size == 0:
        raise ValueError("grid has no data to contour")
    cx = (np.asarray(x_edges)[:-1] + np.asarray(x_edges)[1:]) / 2.0
    cy = (np.asarray(y_edges)[:-1] + np.asarray(y_edges)[1:]) / 2.0
    lines = []
    for level in contour_levels(finite.min(), finite.max(), interval):
        is_index = (index_every > 0 and
                    abs(round(level / (interval * index_every))
                        * interval * index_every - level) < interval * 1e-6)
        for xy, closed in _join(_march(grid, cx, cy, float(level))):
            if xy.shape[0] < min_vertices:
                continue
            lines.append(ContourLine(level=float(level), xy=xy,
                                     closed=closed, is_index=is_index))
    return lines


def smooth_chaikin(xy, iterations=1, closed=False):
    """Corner-cutting smoothing. Moves vertices OFF the surface -- use
    for drawing polish only, and say so in the deliverable."""
    xy = np.asarray(xy, dtype=float)
    for _ in range(iterations):
        if xy.shape[0] < 3:
            return xy
        a = xy[:-1] * 0.75 + xy[1:] * 0.25
        b = xy[:-1] * 0.25 + xy[1:] * 0.75
        mid = np.empty((a.shape[0] * 2, 2))
        mid[0::2] = a
        mid[1::2] = b
        if closed:
            xy = np.vstack([mid, mid[:1]])
        else:
            xy = np.vstack([xy[:1], mid, xy[-1:]])
    return xy
