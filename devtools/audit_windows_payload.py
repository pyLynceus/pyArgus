"""Read-only release-content gate; does not claim installer or runtime acceptance."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

GEOID_SHA256 = 'fa9a407ac7ee3f5a3694008e4bcd09ce9cc250452f0c3b11700a4960340abce2'
PRIVATE_NAMES = frozenset({'HANDOFF.md', 'CLAUDE.md', 'AGENTS.md', 'CODEX_WORKTREE.md'})
PRIVATE_PARTS = frozenset({'.git', '.venv', '__pycache__', 'pyargus-job-records',
                           'review_handoff_20261021'})


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):result.update(block)
    return result.hexdigest()


def audit_source_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name in names:
            rel = PurePosixPath(name.replace('\\', '/'))
            if (rel.is_absolute() or '..' in rel.parts or
                rel.name in PRIVATE_NAMES or PRIVATE_PARTS.intersection(rel.parts) or
                ('.job-' in rel.name and rel.suffix == '.json') or
                ('reference' in rel.parts and 'reports' in rel.parts)):
                raise ValueError('Private or unsafe source archive member: ' + name)
        if 'pyArgus/pyproject.toml' not in names or 'pyArgus/LICENSE' not in names:
            raise ValueError('Application source archive lacks project metadata or license')
    return dict(path=str(path), members=len(names), sha256=digest(path))


def audit_payload(stage):
    stage = Path(stage).resolve()
    required = ['pyArgus.exe', 'native-pdal/Library/bin/pdal.exe',
                'Sources/native-packages.json', 'Sources/pyArgus-source.zip',
                'Licenses/python-packages.json', 'build-info.json']
    for name in required:
        if not (stage/name).is_file():raise ValueError('Missing payload file: ' + name)
    source = audit_source_archive(stage/'Sources/pyArgus-source.zip')
    grids = list(stage.rglob('us_noaa_g2018u0.tif'))
    if not grids or any(digest(path) != GEOID_SHA256 for path in grids):
        raise ValueError('Missing or unverified bundled Geoid18 grid')
    records = json.loads((stage/'Sources/native-packages.json').read_text(encoding='utf-8'))
    if not isinstance(records, list) or not records:
        raise ValueError('Native package inventory is empty')
    checked = []
    for record in records:
        key = record['name'] + '-' + record['version']
        recipes = stage/'Sources/native-recipes'/key
        if not recipes.is_dir() or not any(p.is_file() for p in recipes.rglob('*')):
            raise ValueError('Missing native build recipe: ' + key)
        license = record.get('license', '') or ''
        if 'GPL' not in license and 'MPL' not in license and record['name'] not in ('libarchive','libgdal-core'):
            continue
        entry = record.get('upstream_source', {})
        included = entry.get('included', '')
        path = (stage/included).resolve()
        if not included or not path.is_relative_to(stage/'Sources/native-upstream') or not path.is_file():
            raise ValueError('Missing native corresponding source: ' + key)
        if digest(path) != entry.get('sha256'):
            raise ValueError('Native corresponding source checksum mismatch: ' + key)
        checked.append(key)
    return dict(status='passed_content_checks', application_source=source,
                geoid_files=[str(p.relative_to(stage)) for p in grids],
                native_packages=len(records), corresponding_sources=checked,
                limits='Content checks only; installer lifecycle and executable acceptance remain separate.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(audit_payload(args.payload), indent=2))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc)+'\n')


if __name__ == '__main__':main()
