"""Independent occupancy-set checks for reporting actual overlap, not planned sidelap."""
import csv,json,sqlite3
from pathlib import Path
import numpy as np
import pytest
from pyargus import project
from pyargus.qa import coverage,report
from pyargus.large_qa import Store,write_report
from tests.test_project import scene


def sample():
    # Three strips share one cell; unequal strip areas and isolated/noise-only strips.
    return dict(x=np.array([.1,1.1,1.2,2.2,3.2,1.3,10.3,-10.1,1.4,100.]),
        y=np.full(10,.1),point_source_id=np.array([1,1,2,2,2,3,3,4,5,5]),
        classification=np.array([2,2,1,1,1,4,4,1,7,18]))


def test_asymmetric_pair_percentages_and_unique_multistrip_union(tmp_path):
    result=coverage.generate(sample(),tmp_path,cell=1.,units='metre')
    assert result['union_cells']==6 and result['multiple_strip_cells']==1
    assert result['multiple_strip_percent_of_union']==pytest.approx(100/6)
    assert result['multiplicity_cells']=={'1':5,'3':1}
    assert result['eligible_returns']==8 and result['excluded_returns']==2
    pair=next(p for p in result['pairs'] if (p['a'],p['b'])==(1,2))
    assert pair['shared_cells']==1 and pair['shared_area_square_units']==1
    assert pair['a_covered_by_b_percent']==50
    assert pair['b_covered_by_a_percent']==pytest.approx(100/3)
    assert pair['shared_over_union_percent']==25
    a,b,c,d,e=result['strips']
    assert a['neighbors']==[2,3] and a['shared_with_any_percent']==50
    assert b['shared_with_any_percent']==pytest.approx(100/3)
    assert c['shared_with_any_cells']==1
    assert d['status']=='Isolated coverage' and d['shared_with_any_percent']==0
    assert e['status']=='No eligible coverage' and e['shared_with_any_percent'] is None
    pairs=list(csv.DictReader((tmp_path/'coverage_pairs.csv').open()))
    assert len(pairs)==10 and len([p for p in pairs if int(p['shared_cells'])])==3
    cells=list(csv.DictReader((tmp_path/'coverage_cells.csv').open()))
    assert next(c for c in cells if float(c['x_min'])==1)['analysis_ids']=='1;2;3'
    page=coverage.html_section(result)
    assert 'planned flight sidelap is not inferred' in page
    assert 'Isolated coverage' in page and '% A covered by B' in page


def test_chunk_order_duplication_and_negative_tile_boundaries(tmp_path):
    x=np.array([-768.,-3.,-.001,0.,3.,768.])
    points=dict(x=np.tile(x,2),y=np.zeros(12),classification=np.ones(12,dtype=np.uint8),point_source_id=np.repeat([1,2],6))
    reference=coverage.generate(points,tmp_path/'whole',cell=3.)
    db=sqlite3.connect(tmp_path/'chunks.sqlite');coverage.create(db)
    try:
        for index in reversed(range(12)):
            for _ in range(2):
                coverage.ingest(db,points['x'][index:index+1],points['y'][index:index+1],points['classification'][index:index+1],points['point_source_id'][index:index+1],cell=3.)
        changed=coverage.write(db,tmp_path/'chunks',{1:1,2:2},cell=3.)
        for key in ('union_cells','multiple_strip_cells','multiplicity_cells','pairs'):
            assert changed[key]==reference[key]
        assert reference['union_cells']==5
        assert reference['pairs'][0]['a_covered_by_b_percent']==100
        assert reference['pairs'][0]['shared_area_square_units']==45
        assert (tmp_path/'whole/tiles/coverage_-1_0.png').exists()
        assert (tmp_path/'whole/tiles/coverage_1_0.png').exists()
        assert (tmp_path/'whole/coverage_cells.csv').read_text()==(tmp_path/'chunks/coverage_cells.csv').read_text()
    finally:db.close()


def test_no_eligible_coverage_has_null_percentages_and_no_invented_area(tmp_path):
    points=dict(x=np.array([0.,10.]),y=np.zeros(2),classification=np.array([7,18]),point_source_id=np.array([1,2]))
    result=coverage.generate(points,tmp_path)
    assert result['union_cells']==0 and result['eligible_returns']==0
    assert result['multiple_strip_percent_of_union'] is None
    assert result['pairs'][0]['a_covered_by_b_percent'] is None
    assert result['pairs'][0]['b_covered_by_a_percent'] is None
    assert result['tiles']==[] and not (tmp_path/'coverage.pgw').exists()
    assert 'percentages are not computed' in coverage.html_section(result)
    json.dumps(result,allow_nan=False)


def test_single_strip_is_coverage_without_pairwise_overlap(tmp_path):
    p=sample();p['point_source_id']=np.ones(10,dtype=np.uint16)
    result=coverage.generate(p,tmp_path)
    assert result['pairs']==[] and result['multiple_strip_percent_of_union']==0
    assert 'Only one analysis strip' in coverage.html_section(result)


def test_map_orientation_and_categorical_colors():
    grid=np.array([[0,1],[2,3]])
    image=coverage.rgba(grid)
    np.testing.assert_array_equal(image[0,0],coverage.COLORS[1])
    np.testing.assert_array_equal(image[0,1],coverage.COLORS[3])
    np.testing.assert_array_equal(image[1,0],coverage.COLORS[0])
    np.testing.assert_array_equal(image[1,1],coverage.COLORS[2])


@pytest.mark.parametrize('cell',[0.,-1.,np.nan,np.inf])
def test_invalid_cell_refuses(tmp_path,cell):
    db=sqlite3.connect(tmp_path/'test.db');coverage.create(db)
    try:
        p=sample()
        with pytest.raises(ValueError,match='cell size'):coverage.ingest(db,p['x'],p['y'],p['classification'],p['point_source_id'],cell)
    finally:db.close()


def test_cancel_removes_private_scratch(tmp_path):
    with pytest.raises(project.Cancelled):coverage.generate(sample(),tmp_path,cancel=lambda:True)
    assert not list(tmp_path.glob('.coverage-*'))
    assert not (tmp_path/'coverage.png').exists()


def test_memory_and_disk_reports_have_identical_coverage(scene,tmp_path):
    memory=project.qa(scene,tmp_path/'memory')
    disk=project.qa(__import__('dataclasses').replace(scene,max_points=1),tmp_path/'disk')
    assert memory['coverage_overlap']==disk['coverage_overlap']
    for name in ('coverage_cells.csv','coverage_pairs.csv','coverage_strips.csv','coverage.png','coverage.pgw'):
        assert (tmp_path/'memory'/name).read_bytes()==(tmp_path/'disk'/name).read_bytes()
    assert (tmp_path/'disk/coverage.prj').exists()
    page=(tmp_path/'disk/report.html').read_text(encoding='utf-8')
    assert 'Measured coverage overlap' in page and 'coverage_pairs.csv' in page
