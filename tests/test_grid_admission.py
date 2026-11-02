"""Reject pathological extents before a raster or even its edges are allocated."""
import numpy as np
import pytest
from pyargus.core import gridding
from pyargus.classify import tiles
from pyargus.surfaces.dtm import dtm_grid


@pytest.mark.parametrize('operation', ['grid', 'tiles', 'terrain'])
def test_stray_xy_refused_before_edge_allocation(monkeypatch, operation):
    x = np.array([0., 2_350_000.]); y = np.array([0., 1_300_000.])
    def allocated(*args, **kwargs):
        raise AssertionError('edges allocated before admission')
    monkeypatch.setattr(gridding.np, 'arange', allocated)
    with pytest.raises(ValueError, match='XY extent.*safety limit'):
        if operation == 'grid':gridding.grid_edges(x, y, 3.)
        elif operation == 'tiles':tiles.global_edges([0., 0.], [x[-1], y[-1]], 3.)
        else:dtm_grid(x, y, np.array([100., 100.]), 3.)


@pytest.mark.parametrize('cell', [0., -1., np.nan, np.inf])
def test_invalid_cell_refused(cell):
    with pytest.raises(ValueError, match='positive and finite'):
        gridding.grid_edges(np.array([0., 1.]), np.array([0., 1.]), cell)


def test_grid_at_limit_and_single_point_keep_existing_alignment(monkeypatch):
    monkeypatch.setattr(gridding, 'MAX_GRID_CELLS', 4)
    a, b = gridding.grid_edges(np.array([-.25, 1.]), np.array([-.25, 1.]), 1.)
    np.testing.assert_array_equal(a, [-1., 0., 1.])
    np.testing.assert_array_equal(b, [-1., 0., 1.])
    a, b = gridding.grid_edges(np.array([3.]), np.array([5.]), 1.)
    np.testing.assert_array_equal(a, [3., 4.])
    np.testing.assert_array_equal(b, [5., 6.])


@pytest.mark.parametrize('workers', [1,2])
def test_global_rasters_obey_memory_admission_in_serial_and_parallel(monkeypatch, workers):
    def allocated(*args, **kwargs):raise AssertionError('raster allocated before memory admission')
    monkeypatch.setattr(tiles.np, 'full', allocated)
    def read(*args):raise AssertionError('source read before memory admission')
    with pytest.raises(ValueError, match='Global ground rasters alone'):
        tiles.tiled_surface(read,[0.,0.],[100.,100.],cell=1.,window=2.,
                            memory_mb=.001,workers=workers)


@pytest.mark.parametrize('x', [[], [0.,float('nan')], [0.,float('inf')], [float('-inf'),0.]])
def test_empty_or_nonfinite_coordinates_refuse(x):
    with pytest.raises(ValueError, match='coordinates must be nonempty and finite'):
        gridding.grid_edges(np.asarray(x),np.array([0.,1.]),1.)
