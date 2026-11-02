"""One fingerprint scheme ties validation records to review packets (review item 6, G-4).

The value must change when anything that runs changes and must not change
when only documents, handoff notes, run outputs or bytecode do; the
validation runner must record it with or without git on PATH.
"""
from pathlib import Path

import pytest

from devtools import fingerprint, validate


def tree(root):
    (root / 'pyargus').mkdir(); (root / 'pyargus' / 'a.py').write_text('x=1\n')
    (root / 'tests').mkdir(); (root / 'tests' / 'test_a.py').write_text('def test(): pass\n')
    (root / 'reference').mkdir(); (root / 'reference' / 'run_all.py').write_text('EXPECT=1\n')
    (root / 'pyproject.toml').write_text('[project]\nname="x"\n')
    (root / 'docs').mkdir(); (root / 'docs' / 'guide.md').write_text('prose\n')
    (root / 'HANDOFF.md').write_text('notes\n')


def test_fingerprint_is_deterministic_and_covers_only_what_runs(tmp_path):
    tree(tmp_path)
    first = fingerprint.source_fingerprint(tmp_path)
    assert first == fingerprint.source_fingerprint(tmp_path) and len(first) == 64
    covered = [p.relative_to(tmp_path).as_posix() for p in fingerprint.source_files(tmp_path)]
    assert covered == ['pyargus/a.py', 'pyproject.toml', 'reference/run_all.py', 'tests/test_a.py']
    # Documents, handoff notes, run outputs and bytecode do not count.
    (tmp_path / 'docs' / 'guide.md').write_text('changed prose\n')
    (tmp_path / 'HANDOFF.md').write_text('more notes\n')
    (tmp_path / 'reference' / 'reports').mkdir(); (tmp_path / 'reference' / 'reports' / 'validation.json').write_text('{}')
    (tmp_path / 'pyargus' / '__pycache__').mkdir(); (tmp_path / 'pyargus' / '__pycache__' / 'a.pyc').write_bytes(b'\0')
    assert fingerprint.source_fingerprint(tmp_path) == first
    # A changed reference expectation or a new module does.
    (tmp_path / 'reference' / 'run_all.py').write_text('EXPECT=2\n')
    changed = fingerprint.source_fingerprint(tmp_path)
    assert changed != first
    (tmp_path / 'pyargus' / 'b.py').write_text('')
    assert fingerprint.source_fingerprint(tmp_path) not in (first, changed)


def test_validation_runner_records_the_shared_scheme_without_git(monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError('git')
    monkeypatch.setattr(validate.subprocess, 'check_output', no_git)
    identity = validate.source_identity()
    assert identity['scheme'] == fingerprint.SCHEME
    assert identity['sha256'] == fingerprint.source_fingerprint(validate.ROOT)
    assert identity['commit'].startswith('git unavailable') and identity['status'].startswith('git unavailable')
    assert validate.lock_directory() == validate.ROOT


def test_review_packet_script_uses_the_shared_scheme():
    script = Path(__file__).resolve().parents[1] / 'review_handoff_20261021' / 'prepare_packet.py'
    if not script.is_file():
        pytest.skip('the review packet script is not part of this checkout')
    assert 'devtools.fingerprint' in script.read_text(encoding='utf-8')
