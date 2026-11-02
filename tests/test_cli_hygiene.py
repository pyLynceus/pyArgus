"""CLI tests run in a scratch directory, so no invocation leaves a job record in the checkout (review F-20).

`cli.align` opens its job record before it validates its arguments, and a
solve-only or refused invocation records into the current directory. The
conftest moves every test_cli* module into its own scratch directory; this
module checks that the move happened and that a failing invocation records
there and nowhere else.
"""
from pathlib import Path

import pytest

from pyargus import cli
from tests.test_review_workspace import cloud

ROOT = Path(__file__).resolve().parents[1]


def checkout_records():
    folder = ROOT / 'pyargus-job-records'
    return {p.name for p in folder.glob('*.json')} if folder.is_dir() else set()


def test_cli_modules_run_outside_the_checkout():
    here = Path.cwd().resolve()
    assert ROOT != here and ROOT not in here.parents


def test_failed_solve_only_align_records_in_the_scratch_directory_only(tmp_path):
    las, sbet = tmp_path / 'strip.las', tmp_path / 'flight.out'
    cloud(las)
    sbet.write_bytes(b'')          # identity needs a file; the solve then fails on its contents
    before = checkout_records()
    with pytest.raises((SystemExit, Exception)):
        cli.main(['align', str(las), '--sbet', str(sbet)])
    assert checkout_records() == before
    assert list((Path.cwd() / 'pyargus-job-records' / 'alignment-solve.job-*.json').parent.glob('alignment-solve.job-*.json'))
