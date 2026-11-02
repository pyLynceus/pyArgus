import importlib.util
import json
from pathlib import Path
import zipfile
import pytest
from devtools import audit_windows_payload as audit

ROOT = Path(__file__).resolve().parents[1]


def bundle(path, extra=()):
    path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path,'w') as archive:
        for name in ['pyArgus/pyproject.toml','pyArgus/LICENSE',*extra]:archive.writestr(name,'source')


@pytest.mark.parametrize('name', ['pyArgus/HANDOFF.md', 'pyArgus/CLAUDE.md',
    'pyArgus/pyargus-job-records/solve.json', 'pyArgus/reference/reports/client.json',
    '../private.txt'])
def test_private_archive_is_refused(tmp_path, name):
    path = tmp_path/'source.zip';bundle(path,[name])
    with pytest.raises(ValueError,match='Private or unsafe'):audit.audit_source_archive(path)


def test_actual_source_bundler_excludes_private_top_level_files(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('stage_installer',ROOT/'packaging/windows/stage_installer.py')
    stage = importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
    source = tmp_path/'checkout';source.mkdir()
    for name in ['HANDOFF.md','CLAUDE.md','LICENSE','pyproject.toml']:(source/name).write_text('text')
    (source/'pyargus').mkdir();(source/'pyargus/__init__.py').write_text('')
    output = tmp_path/'payload';(output/'Sources').mkdir(parents=True)
    monkeypatch.setattr(stage,'ROOT',source)
    monkeypatch.setattr(stage.subprocess,'check_output',lambda *a,**kw:b'HANDOFF.md\0CLAUDE.md\0LICENSE\0pyproject.toml\0pyargus/__init__.py\0')
    stage.source_bundle(output)
    audit.audit_source_archive(output/'Sources/pyArgus-source.zip')


def test_package_discovery_never_includes_job_record_namespace(tmp_path):
    from setuptools import find_namespace_packages
    import ast,re
    include = ast.literal_eval(re.search(r'include = (\[.*\])', (ROOT/'pyproject.toml').read_text())[1])
    for name in ['pyargus','pyargus/core','pyargus-job-records','pyargus-data']:
        (tmp_path/name).mkdir(parents=True,exist_ok=True)
    found = find_namespace_packages(where=str(tmp_path),include=include)
    assert set(found) == {'pyargus','pyargus.core'}


@pytest.fixture
def payload(tmp_path, monkeypatch):
    for name in ['pyArgus.exe','native-pdal/Library/bin/pdal.exe','Licenses/python-packages.json','build-info.json']:
        path = tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
    bundle(tmp_path/'Sources/pyArgus-source.zip')
    grid = tmp_path/'_internal/proj/us_noaa_g2018u0.tif';grid.parent.mkdir(parents=True);grid.write_bytes(b'fixture grid')
    monkeypatch.setattr(audit,'GEOID_SHA256',audit.digest(grid))
    recipe = tmp_path/'Sources/native-recipes/libgdal-core-1';recipe.mkdir(parents=True);(recipe/'meta.yaml').write_text('source recipe')
    source = tmp_path/'Sources/native-upstream/libgdal-core-1/source.tar.gz';source.parent.mkdir(parents=True);source.write_bytes(b'fixture upstream')
    records = [dict(name='libgdal-core',version='1',license='MIT',upstream_source=dict(included=source.relative_to(tmp_path).as_posix(),sha256=audit.digest(source)))]
    (tmp_path/'Sources/native-packages.json').write_text(json.dumps(records))
    return tmp_path,source


def test_complete_payload_content_passes(payload):
    stage,_ = payload
    assert audit.audit_payload(stage)['corresponding_sources'] == ['libgdal-core-1']


def test_missing_or_altered_native_source_refuses_release(payload):
    stage,source = payload
    source.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum mismatch'):audit.audit_payload(stage)
    source.unlink()
    with pytest.raises(ValueError,match='Missing native corresponding source'):audit.audit_payload(stage)
