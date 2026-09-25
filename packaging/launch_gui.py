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
        from pyargus.sections import extract_section, export_section
        from pyargus.review import load_review, review_rows
        section = extract_section(paths, [0., 0.], [2., 0.], 1., limit=10)
        assert section.matched == 6 and len(section.points) == 6
        export_section(section, Path(temp) / "section.csv")
        job_path = next(Path(temp).glob("large-qa.job-*.json"))
        review = load_review(job_path)
        assert review_rows(review)[0]["after"] == "completed"
    from pyargus.section_navigation import stepped_corridor
    sa,sb=stepped_corridor([0.,0.],[2.,0.],1.,10.,1)
    np.testing.assert_allclose(sa,[0.,10.])
    np.testing.assert_allclose(sb,[2.,10.])
    # Both noise routes, the screen's guard and the COPC-safe writer, in
    # the frozen bundle: the first build to carry noise-cut, merge and
    # the screening guard, whose modules only the CLI and Classify reach.
    from pyargus.classify import job as ground_job, noise as noise_mod
    from pyargus.formats import merge as merge_mod
    from pyargus.formats.las import drop_copc_records
    with tempfile.TemporaryDirectory(prefix="pyargus-noise-") as temp:
        rng = np.random.default_rng(5)
        n = 4000
        noisy = laspy.LasData(laspy.LasHeader(point_format=6, version="1.4"))
        noisy.x = rng.uniform(0., 60., n); noisy.y = rng.uniform(0., 60., n)
        z = 100. + rng.normal(0., .05, n); z[:3] = -500.
        noisy.z = z
        src = Path(temp) / "noisy.las"; noisy.write(src)
        quiet = dict(cell=1., window=6., threshold=.5, log=lambda _: None)
        try:    # a ceiling inside the site is the site, not its noise
            ground_job.classify_ground_whole(src, Path(temp) / "no.las",
                                             noise_max=99., **quiet)
        except ValueError as exc:
            assert "not gross noise" in str(exc)
        else:
            raise AssertionError("a screen that caught the site ran")
        screened = ground_job.classify_ground_whole(
            src, Path(temp) / "ground.las", noise_min=0., **quiet)
        assert screened["noise_screened"] == 3
        cut = noise_mod.noise_cut(src, Path(temp) / "cut.las", z_min=0.,
                                  max_fraction=.01, log=lambda _: None)
        assert cut["flagged_low"] == 3
        header = laspy.read(src).header
        assert drop_copc_records(header) is header
        assert callable(merge_mod.merge_clouds)
    window = tk.Tk()
    window.withdraw()
    app = Application(window)
    classify = next(s for s in app.stages if type(s).__name__ == "ClassifyStage")
    assert classify.noise_max_fraction.get() == "0.001"
    # Exercise the new editor and record-preserving exporter in the frozen app.
    from pyargus.editing_gui import SectionEditor
    with tempfile.TemporaryDirectory(prefix="pyargus-edit-") as temp:
        source = Path(temp) / "input.las"
        cloud.write(source)
        edit_section = extract_section([source], [0., 0.], [2., 0.], 1.)
        from pyargus.section_cache_store import CacheStore
        from pyargus.section_cache import extract as cached_section
        cache_store=CacheStore(Path(temp)/'section-cache')
        cache_store.build([source])
        cached=cached_section([cache_store.path(source)],[0.,0.],[2.,0.],1.)
        np.testing.assert_array_equal(cached.points,edit_section.points)
        np.testing.assert_array_equal(cached.point_indices,edit_section.point_indices)
        cache_store.clear()

        editor = SectionEditor(window, edit_section)
        editor.window.withdraw()
        editor.selected = np.arange(3)
        editor.target.set("2"); editor.assign()
        assert editor.session.changed == 3
        editor.undo(); assert editor.session.changed == 0
        editor.redo()
        result = editor.session.export(Path(temp) / "edited.laz")
        assert result["changed"] == 3 and result["status"] == "verified"
        editor.saved_classes = editor.session.classes.copy()
        assert editor.close()
    # by TYPE, not position: appending a stage broke this assert and
    # the two test files that shared the habit, and pytest does not
    # collect this file so the suite stayed green while it was broken
    assert any(isinstance(stage, AboveStage) for stage in app.stages)
    assert any(type(stage).__name__ == "ColorizeStage"
               for stage in app.stages)
    from pyargus.workspace_state import Tracker
    with tempfile.TemporaryDirectory(prefix="pyargus-workspace-") as temp:
        state=Tracker(); job=state.begin("Inspect", {}, [])
        state.finish(job,"Needs review"); state.decide("Inspect","Accepted","Packaging smoke test")
        saved=Path(temp)/"workspace.json";state.save(saved)
        assert Tracker.load(saved).status("Inspect")=="Accepted"
    assert app.canvas is app.workspace.viewer.canvas
    assert not isinstance(app.workspace.viewer.window,tk.Toplevel)
    from pyargus.project_gui import open_project
    project_window = open_project(app)
    project_window.window.update_idletasks()
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
    from pyargus.review_gui import ReviewWorkspace
    workspace = ReviewWorkspace(window)
    workspace.window.withdraw()
    workspace.record = review
    workspace.refresh()
    assert workspace.tree.get_children()
    workspace.profile.set(section.points[:, [3, 2]],
                          np.tile([58, 190, 255], (len(section.points), 1)), 5.)
    assert workspace.profile.photo.width() > 0
    workspace.close()
    window.update_idletasks()
    window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv else main())
