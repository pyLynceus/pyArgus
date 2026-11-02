"""Export descriptors must not depend on chunk size or laspy's extrema update."""
from copy import deepcopy
import numpy as np
import pytest
import laspy
from pyargus.formats import las
from pyargus.classify import job


def source_cloud(path, point_format=7):
    header = laspy.LasHeader(point_format=point_format, version='1.4')
    header.scales = [.001, .001, .001]
    header.add_extra_dim(laspy.ExtraBytesParams(name='Amplitude', type=np.float32))
    cloud = laspy.LasData(header)
    x, y = np.meshgrid(np.arange(8.), np.arange(8.))
    cloud.x = x.ravel(); cloud.y = y.ravel(); cloud.z = np.full(x.size, 100.)
    cloud.return_number = cloud.number_of_returns = np.ones(x.size, dtype=np.uint8)
    cloud.classification = np.ones(x.size, dtype=np.uint8)
    cloud['Amplitude'] = np.arange(x.size, dtype=np.float32) / 3
    # An independent one-record writer avoids laspy's multi-point extrema bug
    # when constructing the source fixture. Never use the helper under test.
    with laspy.open(path, mode='w', header=header) as writer:
        for i in range(len(cloud.points)):
            writer.write_points(cloud.points[i:i+1])
    return laspy.read(path)


@pytest.mark.parametrize('suffix', ['.las', '.laz'])
@pytest.mark.parametrize('mode', ['stream', 'whole', 'classify_whole', 'classify_tiled'])
def test_unchanged_extra_dimensions_keep_exact_descriptors(tmp_path, suffix, mode):
    src, dst = tmp_path/'source.las', tmp_path/('result'+suffix)
    original = source_cloud(src)
    descriptors = las.extra_bytes_metadata(original.header)
    if mode == 'stream':
        las.stream_update(src, dst, lambda pts, start: {'z': pts['z']+.25}, chunk_size=7)
    elif mode == 'whole':
        original.z = np.asarray(original.z)+.25
        las.write_preserving(original, dst)
    else:
        function = job.classify_ground_whole if mode.endswith('whole') else job.classify_ground_tiled
        function(src, dst, cell=1., window=2., threshold=.5, log=lambda _:None)
    result = laspy.read(dst)
    assert las.extra_bytes_metadata(result.header) == descriptors
    np.testing.assert_array_equal(result['Amplitude'], original['Amplitude'])
    np.testing.assert_array_equal(result.X, original.X)
    assert result.header.are_points_compressed == (suffix == '.laz')
    assert len(result.points) == 64


def test_preservation_verifier_refuses_a_changed_descriptor(tmp_path):
    original = source_cloud(tmp_path/'source.las')
    changed = deepcopy(original.header)
    descriptor = next(v for v in changed.vlrs if v.record_id == 4)
    descriptor.extra_bytes_structs[0].description = b'changed'
    with pytest.raises(ValueError, match='ExtraBytes'):
        las.assert_extra_bytes_preserved(original.header, changed)



def test_failed_stream_publications_never_overwrite_an_earlier_recovery_copy(tmp_path, monkeypatch):
    from pyargus import publication
    src, dst = tmp_path/'source.las', tmp_path/'result.laz'
    source_cloud(src)
    monkeypatch.setattr(publication, 'RETRY_DELAYS', (0.,))
    def locked(*args):raise PermissionError('target lock')
    monkeypatch.setattr(publication.os, 'replace', locked)
    recovered = []
    for dz in (.25,.5):
        with pytest.raises(publication.PublicationError) as caught:
            las.stream_update(src,dst,lambda pts,start:{'z':pts['z']+dz})
        recovered.append(caught.value.recovery_path)
    assert recovered[0] != recovered[1]
    for path,dz in zip(recovered,(.25,.5)):
        result = laspy.read(path)
        np.testing.assert_allclose(result.z,100.+dz)
        assert result.header.are_points_compressed
    assert not dst.exists()



@pytest.mark.parametrize('suffix', ['.las','.laz'])
def test_extra_descriptors_survive_conversion_from_no_rgb_format(tmp_path, suffix):
    src,dst=tmp_path/'source.las',tmp_path/('colored'+suffix)
    original=source_cloud(src,point_format=6)
    def paint(points,start):return dict(red=np.full(len(points['x']),1234,dtype=np.uint16))
    las.stream_update(src,dst,paint,fields=('x',),point_format=7,chunk_size=7)
    result=laspy.read(dst)
    las.assert_extra_bytes_preserved(original.header,result.header)
    np.testing.assert_array_equal(result['Amplitude'],original['Amplitude'])
    assert result.header.point_format.id==7
