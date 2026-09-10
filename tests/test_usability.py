import numpy as np
import pytest
from pyargus.formats.breaklines import read_breaklines
from pyargus import stage_preview
from tests.test_gui import root, _FakeRunner


def test_dxf_world_coordinates_closure_and_roundtrip(tmp_path):
    import ezdxf
    from pyargus.formats.dxf import write_contours_dxf
    from pyargus.surfaces.contours import ContourLine
    path=tmp_path/'breaks.dxf'
    doc=ezdxf.new(); m=doc.modelspace()
    m.add_polyline3d([(2400000,400000,20),(2400010,400005,23)],close=True)
    m.add_lwpolyline([(0,0),(10,5)],dxfattribs={'elevation':30,'extrusion':(0,0,-1)})
    m.add_line((1,2,3),(4,5,6)); doc.saveas(path)
    lines=read_breaklines(path)
    np.testing.assert_allclose(lines[0][0],lines[0][-1])
    np.testing.assert_allclose(lines[1],[[0,0,-30],[-10,5,-30]])
    np.testing.assert_allclose(lines[2],[[1,2,3],[4,5,6]])
    write_contours_dxf(path,[ContourLine(25,np.array([[1,2],[3,4]]),False,False)])
    np.testing.assert_allclose(read_breaklines(path)[0],[[1,2,25],[3,4,25]])


@pytest.mark.parametrize('kind',['flat','curve','block','mesh'])
def test_dxf_refuses_ambiguous_geometry(tmp_path,kind):
    import ezdxf
    d=ezdxf.new(); m=d.modelspace()
    if kind=='flat': m.add_lwpolyline([(0,0),(1,1)])
    elif kind=='curve': m.add_lwpolyline([(0,0,1),(1,1,0)],format='xyb',dxfattribs={'elevation':25})
    elif kind=='block':
        d.blocks.new('B'); m.add_blockref('B',(0,0))
    else: m.add_polyface()
    p=tmp_path/'bad.dxf'; d.saveas(p)
    with pytest.raises(ValueError): read_breaklines(p)


def test_previews_show_north_up_classes_and_contours():
    from pyargus.surfaces.contours import ContourLine
    # North point appears above south; same XY chooses highest Z class.
    p=stage_preview.classification(np.array([0,1,0,0]),np.array([0,1,0,0]),np.array([0,1,2,3]),np.array([1,2,5,6]))
    assert p.shape==(850,1100,4)
    np.testing.assert_array_equal(p[810,30,:3],stage_preview.CLASS_STYLES[6][1])
    lines=[ContourLine(1,np.array([[0,0],[1,1]]),False,True)]
    c=stage_preview.contours(lines)
    assert np.any(np.all(c[:,:,:3]==[255,187,82],axis=2))


def test_classify_and_contour_jobs_publish_new_previews(tmp_path,root):
    import laspy
    import ezdxf
    from pyargus.gui import Application
    x,y=np.meshgrid(np.arange(0.,24),np.arange(0.,24))
    x,y=x.ravel(),y.ravel(); z=x*.3+y*.2
    d=laspy.LasData(laspy.LasHeader(point_format=3,version='1.2'))
    d.x=x; d.y=y; d.z=z; d.return_number=np.ones(len(x),dtype='uint8'); d.number_of_returns=np.ones(len(x),dtype='uint8')
    source=tmp_path/'input.las'; d.write(source)
    app=Application(root); app.cloud_path.set(str(source))
    classify=app.stages[1]; classified=tmp_path/'classified.las'; classify.out_path.set(str(classified))
    run=_FakeRunner(); classify.prepare()(run)
    assert classified.exists() and run.report is not None
    contours=app.stages[3]; contours.cloud_override.set(str(classified)); contours.out_path.set(str(tmp_path/'contours.dxf'))
    doc=ezdxf.new(); doc.modelspace().add_polyline3d([(0,0,0),(23,23,11.5)])
    bp=tmp_path/'survey.dxf'; doc.saveas(bp); contours.breaklines.set(str(bp))
    previous=run.report; contours.prepare()(run)
    assert (tmp_path/'contours.dxf').exists() and run.report is not previous
    assert not any('preview unavailable' in text for text in run.logged)
