"""The coverage critic's findings: the places no review lens looked.

After eight lenses and their refuters had finished with merge, a final
agent was asked what the panel had NOT examined. It went and read those
places, and three of what it found are real. They share a shape: none
of them is in the code anyone was reviewing, and all three would fire
on ordinary use.
"""

import json

import numpy as np
import pytest

laspy = pytest.importorskip("laspy")

from tests.test_merge import make  # noqa: E402
from pyargus.classify import noise as noise_mod  # noqa: E402
from reference import grid_compare as check  # noqa: E402
from reference import mark_profile as sections  # noqa: E402


def test_noise_cut_refuses_an_existing_output(tmp_path):
    """Every sibling writer in this suite refuses; this one did not.

    The CLI guarded it and the library function did not, so the desktop
    app and any script calling noise_cut directly would overwrite a
    finished cloud without a word -- on a real delivery, hundreds of
    megabytes whose provenance sidecar then describes a different run.
    """
    src = make(tmp_path / "in.las", n=200, psid=1, seed=1)
    out = tmp_path / "out.las"
    noise_mod.noise_cut(src, out, z_min=1_000.0, z_max=1_200.0,
                        log=lambda *_: None)
    before = out.stat().st_mtime_ns

    with pytest.raises(FileExistsError):
        noise_mod.noise_cut(src, out, z_min=1_000.0, z_max=1_200.0,
                            log=lambda *_: None)
    assert out.stat().st_mtime_ns == before, "the refused call still wrote"

    noise_mod.noise_cut(src, out, z_min=1_000.0, z_max=1_200.0, force=True,
                        log=lambda *_: None)
    assert out.is_file()


def test_a_refused_noise_cut_leaves_a_record_of_the_attempt(tmp_path):
    """The docstring promised this and nine of thirteen refusals broke it.

    Every header-derived refusal used to raise before the job record
    existed, so the case the module cites as its reason for existing --
    metres typed for a cloud in feet -- exited with a good message and
    left nothing behind. An operator auditing "was this ever run with
    the wrong units" found no trace either way.
    """
    src = make(tmp_path / "in.las", n=100, psid=1, seed=1)
    out = tmp_path / "cut.las"
    with pytest.raises(ValueError, match="(?i)above every point"):
        noise_mod.noise_cut(src, out, z_min=3_200.0, z_max=3_900.0,
                            log=lambda *_: None)
    records = sorted(tmp_path.glob("cut.las.job-*.json"))
    assert records, "a refusal must leave a record of the attempt"
    body = json.loads(records[-1].read_text(encoding="utf-8"))
    assert json.dumps(body).lower().count("fail") or body.get("status") in (
        "failed", "error"), f"the record does not say it failed: {body}"
    assert not out.exists()


def test_the_mark_summary_survives_a_mark_with_no_ground_under_it():
    """A control mark on a roof, a bridge or open water has no class-2
    point within its radius, so the residual is None and the summary
    line formatted it with :+.2f. The whole run dies at the print."""
    rows = sections.mark_profiles.__doc__ is not None      # module imported
    assert rows
    for residual in (None, -0.5):
        text = sections._residual_text(residual)
        assert isinstance(text, str) and text.strip()
    assert "no ground" in sections._residual_text(None).lower()


def test_the_dtm_check_says_so_when_a_band_selects_no_cells():
    """`_stats` indexed percentiles of an empty array.

    Ask for cells more than N from the boundary on a narrow corridor and
    the selection can be empty; the script died with an IndexError deep
    in numpy instead of saying the band was empty.
    """
    empty = check._stats(np.array([]))
    assert empty["n"] == 0
    for key in ("median", "nmad", "rmse", "p1", "p99"):
        assert empty[key] is None, f"{key} should be None for no cells"
    assert empty["over_2_ft"] == 0

    real = check._stats(np.array([1.0, -1.0, 0.5]))
    assert real["n"] == 3 and real["median"] == 0.5
