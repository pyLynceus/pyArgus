"""Frozen desktop entry and a repeatable packaging smoke test."""
import sys
from pyargus.gui import main


def self_test():
    import tempfile
    from pathlib import Path
    import numpy as np
    import tkinter as tk
    from pyargus.classify import above
    from pyargus.gui import Application, AboveStage
    rng = np.random.default_rng(17)
    matrix = rng.normal(size=(200, 8))
    labels = np.where(matrix[:, 0] > 0, 5, 6)
    model = above.train(matrix, labels, n_estimators=5)
    model.feature_cell, model.xyz_units = 2.0, "metres"
    with tempfile.TemporaryDirectory(prefix="pyargus-smoke-") as temp:
        path = Path(temp) / "forest.joblib"
        above.save(model, path)
        restored = above.load(path)
        assert restored.feature_cell == 2.0
        assert restored.xyz_units == "metres"
        assert np.array_equal(above.predict(model, matrix), above.predict(restored, matrix))
    # Ensure native trajectory modules are also present in the frozen bundle.
    import struct
    from pyargus.formats import trj, trajectory
    with tempfile.TemporaryDirectory(prefix="pyargus-trj-") as temp:
        path = Path(temp) / "trajectory.trj"
        header = bytearray(1376)
        struct.pack_into("<8s4i", header, 0, b"TSCANTRJ", 20010715, 1376, 1, 64)
        struct.pack_into("<2d2i", header, 104, 436024721., 436024721., 0, 12)
        path.write_bytes(header + struct.pack("<7d4B2h", 436024721., 1., 2., 3., 90., 0., 0., 0, 0, 0, 0, 0, 0))
        assert trj.read_trj(path).line_number == 12
        assert trajectory.read_times(path, trj_time="same")[1] == "same"
    window = tk.Tk()
    window.withdraw()
    app = Application(window)
    assert isinstance(app.stages[-1], AboveStage)
    window.update_idletasks()
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else main())
