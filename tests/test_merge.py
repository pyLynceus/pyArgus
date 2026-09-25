"""Merging clouds: a concatenation, or a refusal.

`dtm` and `contours` take one cloud, and a delivery arrives as one
file per flight line -- so producing a site surface means joining them
first. The join is the dangerous part: two files whose scales, offsets
or extra dimensions differ do not describe points in the same terms,
and writing one's records under the other's header reinterprets bytes
without anything looking wrong afterwards. So every one of those is a
refusal, checked before a byte is written, and what the command does
when it does write is an exact concatenation.

Point source ids are the other trap. Strip-to-strip QA reads them, so
two files that both number their points 1 silently become one strip
the moment they are joined.
"""

import json
from pathlib import Path

import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from pyargus.formats import las as las_mod  # noqa: E402
from pyargus.formats import merge as merge_mod  # noqa: E402

WKT = ('COMPD_CS["NAD83(2011) / Georgia West (ftUS) + NAVD88",'
       'PROJCS["NAD83(2011) / Georgia West (ftUS)",GEOGCS["NAD83(2011)",'
       'DATUM["D",SPHEROID["GRS 1980",6378137,298.257222101]],'
       'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
       'PROJECTION["Transverse_Mercator"],'
       'PARAMETER["latitude_of_origin",30],'
       'PARAMETER["central_meridian",-84.1666666666667],'
       'PARAMETER["scale_factor",0.9999],'
       'PARAMETER["false_easting",2296583.333],'
       'PARAMETER["false_northing",0],'
       'UNIT["US survey foot",0.304800609601219]],'
       'VERT_CS["NAVD88 height (ftUS)",VERT_DATUM["NAVD88",2005],'
       'UNIT["US survey foot",0.304800609601219]]]')


ORIGIN = (2_600_000.0, 1_200_000.0, 1_100.0)   # state plane needs an offset


def make(path, n=400, psid=1, seed=0, point_format=7, scales=0.001,
         offsets=None, extra=("Amplitude", "Reflectance"), crs=True,
         version="1.4", classification=None, origin=ORIGIN):
    """A cloud shaped like the vendor's: pf7, extra bytes, a real CRS."""
    rng = np.random.default_rng(seed)
    header = laspy.LasHeader(version=version, point_format=point_format)
    header.scales = np.array([scales] * 3)
    header.offsets = np.array(origin if offsets is None else offsets,
                              dtype=float)
    for name in extra:
        header.add_extra_dim(laspy.ExtraBytesParams(name=name,
                                                    type=np.float32))
    if crs:
        header.add_crs(__import__("pyproj").CRS.from_wkt(WKT))
    data = laspy.LasData(header)
    data.x = origin[0] + rng.uniform(0, 500, n)
    data.y = origin[1] + rng.uniform(0, 500, n)
    data.z = origin[2] + rng.uniform(0, 30, n)
    data.intensity = rng.integers(0, 4000, n).astype(np.uint16)
    data.gps_time = 1000.0 + np.arange(n) * 1e-3
    data.return_number = np.ones(n, dtype=np.uint8)
    data.number_of_returns = np.ones(n, dtype=np.uint8)
    data.point_source_id = np.full(n, psid, dtype=np.uint16)
    data.classification = (np.full(n, 2, dtype=np.uint8)
                           if classification is None else classification)
    for i, name in enumerate(extra):
        data[name] = (rng.uniform(0, 1, n) + i).astype(np.float32)
    data.write(str(path))
    return path


FIELDS = ("x", "y", "z", "intensity", "gps_time", "return_number",
          "number_of_returns", "point_source_id", "classification")


def test_the_merge_is_the_concatenation(tmp_path):
    a = make(tmp_path / "a.las", n=400, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=250, psid=2, seed=2)
    out = tmp_path / "merged.las"
    result = merge_mod.merge_clouds([a, b], out, log=lambda *_: None)

    pa, pb, pm = (las_mod.read_points(p, fields=FIELDS) for p in (a, b, out))
    assert result["points"] == 650 == pm["x"].size
    for name in FIELDS:
        assert np.array_equal(pm[name][:400], pa[name]), name
        assert np.array_equal(pm[name][400:], pb[name]), name
    # the awkward parts: extra dimensions, scales, offsets, the CRS
    for name in ("Amplitude", "Reflectance"):
        joined = np.concatenate([np.asarray(laspy.read(str(a))[name]),
                                 np.asarray(laspy.read(str(b))[name])])
        assert np.array_equal(np.asarray(laspy.read(str(out))[name]), joined)
    info_a, info_m = las_mod.cloud_info(a), las_mod.cloud_info(out)
    assert np.array_equal(info_m["scales"], info_a["scales"])
    assert np.array_equal(info_m["offsets"], info_a["offsets"])
    assert info_m["extra_dims"] == info_a["extra_dims"]
    assert info_m["crs"] is not None and info_m["crs"].equals(info_a["crs"])
    assert info_m["point_format"] == 7
    # the header must describe BOTH files, not just the first
    both = np.vstack([np.c_[pa["x"], pa["y"], pa["z"]],
                      np.c_[pb["x"], pb["y"], pb["z"]]])
    assert np.allclose(info_m["mins"], both.min(axis=0), atol=1e-3)
    assert np.allclose(info_m["maxs"], both.max(axis=0), atol=1e-3)


def test_the_sidecar_and_record_say_what_came_from_where(tmp_path):
    a = make(tmp_path / "a.las", n=400, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=250, psid=2, seed=2)
    out = tmp_path / "merged.las"
    merge_mod.merge_clouds([a, b], out, log=lambda *_: None)

    side = json.loads((tmp_path / "merged.las.merge.json").read_text())
    assert [s["points"] for s in side["sources"]] == [400, 250]
    assert [s["first_index"] for s in side["sources"]] == [0, 400]
    assert [s["point_source_ids"] for s in side["sources"]] == [[1], [2]]
    assert [s["path"] for s in side["sources"]] == [str(a.resolve()),
                                                    str(b.resolve())]
    assert side["points"] == 650 and side["renumbered"] is False
    record = json.loads(next(tmp_path.glob("merged.las.job-*.json")).read_text())
    assert record["status"] == "completed"
    assert record["operation"] == "merge"
    assert record["results"]["points"] == 650


@pytest.mark.parametrize("kwargs, message", [
    (dict(point_format=6), "point format"),
    (dict(scales=0.01), "scale"),
    (dict(offsets=(2_600_100.0, 1_200_100.0, 1_100.0)), "offset"),
    (dict(extra=("Amplitude",)), "extra dimension"),
    (dict(crs=False), "CRS"),
])
def test_clouds_that_disagree_refuse(tmp_path, kwargs, message):
    """Each of these means the two files do not describe points in the
    same terms; writing one under the other's header would reinterpret
    its bytes rather than fail."""
    a = make(tmp_path / "a.las", n=50, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=50, psid=2, seed=2, **kwargs)
    out = tmp_path / "merged.las"
    with pytest.raises(ValueError, match=message):
        merge_mod.merge_clouds([a, b], out, log=lambda *_: None)
    assert not out.exists()
    assert not list(tmp_path.glob("merged.las*.partial"))


def test_colliding_point_source_ids_refuse_until_asked(tmp_path):
    """Strip QA reads point_source_id, so two files that both number
    their points 1 become one strip the moment they are joined."""
    a = make(tmp_path / "a.las", n=60, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=40, psid=1, seed=2)
    out = tmp_path / "merged.las"
    with pytest.raises(ValueError, match="point_source_id"):
        merge_mod.merge_clouds([a, b], out, log=lambda *_: None)
    assert not out.exists()

    result = merge_mod.merge_clouds([a, b], out, psid_from_file=True,
                                    log=lambda *_: None)
    psid = las_mod.read_points(out, fields=("point_source_id",))["point_source_id"]
    assert np.array_equal(np.unique(psid[:60]), [1])
    assert np.array_equal(np.unique(psid[60:]), [2])
    assert result["renumbered"] is True
    side = json.loads((tmp_path / "merged.las.merge.json").read_text())
    assert [s["point_source_ids"] for s in side["sources"]] == [[1], [2]]
    assert [s["original_point_source_ids"] for s in side["sources"]] == [[1], [1]]


def test_merge_refuses_the_obvious_mistakes(tmp_path):
    a = make(tmp_path / "a.las", n=20, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=20, psid=2, seed=2)
    with pytest.raises(ValueError, match="two"):
        merge_mod.merge_clouds([a], tmp_path / "m.las", log=lambda *_: None)
    with pytest.raises(ValueError, match="input"):
        merge_mod.merge_clouds([a, b], a, log=lambda *_: None)
    with pytest.raises(ValueError, match="does not exist"):
        merge_mod.merge_clouds([a, tmp_path / "nowhere.las"],
                               tmp_path / "m.las", log=lambda *_: None)
    out = tmp_path / "m.las"
    merge_mod.merge_clouds([a, b], out, log=lambda *_: None)
    with pytest.raises(FileExistsError):
        merge_mod.merge_clouds([a, b], out, log=lambda *_: None)


def _watch_the_writer(monkeypatch):
    """Record whether the output was ever opened for writing.

    Deliberately independent of the cleanup: a test that inferred "the
    copy started" from the fact that something was deleted could not
    tell a copy that never began from a cleanup that was removed, and
    would report the second as the first.
    """
    opened = []
    real_open = laspy.open

    def spy(path, mode="r", **kwargs):
        if mode == "w":
            opened.append(Path(path).name)
        return real_open(path, mode=mode, **kwargs)

    monkeypatch.setattr(laspy, "open", spy)
    return opened


def test_a_failed_write_leaves_nothing_at_the_destination(tmp_path,
                                                          monkeypatch):
    """The share going away DURING the copy: the first cloud is already
    in the partial file when the second cannot be opened.

    This test was silently defanged once and is written defensively
    because of it. Moving the extended-record read ahead of the writer
    made the old version fail BEFORE any partial file existed, so it
    went on passing while asserting that nothing had been left behind
    when nothing had ever been made. It now proves the partial file
    existed before it checks that it is gone.
    """
    a = make(tmp_path / "a.las", n=60, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=60, psid=2, seed=2)
    out = tmp_path / "merged.las"
    real_records = merge_mod._extended_records

    def then_vanish(paths, log):
        records = real_records(paths, log)      # both clouds still here
        b.rename(tmp_path / "gone.las")         # the share drops
        return records

    monkeypatch.setattr(merge_mod, "_extended_records", then_vanish)
    opened = _watch_the_writer(monkeypatch)

    with pytest.raises(OSError):
        merge_mod.merge_clouds([a, b], out, log=lambda *_: None)

    assert opened, (
        "the copy never started, so this test did not exercise the "
        "cleanup it is named for")
    assert not out.exists()
    assert not list(tmp_path.glob("merged.las*.partial")), (
        "the copy started and failed, and its partial file is still there")


def test_a_cloud_that_goes_away_before_the_copy_never_starts_one(tmp_path,
                                                                 monkeypatch):
    """Failing before the writer opens is the better failure.

    Everything a merge can decide from headers is decided first, so a
    cloud that disappears between the scan and the copy costs nothing:
    no output file is created and no points are written only to be
    thrown away. On the delivery this was built for that is over a
    gigabyte. The ordering is one line and easy to undo, so it is pinned.
    """
    a = make(tmp_path / "a.las", n=60, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=60, psid=2, seed=2)
    out = tmp_path / "merged.las"
    real = las_mod.iter_points

    def vanishing(path, **kwargs):
        # the strip-id scan reads both; take the second away behind it
        if Path(path).name == "b.las":
            for chunk in real(path, **kwargs):
                yield chunk
            b.rename(tmp_path / "gone.las")
            return
        yield from real(path, **kwargs)

    monkeypatch.setattr(las_mod, "iter_points", vanishing)
    opened = _watch_the_writer(monkeypatch)

    with pytest.raises(OSError):
        merge_mod.merge_clouds([a, b], out, log=lambda *_: None)

    assert not opened, (
        f"the output was opened for writing before the merge had finished "
        f"everything it can decide from headers, so points were written "
        f"and thrown away: {opened}")
    assert not out.exists()
    assert not list(tmp_path.glob("merged.las*.partial"))


def test_cli_merges_and_then_the_dtm_sees_one_cloud(tmp_path):
    from pyargus import cli

    a = make(tmp_path / "a.las", n=4000, psid=1, seed=3)
    b = make(tmp_path / "b.las", n=4000, psid=2, seed=4)
    out = tmp_path / "merged.las"
    assert cli.main(["merge", str(a), str(b), "--out", str(out)]) == 0
    assert las_mod.cloud_info(out)["point_count"] == 8000

    asc = tmp_path / "dtm.asc"
    assert cli.main(["dtm", str(out), "--out", str(asc), "--cell", "10"]) == 0
    assert asc.exists() and asc.stat().st_size > 0


def test_reframe_joins_clouds_whose_offsets_differ(tmp_path):
    """The real delivery: the vendor wrote each flight line with its
    own coordinate offset, so the same integer means two different
    places. Refusing is right by default -- but the join is a real
    operation, so --reframe restates every point in one frame and says
    what that cost."""
    a = make(tmp_path / "a.las", n=300, psid=1, seed=1)
    b = make(tmp_path / "b.las", n=200, psid=2, seed=2,
             offsets=(2_600_500.0, 1_200_500.0, 1_110.0))
    out = tmp_path / "merged.las"

    with pytest.raises(ValueError, match="--reframe"):
        merge_mod.merge_clouds([a, b], out, log=lambda *_: None)

    result = merge_mod.merge_clouds([a, b], out, reframe=True,
                                    log=lambda *_: None)
    pa, pb, pm = (las_mod.read_points(p, fields=FIELDS) for p in (a, b, out))
    assert pm["x"].size == 500 and result["reframed"] is True
    # coordinates survive to within half a scale unit, everything else exactly
    for i, source in ((slice(0, 300), pa), (slice(300, 500), pb)):
        for axis in ("x", "y", "z"):
            assert np.max(np.abs(pm[axis][i] - source[axis])) <= 0.0005, axis
        for name in ("intensity", "gps_time", "point_source_id",
                     "classification", "return_number"):
            assert np.array_equal(pm[name][i], source[name]), name
    joined = np.concatenate([np.asarray(laspy.read(str(a))["Amplitude"]),
                             np.asarray(laspy.read(str(b))["Amplitude"])])
    assert np.array_equal(np.asarray(laspy.read(str(out))["Amplitude"]), joined)
    assert result["max_coordinate_shift"] <= 0.0005
    side = json.loads((tmp_path / "merged.las.merge.json").read_text())
    assert side["reframed"] is True
    assert side["max_coordinate_shift"] == result["max_coordinate_shift"]


def test_reframe_refuses_when_one_frame_cannot_hold_the_points(tmp_path):
    """LAS stores coordinates as 32-bit integers, so a fine scale over
    a wide extent has no frame at all: that is a refusal, not a
    silently truncated cloud."""
    # each file is writable on its own; their union is 36,000 ft wide,
    # which at a micron scale is 3.6e10 steps
    a = make(tmp_path / "a.las", n=20, psid=1, seed=1, scales=1e-6)
    b = make(tmp_path / "b.las", n=20, psid=2, seed=2, scales=1e-6,
             origin=(2_636_000.0, 1_200_000.0, 1_100.0))
    with pytest.raises(ValueError, match="32-bit"):
        merge_mod.merge_clouds([a, b], tmp_path / "m.las", reframe=True,
                               log=lambda *_: None)
    assert not (tmp_path / "m.las").exists()


def _stamp(path, payload, record_id=157):
    """Put a vendor-style extended record on an existing cloud."""
    data = laspy.read(str(path))
    from laspy.vlrs.vlrlist import VLRList
    data.evlrs = VLRList([laspy.VLR(user_id="QCS", record_id=record_id,
                                    description="vendor QC",
                                    record_data=payload)])
    data.write(str(path))
    return path


def _evlrs(path):
    with laspy.open(str(path)) as reader:
        return [(v.user_id, v.record_id, bytes(v.record_data_bytes()))
                for v in (reader.evlrs or [])]


def test_a_vendors_record_for_one_line_does_not_become_the_merges(tmp_path):
    """The delivery this was written for carries LP360 QC per line.

    Each line arrived with its own ``QCS/157`` extended record -- about
    100 KB apiece -- holding that line's quality statistics. The merge
    took the LAST input's, so a cloud of two lines went out carrying
    line 2's QC record as though it described the whole, with line 1's
    dropped and nothing said.

    The output's header is the FIRST input's, so its extended records
    are too, and anything dropped is named in the log.
    """
    a = _stamp(make(tmp_path / "a.las", n=400, psid=1, seed=1), b"L1" * 40)
    b = _stamp(make(tmp_path / "b.las", n=250, psid=2, seed=2), b"L2" * 60)
    assert _evlrs(a)[0][2] != _evlrs(b)[0][2]      # the fixture is honest

    out = tmp_path / "merged.las"
    said = []
    merge_mod.merge_clouds([a, b], out, log=said.append)

    assert _evlrs(out) == _evlrs(a), (
        "the merge kept an input's extended records that are not the "
        "first file's, whose header it carries")
    spoken = " ".join(said).lower()
    assert "extended record" in spoken and "b.las" in spoken, (
        f"dropping one input's vendor records must be said out loud, "
        f"not left for a reader to discover: {said}")


def test_matching_extended_records_pass_through_without_a_warning(tmp_path):
    same = b"identical vendor payload" * 10
    a = _stamp(make(tmp_path / "a.las", n=400, psid=1, seed=1), same)
    b = _stamp(make(tmp_path / "b.las", n=250, psid=2, seed=2), same)
    out = tmp_path / "merged.las"
    said = []
    merge_mod.merge_clouds([a, b], out, log=said.append)

    assert _evlrs(out) == _evlrs(a)
    assert "extended record" not in " ".join(said).lower(), (
        f"nothing was dropped, so there is nothing to warn about: {said}")
