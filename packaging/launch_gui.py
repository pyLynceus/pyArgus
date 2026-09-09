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
    window = tk.Tk()
    window.withdraw()
    app = Application(window)
    assert isinstance(app.stages[-1], AboveStage)
    window.update_idletasks()
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else main())
