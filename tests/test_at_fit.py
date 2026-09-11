import numpy as np
import pytest
from pyargus.at_fit import choose_model,correction_grid,evaluate_grid,predict


def test_smooth_tilt_recovered_without_fitting_noise():
    rng=np.random.default_rng(314)
    xy=rng.uniform(0,10000,(40,2))+[2400000,400000]
    delta=.1+(xy[:,0]-2400000)*.00001-(xy[:,1]-400000)*.000015
    result=choose_model(xy,delta)
    assert result['accepted']
    assert result['best']['spatial_rmse']<result['baseline_rmse']*.4
    b=result['best']; fitted=predict(xy,delta,xy,b['kind'],b['alpha'])
    assert np.sqrt(np.mean((delta-fitted)**2))<.005


def test_grid_has_same_z_only_field_and_refuses_outside_extent():
    xy=np.array([[0,0],[0,100],[100,0],[100,100]],dtype=float)
    delta=np.array([0,.1,.1,.2])
    x,y,g=correction_grid(xy,delta,'plane',1,(0,100,0,100),cell=10)
    np.testing.assert_allclose(evaluate_grid(x,y,g,[25,25],[50,50]),[.075,.075],atol=1e-12)
    with pytest.raises(ValueError): evaluate_grid(x,y,g,[101],[50])
    assert np.all(predict(xy,delta,[[1e8,1e8]],'plane')<=.2)


def test_export_preserves_every_other_dimension_and_evlr(tmp_path):
    import laspy
    from pyproj import CRS
    from pyargus.at_fit import export_cloud
    d=laspy.LasData(laspy.LasHeader(point_format=6,version='1.4'))
    d.header.add_crs(CRS.from_epsg(6553)); d.header.scales=np.array([.001,.001,.001])
    d.x=np.arange(10.); d.y=np.arange(10.); d.z=np.arange(10.)+100
    d.classification=np.arange(10,dtype='uint8'); d.gps_time=np.arange(10.)+10000
    d.point_source_id=np.arange(10,dtype='uint16')+20
    from laspy.vlrs.vlrlist import VLRList
    d.evlrs=VLRList([laspy.VLR(user_id='test',record_id=7,record_data=b'keep this metadata')])
    source=tmp_path/'input.las'; output=tmp_path/'corrected.las'; d.write(source)
    axes=np.array([0.,10.]); grid=np.full((2,2),.125)
    result=export_cloud(source,output,axes,axes,grid)
    before=laspy.read(source); after=laspy.read(output)
    for field in before.points.array.dtype.names:
        if field!='Z': np.testing.assert_array_equal(before.points.array[field],after.points.array[field])
    np.testing.assert_allclose(after.z-before.z,.125,atol=.00051)
    assert result['verified'] and after.evlrs[0].record_data_bytes()==b'keep this metadata'
    with pytest.raises(ValueError,match='new file'): export_cloud(source,output,axes,axes,grid)
