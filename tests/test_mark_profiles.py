"""Telling a surface from a wall face at a control mark.

Written after getting it wrong on real data. Asked what the cloud holds
at a control mark whose published elevation stood several feet above
the ground beneath it, the first version of this check counted the points
within half a foot of that elevation, found a few dozen, and concluded
the mark sat on a structure. The surveyor said it was mis-recorded, and
was right: the histogram there held a similar few dozen points in EVERY
one-foot band up the height of a sound wall, which is what a vertical
face returns. The count was not a surface, it was the slice of a face
that happened to fall in the band being asked about.

A count at one elevation is meaningless without its neighbourhood. The
three scenes below are the three answers a mark can have, and the
middle one -- the wall -- is the one a naive count gets wrong.
"""

import numpy as np
import pytest

from reference import mark_profile as sections

# invented elevations: ground, a wall face above it, the wall's top, and
# a mark claimed a foot below that top
GROUND = 100.0
WALL_TOP = 110.0
ASKED = 109.0           # where the mark claims to be: on the face, not the top


def scene(rng, *, wall=False, top=False):
    """A patch of ground, optionally with a wall face and/or its top."""
    parts = [rng.normal(GROUND, 0.08, 1300)]
    if wall:
        # a vertical face returns points at every elevation it spans
        parts.append(rng.uniform(102.0, WALL_TOP, 330))
    if top:
        parts.append(rng.normal(WALL_TOP, 0.05, 290))
    return np.concatenate(parts)


@pytest.fixture
def rng():
    return np.random.default_rng(20260923)


def test_a_mark_on_the_ground_reads_as_ground(rng):
    elevations = scene(rng)
    assert sections._sits_on(elevations, GROUND, GROUND) == "ground"


def test_a_wall_face_is_not_a_surface_at_every_height_you_ask_about(rng):
    """The mis-recorded mark's case, and the reason this file exists."""
    elevations = scene(rng, wall=True, top=True)
    at_asked = int(np.count_nonzero(np.abs(elevations - ASKED) <= 0.5))
    assert at_asked > 5, (
        f"the fixture must reproduce the trap -- a naive count finds "
        f"points at the asked elevation ({at_asked}); if it does not, this "
        f"test cannot catch the mistake it is named for")
    assert sections._standout(elevations, ASKED) < 3.0
    assert sections._sits_on(elevations, ASKED, GROUND) == (
        "nothing that stands out at that elevation")


def test_the_top_of_the_same_wall_is_a_surface(rng):
    """The check must still SEE a real structure, not just reject walls."""
    elevations = scene(rng, wall=True, top=True)
    assert sections._standout(elevations, WALL_TOP) >= 3.0
    assert sections._sits_on(elevations, WALL_TOP, GROUND) == (
        "a flat surface above the ground")


def test_an_elevation_with_nothing_there_reads_as_nothing(rng):
    elevations = scene(rng)                     # bare ground, no wall
    assert sections._sits_on(elevations, 125.0, GROUND) == (
        "nothing that stands out at that elevation")


def test_an_empty_neighbourhood_says_so(rng):
    assert sections._sits_on(np.array([]), GROUND, None) == (
        "nothing in the cloud")


def test_the_measure_is_a_ratio_not_a_count(rng):
    """Ten times the points must not change the verdict.

    The failure being pinned is a threshold on an absolute count, which
    moves with density: a denser flight turns the same wall into a
    'structure' at every elevation. Scaling the whole scene must leave
    both answers where they were.
    """
    sparse = scene(rng, wall=True, top=True)
    dense = np.concatenate([scene(np.random.default_rng(seed), wall=True,
                                  top=True) for seed in range(10)])
    assert dense.size > 9 * sparse.size
    for elevations in (sparse, dense):
        assert sections._sits_on(elevations, ASKED, GROUND) == (
            "nothing that stands out at that elevation")
        assert sections._sits_on(elevations, WALL_TOP, GROUND) == (
            "a flat surface above the ground")
