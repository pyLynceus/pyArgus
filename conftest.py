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


# CLI commands write their job record beside the output, or in the current
# directory for solve-only and refused invocations; a test must never leave
# one in the checkout, so every test_cli* module runs in its own scratch
# directory.
@pytest.fixture(autouse=True)
def cli_tests_run_in_a_scratch_directory(request, tmp_path, monkeypatch):
    if request.module.__name__.rpartition(".")[2].startswith("test_cli"):
        monkeypatch.chdir(tmp_path)
    yield


def _checkout_records():
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyargus-job-records")
    return set(os.listdir(folder)) if os.path.isdir(folder) else set()


def pytest_sessionstart(session):
    session.config._pyargus_records_before = _checkout_records()


def pytest_sessionfinish(session, exitstatus):
    leaked = sorted(_checkout_records() - session.config._pyargus_records_before)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if leaked and reporter is not None:
        reporter.write_line(f"WARNING: {len(leaked)} job record(s) were written into the checkout's "
                            f"pyargus-job-records during this run: {', '.join(leaked[:4])}", red=True)
