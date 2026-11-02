"""The release-content contract against the payloads on disk (review item 8, F-16, F-17, F-19).

Both 0.2.0 Windows payloads must fail the content gate today: neither carries
the native package inventory and copyleft sources, and the 16 October source
archive carries private notes. Their manifests must still verify, so a
payload can be told apart from a copy that drifted. Build outputs are not
part of the checkout, so each real-payload case skips where its folder is
absent; the synthetic cases always run.
"""
import json
import os
from pathlib import Path

import pytest

from devtools import audit_windows_payload as audit
from devtools import payload_manifest

ROOT = Path(__file__).resolve().parents[1]
PAYLOADS = {'0.2.0-2026-10-16': dict(private_source=True),
            '0.2.0-control-coverage-2026-10-19': dict(private_source=False)}


def stage_for(build):
    stage = ROOT / 'dist' / build / 'pyArgus'
    if not (stage / 'payload-manifest.json').is_file():
        pytest.skip(f'payload {build} is not on this machine')
    return stage


@pytest.mark.parametrize('build', sorted(PAYLOADS))
def test_both_shipped_payloads_fail_the_content_gate_today(build):
    stage = stage_for(build)
    with pytest.raises(ValueError, match='Missing payload file: Sources/native-packages.json'):
        audit.audit_payload(stage)
    archive = stage / 'Sources/pyArgus-source.zip'
    if PAYLOADS[build]['private_source']:
        with pytest.raises(ValueError, match='Private or unsafe'):
            audit.audit_source_archive(archive)
    else:
        assert audit.audit_source_archive(archive)['members'] > 100


@pytest.mark.parametrize('build', sorted(PAYLOADS))
def test_shipped_payload_manifests_verify(build):
    stage = stage_for(build)
    result = payload_manifest.verify_manifest(stage, full=bool(os.environ.get('PYARGUS_PAYLOAD_FULL_HASH')))
    assert result['status'] == 'verified', result
    assert result['exe_matches_build_info'] is True and not result['private']
    assert result['hashed'] >= 3 and result['version'] == '0.2.0'
    assert result['build'] is None or result['build'] in build      # the 16 October manifest predates the build key


def synthetic_payload(root):
    files = {'pyArgus.exe': b'exe bytes', 'build-info.json': b'',
             'Sources/pyArgus-source.zip': b'zip bytes', '_internal/lib.pyd': b'lib'}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / 'build-info.json').write_text(json.dumps(dict(exe_sha256=payload_manifest.digest(root / 'pyArgus.exe'))))
    entries = [dict(path=name, bytes=(root / name).stat().st_size, sha256=payload_manifest.digest(root / name))
               for name in files]
    (root / 'payload-manifest.json').write_text(json.dumps(dict(version='0.2.0', build='test', files=entries)))


def test_manifest_verification_passes_then_catches_drift(tmp_path):
    synthetic_payload(tmp_path)
    result = payload_manifest.verify_manifest(tmp_path, full=True)
    assert result['status'] == 'verified' and result['hashed'] == 4 and result['exe_matches_build_info'] is True
    (tmp_path / '_internal/lib.pyd').write_bytes(b'lib!')           # same size, other bytes
    (tmp_path / 'HANDOFF.md').write_text('private')                 # arrived by copy-forward
    (tmp_path / 'Sources/pyArgus-source.zip').unlink()
    result = payload_manifest.verify_manifest(tmp_path, full=True)
    assert result['status'] == 'failed'
    assert result['mismatched'] == ['_internal/lib.pyd'] and result['missing'] == ['Sources/pyArgus-source.zip']
    assert result['private'] == ['HANDOFF.md'] and result['unlisted'] == ['HANDOFF.md']
