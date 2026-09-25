"""Geometry for interactive cross-section navigation; distances use map units."""
import numpy as np
from pyargus.sections import section_coordinates


def stepped_corridor(start, end, width, distance, direction):
    """Translate perpendicular to A->B: +1 left, -1 right, without rotating."""
    section_coordinates([], [], start, end, width)
    if not np.isfinite(distance) or distance <= 0:
        raise ValueError("Step distance must be finite and greater than zero (map units).")
    if direction not in (-1, 1):
        raise ValueError("Step direction must be left (+1) or right (-1).")
    a, b = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    delta = b - a
    length = np.linalg.norm(delta)
    if not np.isfinite(length):
        raise ValueError("Section length must be finite.")
    shift = np.array([-delta[1], delta[0]]) / length * distance * direction
    with np.errstate(over="ignore", invalid="ignore"):
        moved_a, moved_b = a + shift, b + shift
    section_coordinates([], [], moved_a, moved_b, width)
    if np.array_equal(moved_a, a) or np.array_equal(moved_b, b):
        raise ValueError("Step distance is too small for these coordinates.")
    return moved_a, moved_b
