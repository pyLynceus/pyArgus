"""Noise classes are statements about points that SMRF must not overturn,
and ``noise-cut`` is how a raw delivery gets them.

The defect these pin came from a real job: two flight lines classified
straight from the vendor export carried over a hundred gross outliers,
nearly all of them low (the lowest over a thousand feet below the
ground). SMRF builds a per-cell MINIMUM surface, an opening removes
bumps and never pits, so each outlier became the DEM's own value there,
the slope term around the pit inflated the allowance, and ground came
out tens of feet above the vendor's own surface. Nothing in the suite
could flag such a point, and even a pre-flagged one was ignored: the
candidate rule read only return numbers and the labeling rule
overwrote every class.
"""

import json

import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from pyargus.classify import job as ground_job  # noqa: E402

CELL, SLOPE, WINDOW = 3.0, 0.15, 30.0
THRESHOLD, SCALAR = 1.5, 1.25
PARAMS = dict(cell=CELL, slope=SLOPE, window=WINDOW,
              threshold=THRESHOLD, scalar=SCALAR)
LOW, HIGH = 7, 18


ROOF = 18.0    # half-width: a 36-ft building, inside the reach of a
               # window-30 opening (which removes bumps under 60 ft wide)


def roof_mask(x, y):
    return (np.abs(x - 300.0) < ROOF) & (np.abs(y - 300.0) < ROOF)


def scene(seed=0, n=100_000, span=500.0):
    """Gentle ground with one 30-ft building near the middle: the object
    a pit inside it would pull into class 2."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, span, n)
    y = rng.uniform(0.0, span, n)
    z = 100.0 + 0.01 * x + 2.0 * np.sin(y / 80.0) + rng.normal(0.0, 0.05, n)
    z[roof_mask(x, y)] += 30.0
    return x, y, z


def write_las(path, x, y, z, classification=None, extra=None):
    """A pf7 LAS 1.4 with an extra dimension, as the vendor ships them."""
    header = laspy.LasHeader(version="1.4", point_format=7)
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([0.0, 0.0, 0.0])
    header.add_extra_dim(laspy.ExtraBytesParams(name="Reflectance",
                                                type=np.float32))
    data = laspy.LasData(header)
    data.x, data.y, data.z = x, y, z
    data.return_number = np.ones(x.size, dtype=np.uint8)
    data.number_of_returns = np.ones(x.size, dtype=np.uint8)
    data.intensity = (np.arange(x.size) % 4000).astype(np.uint16)
    data.gps_time = 1000.0 + np.arange(x.size) * 1e-4
    if classification is not None:
        data.classification = np.asarray(classification, dtype=np.uint8)
    data.Reflectance = (np.arange(x.size) * 0.5).astype(np.float32) \
        if extra is None else extra
    data.write(str(path))
    return path


def classes_of(path):
    return np.asarray(laspy.read(str(path)).classification)


# ---------------------------------------------------------------- SMRF


def test_a_flagged_pit_does_not_shape_the_surface(tmp_path):
    """The same scene with and without a class-7 pit beside the building
    must classify identically, and the pit must stay class 7."""
    x, y, z = scene()
    clean = write_las(tmp_path / "clean.las", x, y, z)
    # one low-noise point 1,000 ft below grade, under the middle of the
    # roof and on a cell centre (cell 3: 301.5) so its DEM cell is its
    # own, and one high-noise point far above open ground
    px = np.concatenate([x, [301.5, 150.5]])
    py = np.concatenate([y, [301.5, 150.5]])
    pz = np.concatenate([z, [-900.0, 2000.0]])
    cls = np.zeros(px.size, dtype=np.uint8)
    cls[-2], cls[-1] = LOW, HIGH
    noisy = write_las(tmp_path / "noisy.las", px, py, pz, cls)

    said = []
    ground_job.classify_ground_whole(clean, tmp_path / "clean_out.las",
                                     **PARAMS)
    result = ground_job.classify_ground_whole(
        noisy, tmp_path / "noisy_out.las", log=said.append, **PARAMS)
    a = classes_of(tmp_path / "clean_out.las")
    b = classes_of(tmp_path / "noisy_out.las")
    assert a.sum() > 0 and (a == 2).sum() > 0.5 * a.size
    assert np.array_equal(b[:-2], a), int((b[:-2] != a).sum())
    assert b[-2] == LOW and b[-1] == HIGH
    assert result["noise"] == 2
    assert any(line.startswith("noise:") for line in said), said


def test_the_pit_is_the_defect_when_it_is_not_flagged(tmp_path):
    """The guard above is worth having only if an unflagged pit really
    does damage: prove it on the same scene."""
    x, y, z = scene()
    px = np.concatenate([x, [301.5]])
    py = np.concatenate([y, [301.5]])
    pz = np.concatenate([z, [-900.0]])
    plain = write_las(tmp_path / "plain.las", px, py, pz)
    clean = write_las(tmp_path / "clean.las", x, y, z)
    ground_job.classify_ground_whole(plain, tmp_path / "plain_out.las",
                                     **PARAMS)
    ground_job.classify_ground_whole(clean, tmp_path / "clean_out.las",
                                     **PARAMS)
    a = classes_of(tmp_path / "clean_out.las")
    b = classes_of(tmp_path / "plain_out.las")
    roof = roof_mask(x, y)
    assert int(np.count_nonzero((a == 2) & roof)) == 0, "the clean roof is not ground"
    pulled = int(np.count_nonzero((b[:-1] == 2) & roof))
    assert b[-1] == 2, "an unflagged pit is its own DEM cell"
    # the inflated allowance reaches the pit's neighbouring cells only,
    # so this is tens of points on a 36-ft roof, never the whole roof
    assert pulled > 10, f"expected the pit to pull roof into ground, got {pulled}"


def test_tiled_and_whole_agree_with_noise_present(tmp_path):
    x, y, z = scene(seed=3, n=80_000)
    rng = np.random.default_rng(9)
    k = 12
    px = np.concatenate([x, rng.uniform(0, 500, k)])
    py = np.concatenate([y, rng.uniform(0, 500, k)])
    pz = np.concatenate([z, np.where(np.arange(k) % 2 == 0, -500.0, 1500.0)])
    cls = np.zeros(px.size, dtype=np.uint8)
    cls[-k:] = np.where(np.arange(k) % 2 == 0, LOW, HIGH)
    src = write_las(tmp_path / "src.las", px, py, pz, cls)
    whole = ground_job.classify_ground_whole(src, tmp_path / "whole.las",
                                             **PARAMS)
    tiled = ground_job.classify_ground_tiled(src, tmp_path / "tiled.las",
                                             tile_size=200.0, **PARAMS)
    a, b = classes_of(tmp_path / "whole.las"), classes_of(tmp_path / "tiled.las")
    assert np.array_equal(a, b), int((a != b).sum())
    assert np.array_equal(a[-k:], cls[-k:])
    assert (a[:-k] == 2).sum() > 0
    assert whole["noise"] == tiled["noise"] == k

    # --any-return admits every return to the surface -- but never a
    # flagged one, in either driver: the tiled path reads the class
    # field for its own keep filter, not only for the labels
    wa = ground_job.classify_ground_whole(src, tmp_path / "whole_any.las",
                                          any_return=True, **PARAMS)
    ta = ground_job.classify_ground_tiled(src, tmp_path / "tiled_any.las",
                                          any_return=True, tile_size=200.0,
                                          **PARAMS)
    c = classes_of(tmp_path / "whole_any.las")
    d = classes_of(tmp_path / "tiled_any.las")
    assert np.array_equal(c, d), int((c != d).sum())
    assert np.array_equal(c[-k:], cls[-k:])
    assert wa["noise"] == ta["noise"] == k


def test_both_noise_routes_at_once_are_counted_once(tmp_path):
    """Flags carried in AND screening on the fly, in one run.

    The two routes were built on separate branches and git merged the
    tiled driver's counting silently: one line from each side survived,
    and together they counted every already-flagged point twice. The
    whole driver kept a dict key naming a variable the other side had
    removed. Each route is counted on its own here, with the noise
    spread through the file so the tiled pass must ADD its counts
    across chunks (the first version of this test put every noise point
    in the last chunk, where a count that overwrote instead of adding
    still came out right), and both drivers must say the same thing.
    """
    x, y, z = scene(seed=5, n=60_000)
    rng = np.random.default_rng(11)
    k, m = 6, 8     # k carried in, m screened now
    chunk = 7_000
    total = x.size + k + m
    # where the noise sits in the file: spread end to end, carried-in
    # and screened interleaved
    where = np.linspace(500, total - 500, k + m).astype(int)
    carried_at, screened_at = where[0::2][:k], np.setdiff1d(where, where[0::2][:k])
    assert len(set((where // chunk).tolist())) >= 5, "noise must span chunks"
    # carried-in flags: two on the side of the window their class names,
    # one INSIDE it, and three on the WRONG side -- flagged high while
    # standing below, low while standing above. A recorded flag is kept
    # as it was, not re-decided by this run's window; without the
    # wrong-side ones, a screen that overwrote flags would change nothing
    carried_z = np.array([-500.0, 1500.0, -400.0, 100.0, 1600.0, 1700.0])
    carried_c = np.array([LOW, HIGH, HIGH, HIGH, LOW, LOW], dtype=np.uint8)
    # screened now: unflagged, half below the window and half above
    screened_z = np.where(np.arange(m) % 2 == 0, -300.0, 1300.0)
    scene_at = np.setdiff1d(np.arange(total), where)
    px, py, pz = np.empty(total), np.empty(total), np.empty(total)
    px[scene_at], py[scene_at], pz[scene_at] = x, y, z
    px[where] = rng.uniform(0, 500, k + m)
    py[where] = rng.uniform(0, 500, k + m)
    pz[carried_at], pz[screened_at] = carried_z, screened_z
    cls = np.zeros(total, dtype=np.uint8)
    cls[carried_at] = carried_c
    src = write_las(tmp_path / "src.las", px, py, pz, cls)
    # a limit with more than six significant digits: the log must state
    # the limit that was APPLIED, not a rounding of it
    window = dict(noise_min=0.0, noise_max=1000.0625)

    said_whole, said_tiled = [], []
    whole = ground_job.classify_ground_whole(
        src, tmp_path / "whole.las", log=said_whole.append, **window,
        **PARAMS)
    tiled = ground_job.classify_ground_tiled(
        src, tmp_path / "tiled.las", tile_size=200.0, chunk_size=chunk,
        log=said_tiled.append, **window, **PARAMS)

    a, b = classes_of(tmp_path / "whole.las"), classes_of(tmp_path / "tiled.las")
    assert np.array_equal(a, b), int((a != b).sum())
    assert np.array_equal(a[carried_at], carried_c)
    expected = np.where(screened_z < 0.0, LOW, HIGH)
    assert np.array_equal(a[screened_at], expected)
    for result in (whole, tiled):
        assert result["noise_already"] == k
        assert result["noise_screened"] == m
        assert result["noise"] == k + m
    for said in (said_whole, said_tiled):
        noise_lines = [line for line in said if line.startswith("noise:")]
        assert len(noise_lines) == 2, noise_lines
        assert f"{k:,} points already flagged" in noise_lines[0]
        assert (f"{m:,} points screened outside 0 to 1000.0625 "
                in noise_lines[1]), noise_lines[1]


# ------------------------------------------------- the screen's guard
#
# noise-cut refused a window that would flag more than a declared
# fraction of the cloud; screening during classification did not, so a
# limit typed inside the site's own elevations -- metres for a cloud in
# feet, or a bound from the wrong job -- quietly called the site noise
# and classified what was left. The same two refusals now guard both
# routes, in the same cost order.

# by NAME, looked up at call time: a dict of function objects captured at
# import would keep testing whatever the module held then
DRIVERS = {"whole": ("classify_ground_whole", {}),
           "tiled": ("classify_ground_tiled", {"tile_size": 200.0})}


def driver_of(key):
    name, extra = DRIVERS[key]
    return getattr(ground_job, name), extra


def quiet(_):
    pass


@pytest.mark.parametrize("driver", sorted(DRIVERS))
def test_screening_refuses_a_window_that_catches_the_site(tmp_path, driver):
    run, extra = driver_of(driver)
    x, y, z = scene(seed=7, n=30_000)
    src = write_las(tmp_path / "src.las", x, y, z)
    out = tmp_path / "out.las"
    # a ceiling typed inside the site: the roof and the upper part of the
    # slope stand above it
    with pytest.raises(ValueError, match="not gross noise") as refused:
        run(src, out, noise_max=103.0, log=quiet, **extra, **PARAMS)
    assert "--noise-max-fraction" in str(refused.value)
    assert not out.exists()
    records = list(tmp_path.glob("out.las.job-*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text(encoding="utf-8"))["status"] == "failed"
    # raised on purpose, the same window runs
    raised = run(src, tmp_path / "raised.las", noise_max=103.0,
                 noise_max_fraction=1.0, log=quiet, **extra, **PARAMS)
    assert raised["noise_screened"] > 0.001 * x.size


@pytest.mark.parametrize("driver", sorted(DRIVERS))
def test_a_screen_outside_the_header_refuses_before_reading_a_point(
        tmp_path, monkeypatch, driver):
    """The case the fraction exists for -- a bound from the wrong job,
    or the wrong units -- is the case where EVERY point is caught, so
    it is refused from the header, before a point is read."""
    run, extra = driver_of(driver)
    x, y, z = scene(seed=7, n=5_000)
    src = write_las(tmp_path / "src.las", x, y, z)

    def no_reads(*args, **kwargs):
        raise AssertionError("points were read before the refusal")

    monkeypatch.setattr(laspy, "read", no_reads)
    monkeypatch.setattr(ground_job.las_mod, "iter_points", no_reads)
    monkeypatch.setattr(ground_job.las_mod, "copc_query", no_reads)
    with pytest.raises(ValueError, match="--noise-min 5000 is above every "
                                         "point"):
        run(src, tmp_path / "a.las", noise_min=5000.0, log=quiet, **extra,
            **PARAMS)
    with pytest.raises(ValueError, match="--noise-max -5000 is below every "
                                         "point"):
        run(src, tmp_path / "b.las", noise_max=-5000.0, log=quiet, **extra,
            **PARAMS)


def test_the_tiled_screen_refuses_on_the_running_count(tmp_path, monkeypatch):
    """Not after accumulating the whole cloud: the refusal is the cheap
    thing, and on a real job the tiled driver is the one whose cloud is
    too big to hold."""
    x, y, z = scene(seed=8, n=40_000)
    src = write_las(tmp_path / "src.las", x, y, z)
    real = ground_job.las_mod.iter_points
    read = []

    def counting(*args, **kwargs):
        for chunk in real(*args, **kwargs):
            read.append(np.asarray(chunk["z"]).size)
            yield chunk

    monkeypatch.setattr(ground_job.las_mod, "iter_points", counting)
    with pytest.raises(ValueError, match="not gross noise"):
        ground_job.classify_ground_tiled(
            src, tmp_path / "out.las", tile_size=200.0, chunk_size=2_000,
            noise_max=103.0, log=quiet, **PARAMS)
    assert 0 < sum(read) <= 2 * 2_000, sum(read)


@pytest.mark.parametrize("driver", sorted(DRIVERS))
def test_the_screen_budget_is_the_same_boundary_as_noise_cut(tmp_path, driver):
    """int(fraction x points) may be flagged; one more refuses. Points
    carried in already flagged do not count against it: they are not
    this run's decision."""
    run, extra = driver_of(driver)
    for planted, refuses in ((10, False), (11, True)):
        x, y, z = scene(seed=9, n=10_000 - planted)
        rng = np.random.default_rng(planted)
        px = np.concatenate([x, rng.uniform(0, 500, planted + 20)])
        py = np.concatenate([y, rng.uniform(0, 500, planted + 20)])
        pz = np.concatenate([z, np.full(planted + 20, -400.0)])
        cls = np.zeros(px.size, dtype=np.uint8)
        cls[-20:] = LOW          # twenty more, flagged before the run
        src = write_las(tmp_path / f"src{planted}.las", px, py, pz, cls)
        out = tmp_path / f"out{planted}.las"
        if refuses:
            with pytest.raises(ValueError, match="not gross noise"):
                run(src, out, noise_min=0.0, log=quiet, **extra, **PARAMS)
        else:
            result = run(src, out, noise_min=0.0, log=quiet, **extra,
                         **PARAMS)
            assert result["noise_screened"] == planted
            assert result["noise_already"] == 20


def test_the_screen_fraction_is_validated_with_the_bounds():
    for bad in (0.0, -0.1, 1.5, float("nan")):
        with pytest.raises(ValueError, match="fraction"):
            ground_job.validate_noise_bounds(None, 1200.0, bad)
    ground_job.validate_noise_bounds(None, 1200.0, 1.0)
    ground_job.validate_noise_bounds(1000.0, 1200.0)


def test_cli_screen_refusal_names_the_option_that_overrides_it(tmp_path):
    from pyargus import cli

    x, y, z = scene(seed=7, n=20_000)
    src = write_las(tmp_path / "src.las", x, y, z)
    base = ["classify-ground", str(src), "--cell", str(CELL), "--slope",
            str(SLOPE), "--window", str(WINDOW), "--threshold",
            str(THRESHOLD), "--noise-max", "103"]
    with pytest.raises(SystemExit, match="--noise-max-fraction"):
        cli.main(base + ["--out", str(tmp_path / "a.las")])
    assert cli.main(base + ["--out", str(tmp_path / "b.las"),
                            "--noise-max-fraction", "1"]) == 0


def test_the_fraction_field_does_not_outdate_earlier_jobs():
    """The workspace compares a job's recorded stage fields with the
    current ones to call it outdated, and it records every field on the
    stage -- so a new field, compared naively, would call every
    classification made before it existed outdated."""
    from pyargus.workspace_state import Tracker

    tracker = Tracker()

    def job(**stage):
        return dict(stage="Classification", stage_class="ClassifyStage",
                    settings=dict(stage=dict(cell="3.0", out_path="a.las",
                                             **stage)))

    def same(recorded, **now):
        current = dict(stage=dict(cell="3.0", out_path="b.las", **now))
        return (tracker.comparable_settings(recorded, current)
                == tracker.comparable_settings(recorded, recorded["settings"]))

    # no window: the fraction cannot have mattered, whatever it says
    assert same(job(noise_min="", noise_max=""), noise_min="", noise_max="",
                noise_max_fraction="0.001")
    assert same(job(noise_min="", noise_max=""), noise_min="", noise_max="",
                noise_max_fraction="0.5")
    # a window, recorded before the field existed: compares at the default
    assert same(job(noise_min="", noise_max="1200"), noise_min="",
                noise_max="1200", noise_max_fraction="0.001")
    # but under a window a changed fraction IS a changed setting
    assert not same(job(noise_min="", noise_max="1200"), noise_min="",
                    noise_max="1200", noise_max_fraction="0.01")
    # a field holding only spaces is blank to the run (it strips the
    # text), so it is no window here either
    assert same(job(noise_min=" ", noise_max=""), noise_min=" ",
                noise_max="", noise_max_fraction="0.5")


def test_the_tiled_plan_refuses_before_the_screen_reads_a_point(tmp_path,
                                                                monkeypatch):
    """A halo or tile size that cannot be right is known from the
    arguments alone; with a noise window set it must not wait behind a
    full streaming pass (the review panel measured it doing so)."""
    x, y, z = scene(seed=7, n=5_000)
    src = write_las(tmp_path / "src.las", x, y, z)

    def no_reads(*args, **kwargs):
        raise AssertionError("points were read before the refusal")

    monkeypatch.setattr(ground_job.las_mod, "iter_points", no_reads)
    with pytest.raises(ValueError, match="halo"):
        ground_job.classify_ground_tiled(src, tmp_path / "a.las", halo=1.0,
                                         noise_max=500.0, log=quiet, **PARAMS)
    with pytest.raises(ValueError, match="tile_size must be positive"):
        ground_job.classify_ground_tiled(src, tmp_path / "b.las",
                                         tile_size=-5.0, noise_max=500.0,
                                         log=quiet, **PARAMS)


@pytest.mark.parametrize("driver", sorted(DRIVERS))
def test_a_truncated_cloud_is_refused_before_it_is_screened(tmp_path, driver):
    """The budget is a share of the cloud. laspy reads a truncated file
    short without complaint, and the two drivers took the share of
    different counts -- the tiled one of the header's -- so they reached
    opposite decisions on the same file, and the tiled one published."""
    run, extra = driver_of(driver)
    x, y, z = scene(seed=10, n=10_000)
    full = write_las(tmp_path / "full.las", x, y, z)
    with laspy.open(str(full)) as reader:
        start = reader.header.offset_to_point_data
        size = reader.header.point_format.size
    short = tmp_path / "short.las"
    short.write_bytes(full.read_bytes()[:start + 7_000 * size])
    with pytest.raises(ValueError, match="truncated"):
        run(short, tmp_path / "out.las", noise_max=500.0, log=quiet, **extra,
            **PARAMS)
    assert not (tmp_path / "out.las").exists()


# ---------------------------------------------------------------- noise-cut


def cli_noise_cut(src, out, *extra):
    from pyargus import cli
    return cli.main(["noise-cut", str(src), "--out", str(out), *extra])


@pytest.mark.parametrize("chunk", [1_000_000, 1_000, 7])
def test_noise_cut_flags_only_the_window_and_touches_nothing_else(tmp_path,
                                                                  chunk):
    """Run it chunked as well as whole: a real delivery runs to tens of
    chunks, and pass 2 addresses points by their absolute index across
    chunk boundaries. The flagged indices below sit at a chunk start (1000),
    a chunk end (999 is not flagged but 4999 is the file's last point)
    and in the middle, so an off-by-one in the searchsorted window or a
    forgotten chunk offset flags the wrong records."""
    x, y, z = scene(n=5_000)
    rng = np.random.default_rng(1)
    cls = rng.integers(0, 3, x.size).astype(np.uint8)   # 0, 1, 2 as delivered
    z = z.copy()
    low_idx, high_idx = [0, 1000, 4999], [77, 2500]
    z[low_idx] = [-7.5, 20.0, 40.0]
    z[high_idx] = [1500.0, 5000.0]
    src = write_las(tmp_path / "src.las", x, y, z, cls)
    out = tmp_path / "cut.las"
    assert cli_noise_cut(src, out, "--z-min", "60", "--z-max", "200",
                         "--max-fraction", "0.01",
                         "--chunk-size", str(chunk)) == 0

    before, after = laspy.read(str(src)), laspy.read(str(out))
    assert len(after.points) == len(before.points)
    expect = cls.copy()
    expect[low_idx], expect[high_idx] = LOW, HIGH
    assert np.array_equal(np.asarray(after.classification), expect)
    for name in ("x", "y", "z", "intensity", "return_number",
                 "number_of_returns", "gps_time", "Reflectance"):
        assert np.array_equal(np.asarray(after[name]), np.asarray(before[name])), name
    assert "Reflectance" in after.point_format.dimension_names
    assert after.header.scales.tolist() == before.header.scales.tolist()

    sidecar = json.loads((tmp_path / "cut.las.noise.json").read_text())
    assert sidecar["z_min"] == 60.0 and sidecar["z_max"] == 200.0
    assert sidecar["points"] == x.size
    assert sidecar["flagged_low"] == 3 and sidecar["flagged_high"] == 2
    flagged = {f["index"]: f for f in sidecar["flagged"]}
    assert sorted(flagged) == sorted(low_idx + high_idx)
    assert flagged[0]["previous_class"] == int(cls[0])
    assert flagged[0]["z"] == pytest.approx(-7.5, abs=1e-3)
    assert flagged[77]["class"] == HIGH
    assert [f["index"] for f in sidecar["flagged"]] == sorted(flagged)
    # the sidecar exists to audit a flag without re-reading the cloud,
    # so its coordinates must be that point's own (x and y not swapped)
    for i in low_idx + high_idx:
        assert flagged[i]["x"] == pytest.approx(x[i], abs=1e-3), i
        assert flagged[i]["y"] == pytest.approx(y[i], abs=1e-3), i
    record = json.loads(next(tmp_path.glob("cut.las.job-*.json")).read_text())
    assert record["status"] == "completed"
    assert record["operation"] == "noise-cut"
    assert record["results"]["flagged_low"] == 3


def test_noise_cut_leaves_existing_flags_alone(tmp_path):
    """A point the vendor already flagged keeps ITS OWN class, inside
    the window or out. The out-of-window pair is the point: a class-18
    point below z-min must not be rewritten to 7, nor counted as newly
    flagged."""
    x, y, z = scene(n=2_000)
    z = z.copy()
    cls = np.zeros(x.size, dtype=np.uint8)
    cls[5] = LOW                      # in-band, pre-flagged by the vendor
    cls[6], z[6] = HIGH, -50.0        # vendor high noise, below z-min
    cls[7], z[7] = LOW, 900.0         # vendor low noise, above z-max
    src = write_las(tmp_path / "src.las", x, y, z, cls)
    out = tmp_path / "cut.las"
    assert cli_noise_cut(src, out, "--z-min", "0", "--z-max", "500") == 0
    after = classes_of(out)
    assert after[5] == LOW and after[6] == HIGH and after[7] == LOW
    sidecar = json.loads((tmp_path / "cut.las.noise.json").read_text())
    assert sidecar["flagged_low"] == 0 and sidecar["flagged_high"] == 0
    assert sidecar["already_flagged"] == 3
    assert sidecar["flagged"] == []


def test_noise_cut_states_the_window_it_applied(tmp_path):
    """Limits were printed with ``:g``, six significant digits, so a
    window of 1100.0625 logged as 1100.06 -- a limit the run did not
    use, in the line an operator checks it against. The refusal
    messages quote the limits too."""
    from pyargus.classify import noise

    x, y, z = scene(n=2_000)
    src = write_las(tmp_path / "src.las", x, y, z)
    said = []
    noise.noise_cut(src, tmp_path / "cut.las", z_min=-1000.0625,
                    z_max=1100.0625, max_fraction=0.5, log=said.append)
    assert any("z < -1000.0625" in line for line in said), said
    assert any("z > 1100.0625" in line for line in said), said
    with pytest.raises(ValueError, match=r"--z-min 1100\.0625 must be below "
                                         r"--z-max 1100\.0625"):
        noise.noise_cut(src, tmp_path / "again.las", z_min=1100.0625,
                        z_max=1100.0625, log=said.append)
    with pytest.raises(ValueError, match=r"--z-min 5000\.0625 is above"):
        noise.noise_cut(src, tmp_path / "again.las", z_min=5000.0625,
                        log=said.append)


def test_noise_cut_refuses_before_writing(tmp_path):
    x, y, z = scene(n=3_000)
    z = z.copy()
    z[:30] = -100.0                    # 1% of the cloud
    src = write_las(tmp_path / "src.las", x, y, z)
    out = tmp_path / "cut.las"
    with pytest.raises(SystemExit, match="fraction"):
        cli_noise_cut(src, out, "--z-min", "0", "--max-fraction", "0.001")
    assert not out.exists() and not list(tmp_path.glob("cut.las*.partial"))
    assert not (tmp_path / "cut.las.noise.json").exists()
    # no cloud, but the attempt IS recorded: that is what the message says
    records = list(tmp_path.glob("cut.las.job-*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["status"] == "failed"

    with pytest.raises(SystemExit, match="z-min"):
        cli_noise_cut(src, out, "--z-min", "200", "--z-max", "100")
    with pytest.raises(SystemExit, match="bound"):
        cli_noise_cut(src, out)
    with pytest.raises(SystemExit, match="finite"):
        cli_noise_cut(src, out, "--z-min", "nan")
    with pytest.raises(SystemExit, match="max-fraction"):
        cli_noise_cut(src, out, "--z-min", "0", "--max-fraction", "0")
    with pytest.raises(SystemExit, match="max-fraction"):
        cli_noise_cut(src, out, "--z-min", "0", "--max-fraction", "2")
    with pytest.raises(SystemExit, match="input"):
        cli_noise_cut(src, src, "--z-min", "0")
    with pytest.raises(SystemExit, match="does not exist"):
        cli_noise_cut(tmp_path / "nowhere.las", out, "--z-min", "0")
    # a window outside the header's own range is a typo, and it refuses
    # before reading a single point rather than after tens of chunks of them
    with pytest.raises(SystemExit, match="above every point"):
        cli_noise_cut(src, out, "--z-min", "5000")
    with pytest.raises(SystemExit, match="below every point"):
        cli_noise_cut(src, out, "--z-max", "-5000")

    assert cli_noise_cut(src, out, "--z-min", "0", "--max-fraction", "0.02") == 0
    with pytest.raises(SystemExit, match="exists"):
        cli_noise_cut(src, out, "--z-min", "0", "--max-fraction", "0.02")
    before = out.stat().st_mtime_ns
    assert cli_noise_cut(src, out, "--z-min", "-200", "--max-fraction",
                         "0.02", "--force") == 0
    assert out.stat().st_mtime_ns != before
    assert int((classes_of(out) == LOW).sum()) == 0   # the new window flags none


def test_noise_cut_refuses_a_cloud_whose_header_miscounts(tmp_path):
    """A truncated copy off a share reads short in both passes, so a
    written == read check cannot see it; the header is the third number
    that must agree."""
    import struct

    x, y, z = scene(n=1_000)
    src = write_las(tmp_path / "src.las", x, y, z)
    raw = bytearray(src.read_bytes())
    struct.pack_into("<Q", raw, 247, 1_200)       # LAS 1.4 point count
    src.write_bytes(bytes(raw))
    with pytest.raises(SystemExit, match="header claims"):
        cli_noise_cut(src, tmp_path / "cut.las", "--z-min", "0")
    assert not (tmp_path / "cut.las").exists()


def test_noise_cut_then_classify_carries_the_flags_end_to_end(tmp_path):
    from pyargus import cli

    x, y, z = scene(seed=5)
    px = np.concatenate([x, [301.5, 150.5]])
    py = np.concatenate([y, [301.5, 150.5]])
    pz = np.concatenate([z, [-900.0, 2000.0]])
    raw = write_las(tmp_path / "raw.las", px, py, pz)
    cut = tmp_path / "cut.las"
    assert cli_noise_cut(raw, cut, "--z-min", "50", "--z-max", "200") == 0
    common = ["classify-ground", str(cut), "--cell", str(CELL), "--slope",
              str(SLOPE), "--window", str(WINDOW), "--threshold",
              str(THRESHOLD), "--scalar", str(SCALAR)]
    assert cli.main(common + ["--out", str(tmp_path / "w.las")]) == 0
    assert cli.main(common + ["--out", str(tmp_path / "t.las"), "--tiled",
                              "--tile-size", "200"]) == 0
    w, t = classes_of(tmp_path / "w.las"), classes_of(tmp_path / "t.las")
    assert np.array_equal(w, t)
    assert w[-2] == LOW and w[-1] == HIGH
    # and the roof is not ground: the flagged pit never reached it
    assert int(np.count_nonzero((w[:-2] == 2) & roof_mask(x, y))) == 0
