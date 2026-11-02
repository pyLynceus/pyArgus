"""Linux GUI, CLI and delivered-runtime verification entry."""
import multiprocessing
multiprocessing.freeze_support()
import argparse
import json
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    if sys.argv[1:2] == ["--cli"]:
        from pyargus.cli import main
        sys.argv.pop(1)
        raise SystemExit(main())
    if sys.argv[1:] == ["--version"]:
        from pyargus import __version__
        print(__version__)
        raise SystemExit(0)
    if "--self-test" in sys.argv:
        import traceback
        from launch_gui import self_test
        import launch_gui
        from pyargus.formats.copc import find_pdal
        pdal = find_pdal()
        # Exercise the system PDAL integration on Linux as well as bundled paths.
        launch_gui.BUNDLED_PDAL = Path(pdal) if pdal else None
        parser = argparse.ArgumentParser()
        parser.add_argument("--self-test", action="store_true")
        parser.add_argument("--require-gpu", action="store_true")
        parser.add_argument("--self-test-report", type=Path, required=True)
        args = parser.parse_args()
        report = {"platform": "linux", "pdal": pdal}
        try:
            code = self_test(require_gpu=args.require_gpu, report=report)
            report["passed"] = code == 0
            report["copc_verified"] = bool(pdal)
        except Exception:
            code = 1
            report.update(passed=False, error=traceback.format_exc())
        args.self_test_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(code)
    from pyargus.gui import main
    raise SystemExit(main())
