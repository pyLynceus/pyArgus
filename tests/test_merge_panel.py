"""What a 129-agent review panel found in the first version of merge.

Kept in their own file because they share a provenance rather than a
subject: each one pins a defect that shipped in commit a357a0e, survived
three independent refuters, and was then reproduced by hand against the
real code before anything was changed. Every test here failed against
that version.

The through-line is that a merge is dangerous precisely where it looks
harmless. Each of these produced a file that opened cleanly in any
viewer and was wrong: two flight lines silently reduced to one strip, a
short delivery reported as complete, two GPS time bases under one
declared type, a float dimension quietly truncated to an integer one,
and two coordinate systems joined because the library that reads the
projection records was an optional install.
"""

import struct

import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from tests.test_merge import WKT, make  # noqa: E402
from pyargus.formats import las as las_mod  # noqa: E402
from pyargus.formats import merge as merge_mod  # noqa: E402


def test_a_collision_between_two_of_three_clouds_still_refuses(tmp_path):
    """The refusal read the intersection of ALL inputs.

    Two lines numbering their points 1 and a third numbering its 3 have
    an empty intersection, so the check saw no collision, and the two
    real strips became one the moment they were joined. Strip QA then
    compares a strip with itself and reports a perfect result. A
    delivery is three or more lines far more often than two.
    """
    a = make(tmp_path / "a.las", n=50, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=50, psid=1, seed=2)      # collides with a
    c = make(tmp_path / "c.las", n=50, psid=3, seed=3)      # innocent
    with pytest.raises(ValueError, match="point_source_id"):
        merge_mod.merge_clouds([a, b, c], tmp_path / "m.las",
                               log=lambda *_: None)
    assert not (tmp_path / "m.las").exists()

    merge_mod.merge_clouds([a, b, c], tmp_path / "ok.las", psid_from_file=True,
                           log=lambda *_: None)
    ids = las_mod.read_points(tmp_path / "ok.las",
                              fields=("point_source_id",))["point_source_id"]
    assert sorted(int(v) for v in np.unique(ids)) == [1, 2, 3]


def test_clouds_whose_crs_cannot_be_read_are_not_assumed_to_agree(
        tmp_path, monkeypatch):
    """"Could not parse" is not the same as "declares none".

    pyproj is an optional extra. Without it laspy's parse_crs raises,
    cloud_info swallows the exception and every file reports None, so
    None against None read as "these agree" and two coordinate systems
    merged into one cloud carrying the first file's projection record.
    With --reframe the offset refusal is skipped as well, and --reframe
    is exactly the flag a real two-zone merge would be run with.
    """
    pyproj = pytest.importorskip("pyproj")
    a = make(tmp_path / "a.las", n=40, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=40, psid=2, seed=2, crs=False)
    elsewhere = WKT.replace('"false_easting",2296583.333',
                            '"false_easting",700000.0')
    data = laspy.read(str(b))
    data.header.add_crs(pyproj.CRS.from_wkt(elsewhere))
    data.write(str(b))

    real = las_mod.cloud_info

    def blind(path, *args, **kwargs):
        info = dict(real(path, *args, **kwargs))
        info["crs"] = None                       # as if pyproj were absent
        return info

    monkeypatch.setattr(las_mod, "cloud_info", blind)
    with pytest.raises(ValueError, match="(?i)coordinate system|crs"):
        merge_mod.merge_clouds([a, b], tmp_path / "m.las", reframe=True,
                               log=lambda *_: None)
    assert not (tmp_path / "m.las").exists()


def test_two_clouds_that_declare_no_crs_at_all_still_merge(tmp_path):
    """The other half of that rule: absent is not a disagreement.

    Refusing whenever the CRS is unknown would be the easy fix and the
    wrong one -- plenty of real clouds declare no projection, and they
    must still join.
    """
    a = make(tmp_path / "a.las", n=40, psid=1, seed=1, crs=False)
    b = make(tmp_path / "b.las", n=40, psid=2, seed=2, crs=False)
    result = merge_mod.merge_clouds([a, b], tmp_path / "m.las",
                                    log=lambda *_: None)
    assert result["points"] == 80


def test_a_header_claiming_more_points_than_the_file_holds_refuses(tmp_path):
    """noise-cut checks this and merge did not.

    A truncated cloud, or one whose header went stale, merged short and
    exited 0. The delivery was missing points and nothing said so.
    """
    a = make(tmp_path / "a.las", n=100, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=100, psid=2, seed=2)
    raw = bytearray((tmp_path / "b.las").read_bytes())
    struct.pack_into("<Q", raw, 247, 400)         # LAS 1.4 point count
    (tmp_path / "b.las").write_bytes(bytes(raw))

    with pytest.raises(ValueError, match="(?i)header|count"):
        merge_mod.merge_clouds([a, b], tmp_path / "m.las",
                               log=lambda *_: None)
    assert not (tmp_path / "m.las").exists()


def test_two_gps_time_conventions_do_not_merge(tmp_path):
    """GPS week time and adjusted standard GPS time differ by ~1e9 s.

    Joining them under one declared type gives a cloud whose gps_time
    means two different things, which every trajectory match, drift
    correction and time-based check in this suite then reads as one.
    """
    a = make(tmp_path / "a.las", n=40, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=40, psid=2, seed=2)
    for path, kind in ((a, 1), (b, 0)):
        data = laspy.read(str(path))
        data.header.global_encoding.gps_time_type = laspy.header.GpsTimeType(
            kind)
        data.write(str(path))
    with pytest.raises(ValueError, match="(?i)gps"):
        merge_mod.merge_clouds([a, b], tmp_path / "m.las",
                               log=lambda *_: None)
    assert not (tmp_path / "m.las").exists()


def _with_extra(path, dtype, psid, seed, origin, value):
    """A cloud with one extra dimension of a chosen type and value."""
    header = laspy.LasHeader(version="1.4", point_format=7)
    header.scales = np.array([0.001] * 3)
    header.offsets = np.array(origin, dtype=float)
    header.add_extra_dim(laspy.ExtraBytesParams(name="Amplitude", type=dtype))
    data = laspy.LasData(header)
    rng = np.random.default_rng(seed)
    data.x = origin[0] + rng.uniform(0, 100, 40)
    data.y = origin[1] + rng.uniform(0, 100, 40)
    data.z = origin[2] + rng.uniform(0, 10, 40)
    data.point_source_id = np.full(40, psid, dtype=np.uint16)
    data["Amplitude"] = np.full(40, value, dtype=dtype)
    data.write(str(path))
    return path


def test_an_extra_dimension_of_the_same_name_but_another_type_refuses(
        tmp_path):
    """Extra dimensions were compared by NAME only.

    Under --reframe the records are rebuilt against the first file's
    header, so a float32 Amplitude written into a uint8 slot is cast by
    numpy without a word. Measured on this exact pair before the check
    existed: 12.75 arrived as 12.
    """
    a = _with_extra(tmp_path / "a.las", np.uint8, 1, 1,
                    (2_600_000.0, 1_200_000.0, 1_100.0), 200)
    b = _with_extra(tmp_path / "b.las", np.float32, 2, 2,
                    (2_600_500.0, 1_200_500.0, 1_100.0), 12.75)
    with pytest.raises(ValueError, match="(?i)extra dimension"):
        merge_mod.merge_clouds([a, b], tmp_path / "m.las", reframe=True,
                               log=lambda *_: None)
    assert not (tmp_path / "m.las").exists()


def test_the_same_extra_dimension_type_on_both_sides_is_fine(tmp_path):
    a = _with_extra(tmp_path / "a.las", np.float32, 1, 1,
                    (2_600_000.0, 1_200_000.0, 1_100.0), 12.75)
    b = _with_extra(tmp_path / "b.las", np.float32, 2, 2,
                    (2_600_500.0, 1_200_500.0, 1_100.0), 3.5)
    merge_mod.merge_clouds([a, b], tmp_path / "m.las", reframe=True,
                           log=lambda *_: None)
    values = np.asarray(laspy.read(str(tmp_path / "m.las"))["Amplitude"])
    assert np.allclose(np.unique(values[:40]), 12.75)
    assert np.allclose(np.unique(values[40:]), 3.5)


def test_force_replaces_an_existing_output_and_nothing_else_does(tmp_path):
    """The CLI declared --force, said "pass --force to replace it", and
    merge_clouds did not take the argument."""
    a = make(tmp_path / "a.las", n=40, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=40, psid=2, seed=2)
    out = tmp_path / "m.las"
    merge_mod.merge_clouds([a, b], out, log=lambda *_: None)
    assert las_mod.cloud_info(out)["point_count"] == 80

    with pytest.raises(FileExistsError):
        merge_mod.merge_clouds([a, b], out, log=lambda *_: None)

    c = make(tmp_path / "c.las", n=90, psid=3, seed=3)
    merge_mod.merge_clouds([a, c], out, force=True, log=lambda *_: None)
    assert las_mod.cloud_info(out)["point_count"] == 130


def test_an_empty_cloud_does_not_drag_the_frame_to_the_origin(tmp_path):
    """A zero-point input has no bounds to contribute.

    Its header minima are whatever the writer left there, and taking
    the union with them pulled the offset toward (0, 0, 0), which puts
    state plane coordinates billions of scale units away and produces a
    refusal blaming the extent instead of the empty file.
    """
    a = make(tmp_path / "a.las", n=40, psid=1, seed=1)
    # a different offset is what sends this down the reframe path, which
    # is where the bounds of an empty file get used
    empty = make(tmp_path / "empty.las", n=0, psid=2, seed=2,
                 offsets=(2_600_100.0, 1_200_100.0, 1_100.0))
    with pytest.raises(ValueError) as caught:
        merge_mod.merge_clouds([a, empty], tmp_path / "m.las", reframe=True,
                               log=lambda *_: None)
    said = str(caught.value)
    assert "empty.las" in said and "no points" in said, (
        f"the refusal should name the empty cloud: {said}")
    assert "32-bit" not in said and "extent" not in said, (
        f"the refusal blamed the extent, which is the symptom rather than "
        f"the cause: {said}")
