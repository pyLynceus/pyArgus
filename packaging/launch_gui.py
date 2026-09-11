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
    from pyargus.formats.breaklines import read_breaklines
    from pyargus.formats.dxf import write_contours_dxf
    from pyargus.surfaces.contours import ContourLine
    from pyargus import stage_preview
    with tempfile.TemporaryDirectory(prefix="pyargus-cad-") as temp:
        path = Path(temp) / "breaklines.dxf"
        lines = [ContourLine(5., np.array([[0.,0.],[1.,1.]]), False, True)]
        write_contours_dxf(path, lines)
        assert read_breaklines(path)[0].shape == (2,3)
        assert stage_preview.contours(lines).shape[2] == 4
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
    from pyargus import project
    import laspy
    from pyproj import CRS
    with tempfile.TemporaryDirectory(prefix="pyargus-project-") as temp:
        paths = []
        for sid in (1, 2):
            cloud = laspy.LasData(laspy.LasHeader(point_format=6, version="1.4"))
            cloud.header.add_crs(CRS("EPSG:6447"))
            cloud.x, cloud.y, cloud.z = np.arange(3.), np.zeros(3), np.ones(3)
            cloud.point_source_id = np.full(3, sid, dtype=np.uint16)
            path = Path(temp) / f"cloud_{sid}.las"
            cloud.write(path); paths.append(str(path))
        spec = project.Project(paths, same_vertical=True)
        saved = Path(temp) / "project.json"; spec.save(saved)
        assert project.load(project.Project.load(saved)).inventory["points"] == 6
        spec.max_points = 1
        report = project.qa(spec, Path(temp) / "large-qa")
        assert report["mode"] == "disk-backed" and report["points"] == 6
    window = tk.Tk()
    window.withdraw()
    app = Application(window)
    # by TYPE, not position: appending a stage broke this assert and
    # the two test files that shared the habit, and pytest does not
    # collect this file so the suite stayed green while it was broken
    assert any(isinstance(stage, AboveStage) for stage in app.stages)
    assert any(type(stage).__name__ == "ColorizeStage"
               for stage in app.stages)
    from pyargus.project_gui import open_project
    project_window = open_project(app)
    project_window.window.withdraw()
    assert project_window.counts.get() == "0 clouds; 0 trajectories"
    from pyargus.viewer3d import Viewer
    viewer = Viewer(window)
    viewer.window.withdraw()
    points = np.array([[0.,0,0],[1,2,3],[3,1,2]])
    viewer.scene = (points, np.full(3,2), np.arange(3), np.zeros(3,dtype=int), 3, None)
    viewer.visible = [tk.BooleanVar(master=viewer.window,value=True)]
    viewer.center = np.ones(3); viewer.span = 4.
    viewer.draw(); viewer.view(40,30)
    assert viewer.photo.width() > 0
    viewer.close()
    window.update_idletasks()
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else main())
