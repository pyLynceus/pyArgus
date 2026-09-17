import os
import sys

# Tests run against the working tree whether or not the package is
# installed; the repo root goes first on the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# GUI tests must never write or resume a user's real workspace history.
import pytest

@pytest.fixture(autouse=True)
def isolated_workspace_history(tmp_path, monkeypatch):
    monkeypatch.setenv("PYARGUS_WORKSPACE_AUTOSAVE", str(tmp_path / "session.argus.json"))
    yield
    import gc
    gc.collect()
