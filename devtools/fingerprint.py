"""One source fingerprint, shared by devtools.validate and review packets.

The fingerprint covers what runs: the application, its tests, packaging,
developer tools, the reference battery and CI definitions, plus the root
files that define the build and the pinned environment. Documents and
handoff notes are left out so that the value changes only when behaviour
can; run outputs under reference/reports, caches, logs and bytecode are
left out for the same reason.

Scheme v1: SHA-256 over, for each covered file in sorted POSIX relative-path
order, the path bytes, a NUL byte and the file's own SHA-256 digest. That
per-file construction is the one both earlier tools already used; only their
file sets differed, which is why a validation record and a packet could not
be tied together before October 22, 2026.

Run: .venv/Scripts/python.exe -m devtools.fingerprint [ROOT] [--list]
"""
import argparse
import hashlib
import json
from pathlib import Path

SCHEME = 'pyargus-source-fingerprint-v1'
ROOTS = ('pyargus', 'tests', 'packaging', 'devtools', 'reference', '.github')
ROOT_FILES = ('pyproject.toml', 'conftest.py', 'requirements-validation-win-py311.txt', 'LICENSE')
EXCLUDED_DIRS = {'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'reports'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo', '.log'}


def source_files(root):
    """The covered files, sorted by POSIX relative path."""
    root = Path(root)
    files = []
    for name in ROOTS:
        folder = root / name
        if not folder.is_dir():
            continue
        for path in folder.rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if EXCLUDED_DIRS.intersection(relative.parts) or path.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            files.append(path)
    files.extend(root / name for name in ROOT_FILES if (root / name).is_file())
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def source_fingerprint(root):
    """Hex SHA-256 of the covered files' paths and contents (scheme v1)."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--list', action='store_true', help='also print every covered file')
    args = parser.parse_args(argv)
    files = source_files(args.root)
    if args.list:
        for path in files:
            print(path.relative_to(args.root).as_posix())
    print(json.dumps(dict(scheme=SCHEME, root=str(args.root), files=len(files),
                          sha256=source_fingerprint(args.root))))


if __name__ == '__main__':
    main()
