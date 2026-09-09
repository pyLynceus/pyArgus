import numpy as np
from pyargus.gui import preview_view
from tests.test_gui import root, application


def test_view_rotation_and_pan_preserve_source():
    image=np.zeros((5,5,4),dtype=np.uint8)
    image[2,3]=[255,100,0,255]
    original=image.copy()
    assert np.array_equal(preview_view(image,5,5),image)
    turned=preview_view(image,5,5,angle=90)
    assert turned[3,2,0]==255
    moved=preview_view(image,5,5,pan=(-1,0))
    assert moved[2,2,0]==255
    assert np.array_equal(image,original)
    assert preview_view(image,20,10,zoom=32).shape==(10,20,4)


def test_controls_reset(application):
    application._zoom_view(2)
    application._rotate_view(15)
    assert application._view_zoom==2
    assert application._view_angle==15
    application._view_pan=[5,6]
    application._reset_view()
    assert application._view_zoom==1 and application._view_angle==0
    assert application._view_pan==[0,0]
