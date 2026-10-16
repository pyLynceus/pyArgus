"""Release identity must agree across the app and Windows packaging surfaces."""
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
import pyargus
from pyargus.workspace_layout import WorkspaceLayout

ROOT = Path(__file__).resolve().parents[1]


def test_package_and_installer_identity_agree():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "' + re.escape(pyargus.__version__) + r'"$', project, re.M)
    installer = (ROOT / "packaging/windows/pyArgus.iss").read_text(encoding="utf-8")
    assert '#define AppVersion "' + pyargus.__version__ + '"' in installer
    assert '#define ReleaseDate "' + pyargus.__release_date__ + '"' in installer
    assert "VersionInfoVersion={#AppVersion}.0" in installer
    spec = importlib.util.spec_from_file_location("release_stage", ROOT / "packaging/windows/stage_installer.py")
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    assert stage.APP_VERSION == pyargus.__version__
    assert stage.RELEASE_DATE == pyargus.__release_date__


def test_source_about_shows_release_identity(monkeypatch):
    calls = []
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr("pyargus.workspace_layout.messagebox.showinfo", lambda *a, **k: calls.append(a))
    WorkspaceLayout.about(SimpleNamespace(root=None))
    title, message = calls[0]
    assert title == "About pyArgus"
    assert "pyArgus " + pyargus.__version__ in message
    assert "Release " + pyargus.__release_date__ in message
    assert "Source checkout" in message


@pytest.mark.parametrize("manifest", [None, "broken JSON", [], {"release": "0.2.0-2026-10-16", "source_commit": "abc123"}])
def test_packaged_about_keeps_version_with_missing_or_invalid_manifest(tmp_path, monkeypatch, manifest):
    calls = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pyArgus.exe"))
    if manifest is not None:
        text = manifest if isinstance(manifest, str) else json.dumps(manifest)
        (tmp_path / "build-info.json").write_text(text, encoding="utf-8")
    monkeypatch.setattr("pyargus.workspace_layout.messagebox.showinfo", lambda *a, **k: calls.append(a))
    WorkspaceLayout.about(SimpleNamespace(root=None))
    message = calls[0][1]
    assert "pyArgus " + pyargus.__version__ in message
    assert "Release " + pyargus.__release_date__ in message
    if isinstance(manifest, dict):
        assert "Build " + manifest["release"] in message
        assert "Source abc123" in message
    else:
        assert "Packaged application" in message
