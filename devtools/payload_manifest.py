"""Verify a staged Windows payload against its payload-manifest.json.

Every listed file must exist with its listed size; hashes are checked for the
executable, the application source archive and the build record always, for a
deterministic sample of the rest by default, and for every file with
``--full``. Files on disk that the manifest does not list are reported, since
a payload assembled by copying an earlier one forward is exactly how private
or stale files arrive. This is a content check, not installer or runtime
acceptance.

Run: .venv/Scripts/python.exe -m devtools.payload_manifest <payload-folder> [--full]
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

ALWAYS = ('pyArgus.exe', 'Sources/pyArgus-source.zip', 'build-info.json')
PRIVATE_NAMES = frozenset({'HANDOFF.md', 'CLAUDE.md', 'AGENTS.md', 'CODEX_WORKTREE.md'})
PRIVATE_PARTS = frozenset({'.git', '.venv', '__pycache__', 'pyargus-job-records'})


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 ** 2), b''):
            result.update(block)
    return result.hexdigest()


def verify_manifest(stage, *, full=False, sample=48):
    stage = Path(stage).resolve()
    manifest = json.loads((stage / 'payload-manifest.json').read_text(encoding='utf-8'))
    files = manifest['files']
    listed = {entry['path'] for entry in files}
    missing, wrong_size, mismatched, hashed = [], [], [], []
    for entry in files:
        path = stage / entry['path']
        if not path.is_file():
            missing.append(entry['path'])
        elif path.stat().st_size != entry['bytes']:
            wrong_size.append(entry['path'])
    chosen = [entry for entry in files if entry['path'] in ALWAYS]
    if full:
        chosen = files
    else:
        rest = [entry for entry in files if entry['path'] not in ALWAYS]
        # A fixed pseudo-random order: the same files every run, no favourites.
        rest.sort(key=lambda entry: hashlib.sha256(entry['path'].encode()).hexdigest())
        chosen += rest[:sample]
    for entry in chosen:
        path = stage / entry['path']
        if path.is_file():
            hashed.append(entry['path'])
            if digest(path) != entry['sha256']:
                mismatched.append(entry['path'])
    on_disk = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
    on_disk.discard('payload-manifest.json')
    unlisted = sorted(on_disk - listed)
    private = sorted(name for name in on_disk
                     if PurePosixPath(name).name in PRIVATE_NAMES
                     or PRIVATE_PARTS.intersection(PurePosixPath(name).parts))
    exe_matches = None
    build_info = stage / 'build-info.json'
    if build_info.is_file() and (stage / 'pyArgus.exe').is_file():
        recorded = json.loads(build_info.read_text(encoding='utf-8')).get('exe_sha256')
        exe_matches = None if recorded is None else digest(stage / 'pyArgus.exe') == recorded
    problems = bool(missing or wrong_size or mismatched or private or exe_matches is False)
    return dict(status='failed' if problems else 'verified', payload=str(stage),
                version=manifest.get('version'), build=manifest.get('build'),
                entries=len(files), hashed=len(hashed), full=full,
                missing=missing, wrong_size=wrong_size, mismatched=mismatched,
                unlisted_count=len(unlisted), unlisted=unlisted[:50], private=private,
                exe_matches_build_info=exe_matches,
                limits='Content check against the payload manifest; installer lifecycle and runtime acceptance are separate.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('payload', type=Path)
    parser.add_argument('--full', action='store_true', help='hash every listed file')
    parser.add_argument('--sample', type=int, default=48, help='files hashed beyond the executable, source and build record')
    args = parser.parse_args(argv)
    result = verify_manifest(args.payload, full=args.full, sample=args.sample)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
