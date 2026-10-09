"""The frozen-bundle self-test, run by pytest.

`packaging/launch_gui.py --self-test` is the gate the PyInstaller
bundle is checked with, and pytest did not collect it -- so when
appending a stage broke its positional `stages[-1]` assertion, the
whole suite stayed green and only a review panel noticed. A gate
nothing runs is not a gate.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "packaging" / "launch_gui.py"


def test_packaging_self_test_passes(tmp_path):
    pytest.importorskip("laspy")
    tkinter = pytest.importorskip("tkinter")
    try:
        window = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display for Tk")
    window.destroy()
    report=tmp_path/"self-test.json"
    result = subprocess.run([sys.executable, str(GATE), "--self-test", "--self-test-report",str(report)],
                            capture_output=True, text=True, cwd=str(ROOT),
                            timeout=900)
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]

    evidence=json.loads(report.read_text(encoding="utf-8"))
    assert evidence["passed"] and evidence["multicore"]["workers"]==2
    assert evidence["multicore"]["peak_tasks"]==2 and "device" in evidence["gpu"]
