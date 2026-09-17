"""Native file fixtures are assembled independently from the reader dtype."""
import struct
import numpy as np
import pytest
from pyargus.formats import trj, trajectory
from pyargus.align import attach
from pyargus.core import rotation

def make_file(path, rows=None):
    if rows is None:
        rows = [(436024721+i*.005, 100+i, 200, 400, h, 2, 3)
                for i,h in enumerate((359, 1, 3))]
    h = bytearray(1376)
    struct.pack_into('<8s4i', h, 0, b'TSCANTRJ', 20010715, 1376, len(rows), 64)
    h[24:28] = b'test'
    h[102:104] = bytes((7,3))
    struct.pack_into('<2d2i', h, 104, rows[0][0], rows[-1][0], 11, 12)
    path.write_bytes(h + b''.join(struct.pack('<7d4B2h', *r, 1,2,3,4,-1,5) for r in rows))
    return path

def test_layout_metadata_and_angles(tmp_path):
    p = make_file(tmp_path/'TEST.TRJ')
    t = trj.read_trj(p)
    assert len(t.records) == 3 and t.line_number == 12 and t.original_number == 11
    assert t.description == 'test' and t.system_id == 7 and t.quality == 3
    assert t.records['mark'][0] == -1 and t.records['quality_rp'][0] == 4
    assert t.records['heading'].tolist() == [359,1,3]
    d, xyz, mode = trajectory.load_alignment(p, None, trj_time='same', trj_confirmed=True)
    assert mode == 'same' and np.array_equal(xyz[0], t.records['x'])
    from pyargus.formats.sbet import interpolate
    angle = interpolate(d, [d['time'][0]+.0025], fields=('heading',))['heading'][0]
    assert abs(angle) < 1e-5  # heading crosses north, not south

@pytest.mark.parametrize('fault', ['magic','version','header','stride','count','truncated','trailing','nan','duplicate','bounds'])
def test_malformed_refuses(tmp_path, fault):
    p = make_file(tmp_path/'bad.trj')
    b = bytearray(p.read_bytes())
    if fault == 'magic': b[0] = 0
    elif fault in ('version','header','count','stride'):
        struct.pack_into('<i', b, dict(version=8,header=12,count=16,stride=20)[fault], 999)
    elif fault == 'truncated': b = b[:-1]
    elif fault == 'trailing': b += b'!'
    elif fault == 'nan': struct.pack_into('<d', b, 1376+8, float('nan'))
    elif fault == 'duplicate': b[1440:1448] = b[1376:1384]
    elif fault == 'bounds': struct.pack_into('<d', b, 104, 0)
    p.write_bytes(b)
    with pytest.raises(ValueError): trj.read_trj(p)

def test_explicit_conventions_and_clock_required(tmp_path):
    p = make_file(tmp_path/'a.trj')
    with pytest.raises(ValueError, match='confirmed'): trajectory.load_alignment(p, None)
    with pytest.raises(ValueError, match='time'): trajectory.read_times(p)
    with pytest.raises(ValueError, match='seconds of week'): trajectory.read_times(p, trj_time='week')
    times, mode = trajectory.read_times(p, trj_time='same')
    q, week, frac = trajectory.match_times([times[0], times[-1]+1], times, mode)
    assert week is None and frac == .5 and q[0] == times[0]

def test_native_geometry_and_correction_share_time_base(tmp_path):
    times = 436024721 + np.arange(101)*.1
    rows = [(t, (t-times[0])*20, 200, 400, 90, 2, 3) for t in times]
    p = make_file(tmp_path/'line.trj', rows)
    d, (e,n,z), mode = trajectory.load_alignment(p,None,trj_time='same',trj_confirmed=True)
    nav = np.column_stack([e,n,z])
    r = rotation.matrices(np.deg2rad(2), -np.deg2rad(3), 0.)
    body = np.tile([0., 10., -100.], (len(d),1))
    xyz = nav + body @ r.T
    pts = dict(x=xyz[:,0],y=xyz[:,1],z=xyz[:,2],gps_time=times,
               point_source_id=np.ones(len(d),dtype=int))
    a = attach.bundles_from_cloud(pts,d,e,n,z,time_mode=mode)
    assert a.gps_week is None
    np.testing.assert_allclose(a.bundles[0].body_vecs,body,atol=1e-10)
    out, skipped = attach.apply_corrections(pts,d,e,n,z,a.heading_source,
                          np.zeros(3),{1:np.array([0,0,2.])},time_mode=mode)
    assert skipped == 0
    np.testing.assert_allclose(out,xyz+[0,0,2])
    drift = {1:(times[[0,-1]],np.array([0.,2.]))}
    out, _ = attach.apply_corrections(pts,d,e,n,z,a.heading_source,
                       np.zeros(3),{},drift_by_sid=drift,time_mode=mode)
    np.testing.assert_allclose(out[:,2]-xyz[:,2],np.linspace(0,2,len(d)),atol=1e-8)
    bad = dict(pts, gps_time=times+1000)
    with pytest.raises(ValueError,match='inside'):
        attach.bundles_from_cloud(bad,d,e,n,z,time_mode=mode)

def test_cli_inspection_and_alias(tmp_path,capsys):
    from pyargus.cli import build_parser
    parser = build_parser()
    p = make_file(tmp_path/'line.trj')
    args = parser.parse_args(['trajectory-info',str(p)])
    assert args.func(args) == 0
    assert 'Line: 12' in capsys.readouterr().out
    args = parser.parse_args(['align','cloud.las','--trajectory',str(p),'--trj-time','same','--trj-confirmed'])
    assert args.sbet == str(p) and args.trj_confirmed

def test_gui_inspection(tmp_path, monkeypatch):
    # Imported inside the test on purpose: test_gui skips itself where
    # Tk is missing, so this import skips this test alone and leaves
    # the native-format tests above to run on a machine without it.
    from tests.test_gui import make_root
    from pyargus import gui
    root = make_root()
    try:
        app = gui.Application(root)
        app.sbet_path.set(str(make_file(tmp_path/'native.trj')))
        app.inspect_trajectory()
        app.runner.thread.join(5)
        assert app.runner.status == 'Finished'
        found=[]
        while not app.runner.lines.empty():
            found.append(app.runner.lines.get_nowait())
        assert any('Positions: 3' in line for line in found)
        assert '*.trj' in [pattern for _,pattern in gui.SBET_TYPES]
        assert app.trj_time.get() == 'Select TRJ time'
    finally:
        root.destroy()


def test_native_qa_cli_uses_stored_clock(tmp_path):
    import laspy
    from pyargus.cli import main
    x,y = np.meshgrid(np.arange(10.),np.arange(10.))
    las = laspy.LasData(laspy.LasHeader(point_format=6,version='1.4'))
    las.x,las.y,las.z = x.ravel(),y.ravel(),np.ones(100)
    las.classification = np.full(100,2,dtype=np.uint8)
    las.point_source_id = np.ones(100,dtype=np.uint16)
    p = make_file(tmp_path/'qa.trj')
    times = trj.read_trj(p).records['time']
    las.gps_time = np.linspace(times[0],times[-1],100)
    cloud = tmp_path/'cloud.las'; las.write(cloud)
    out = tmp_path/'report'
    assert main(['qa-report',str(cloud),'--out',str(out),'--trajectory',str(p),
                 '--trj-time','same']) == 0
    html = (out/'report.html').read_text(encoding='utf-8')
    assert 'Same stored timestamps' in html and '100.00%' in html
