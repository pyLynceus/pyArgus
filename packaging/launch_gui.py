"""Frozen desktop entry and a repeatable packaging smoke test."""
import sys
import os
from pathlib import Path


def configure_bundled_runtime():
    """Use the installer-private PDAL without changing the machine PATH."""
    if not getattr(sys, "frozen", False):
        return None
    candidate = Path(sys.executable).resolve().parent / "native-pdal/Library/bin/pdal.exe"
    if candidate.is_file():
        # An operator's explicit override still takes precedence.
        os.environ.setdefault("PDAL_EXE", str(candidate))
        return candidate
    return None


BUNDLED_PDAL = configure_bundled_runtime()
from pyargus.gui import main


def self_test(*, require_gpu=False, report=None):
    if report is None: report={}
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
    if BUNDLED_PDAL is not None:
        from pyargus.formats.copc import find_pdal, write_copc
        assert Path(find_pdal()).is_file()
        import laspy
        from pyproj import CRS
        with tempfile.TemporaryDirectory(prefix="pyargus-installed-copc-") as temp:
            source = Path(temp) / "sample.las"
            target = Path(temp) / "sample.copc.laz"
            header = laspy.LasHeader(point_format=6, version="1.4")
            header.add_crs(CRS("EPSG:6447"))
            cloud = laspy.LasData(header)
            cloud.x = np.linspace(2400000., 2400010., 64)
            cloud.y = np.linspace(400000., 400005., 64)
            cloud.z = np.linspace(1000., 1001., 64)
            cloud.add_extra_dim(laspy.ExtraBytesParams(name="Amplitude", type=np.float32))
            cloud.Amplitude = np.arange(64, dtype=np.float32)
            cloud.write(source)
            write_copc(source, target, timeout=60)
            check = laspy.read(target)
            assert len(check.points) == 64
            assert "Amplitude" in check.point_format.extra_dimension_names
            assert check.header.parse_crs().to_epsg() == 6447
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
        qa_report = project.qa(spec, Path(temp) / "large-qa")
        assert qa_report["mode"] == "disk-backed" and qa_report["points"] == 6
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
    from pyargus.anaglyph import render
    stereo=render(np.array([[0.,0.,1.]]),np.array([[255,255,255]]),10,80,60,[0,0],6)
    assert stereo.shape==(60,80,3)
    assert not np.array_equal(stereo[:,:,0],stereo[:,:,1])
    window = tk.Tk()
    window.withdraw()
    app = Application(window)
    layout=app.workspace.layout
    assert layout.mode=='Review' and not app.task_panel.winfo_manager()
    assert tuple(layout.menus)==('File','View','Tools','Help')
    layout.set_mode('Process');assert app.task_panel.winfo_manager()=='pack'
    layout.set_mode('Deliver');assert layout.deliver.winfo_manager()=='pack'
    layout.set_mode('Review');assert not app.task_panel.winfo_manager()
    from pyargus.review_shortcuts import parse_classes
    assert parse_classes('Vegetation')==(3,4,5)
    app.workspace.class_filter.set('Noise');app.workspace.filter()
    assert app.workspace.viewer.class_filter==(7,18)
    app.workspace.class_filter.set('All');app.workspace.filter()
    assert not app.workspace.review.advanced.winfo_manager()
    assert layout.shortcuts.context()['workspace']
    from pyargus.section_interaction import drag_corridor
    moved=drag_corridor('move',[2400000,400000],[2400100,400000],3,[0,0],[5,7])
    assert moved[0].tolist()==[2400005,400007]
    layout.apply_preset('Full 3D');assert not app.workspace.show_dock.get()
    layout.apply_preset('Comparison review')
    assert app.workspace.show_dock.get() and app.workspace.viewer.mode.get()=='Dataset'
    assert not app.workspace.review.busy and not layout.corridor.enabled.get()
    saved_layout=layout.snapshot();layout.project_settings();layout.restore(saved_layout)
    assert layout.snapshot()==saved_layout
    assert app.workspace.notes.frame in [window.nametowidget(t) for t in app.workspace.tabs.tabs()]
    assert app.workspace.notes.model.data['last_review'] is None
    assert app.workspace.overview.frame in [window.nametowidget(t) for t in app.workspace.tabs.tabs()]
    assert app.workspace.overview.summary['kind']=='add'
    assert app.workspace.comparison.frame in [window.nametowidget(t) for t in app.workspace.tabs.tabs()]
    from pyargus.version_comparison import preferences,role_visibility
    assert preferences()['role']=='Result' and role_visibility('Original')==[True,False]
    # Exercise the new editor and record-preserving exporter in the frozen app.
    from pyargus.editing_gui import SectionEditor
    with tempfile.TemporaryDirectory(prefix="pyargus-edit-") as temp:
        source = Path(temp) / "input.las"
        cloud.write(source)
        # Verify the actual comparison worker and scan-free GUI switches in the bundle.
        import time
        w=app.workspace;v=w.viewer;c=w.comparison
        result_cloud=Path(temp)/'result.las';cloud.write(result_cloud)
        w.add_files([str(source)])
        def comparison_wait(predicate):
            until=time.monotonic()+20
            while time.monotonic()<until:
                window.update();w.poll();time.sleep(.02)
                if predicate():return
            raise AssertionError('Frozen comparison timed out')
        comparison_wait(lambda:not v.busy and w.review.scene is v.scene)
        original_camera=v.camera_state();original_inputs=list(w.project_panel.clouds)
        c.original.set(str(source.resolve()));c.result.set(str(result_cloud.resolve()));c.confirmed.set(True)
        c.prepare();comparison_wait(lambda:c.pending is None and not v.busy)
        assert c.info and c.info['provenance'].startswith('Manual pair')
        assert v.camera_state()==original_camera and str(result_cloud.resolve()) in v.review_only_paths
        scene=v.scene;launch=v.launch
        def unexpected_scan(*args,**kwargs):raise AssertionError('Comparison switch attempted a scan')
        v.launch=unexpected_scan
        try:
            for role in ('Original','Both','Result'):
                c.switch(role);assert [var.get() for var in v.visible]==role_visibility(role)
                assert v.scene is scene and v.camera_state()==original_camera
            c.restore_previous();assert w.project_panel.clouds==original_inputs
        finally:v.launch=launch
        # The rest of this smoke test expects an empty input project.
        w.project_panel.clouds.clear();w.project_panel.refresh()
        w.tracker.data['layers'].clear();app.cloud_path.set('')
        v.scene=None;v.overview_scene=None;v.paths=();v.visible=[];v.review_only_paths.clear()
        w.review.scene=None;w.review.loaded_paths=();w.review.loaded_identities=[]
        c.restore(None);w.refresh_layers()
        # Export through the same GUI runner and inspect the resulting offline archive.
        from pyargus.review_package_gui import canvas_png
        import zipfile,json,hashlib
        p=w.package_export;p.include_previews.set(False)
        p.start(Path(temp)/'review-package.zip')
        comparison_wait(lambda:p.pending is None and not app.runner.running)
        assert p.result and not w.tracker.data['jobs']
        with zipfile.ZipFile(p.last_path) as package:
            assert package.testzip() is None and 'report.html' in package.namelist()
            package_summary=json.loads(package.read('package.json'))
            assert not package_summary['scope']['external_payloads_included']
            for member in json.loads(package.read('manifest.json'))['files']:
                assert hashlib.sha256(package.read(member['path'])).hexdigest()==member['sha256']
        p.include_previews.set(True);w.tracker.data['layers'].clear();w.refresh_layers()
        from pyargus.project_overview import read_extents,coordinate_groups,map_transform,map_pixels,map_world
        extent_rows,_=read_extents([source]);assert extent_rows[0]['points']==3
        assert len(coordinate_groups(extent_rows))==1
        transform=map_transform(extent_rows[0]['bounds'],250,150)
        np.testing.assert_allclose(map_world(map_pixels([[1.,0.]],transform),transform),[[1.,0.]])
        from pyargus.review_memory import ReviewMemory,context_errors
        from pyargus.job_manifest import identity
        note_view=dict(schema_version=1,inputs=[identity(source)],crs=CRS(6447).to_wkt(),
            camera=dict(center=[1.,0.,1.],pan_units=[0.,0.],yaw=25.,pitch=45.,zoom=1.,span=3.),
            display=dict(mode='Classification',classes='Ground',line='All',stereo=False,depth=2.,swap=False),
            visible=[True],section=None,section_source=str(source.resolve()),confirmed=False,route=None,
            profile=dict(mode='Dataset',line='All',exaggeration=5.),layout=layout.snapshot(),details=False,references=[])
        memory=ReviewMemory();memory.save_view('Frozen smoke view',note_view);issue=memory.issue('Frozen smoke issue',note_view)
        memory.update_issue(issue['id'],'Frozen smoke issue','Noise','In review','Operator note')
        assert len(ReviewMemory(memory.data).data['issues'])==1 and not context_errors(note_view)
        edit_section = extract_section([source], [0., 0.], [2., 0.], 1.)
        from pyargus.section_cache_store import CacheStore
        from pyargus.section_cache import extract as cached_section
        cache_store=CacheStore(Path(temp)/'section-cache')
        cache_store.build([source])
        cached=cached_section([cache_store.path(source)],[0.,0.],[2.,0.],1.)
        np.testing.assert_array_equal(cached.points,edit_section.points)
        np.testing.assert_array_equal(cached.point_indices,edit_section.point_indices)
        from pyargus.viewport_cache import extract as viewport_extract
        viewport=viewport_extract(cache_store,[source],[0.,0.,1.],0,90,(-1,3,-1,1),stereo_depth=2)
        assert viewport[4]==3
        cache_store.clear()
        from pyargus.features import Features, export_dxf
        from pyargus.job_manifest import identity
        features=Features();fid=features.new('Smoke wall','Wall top')
        for xyz in ([0.,0.,1.],[2.,0.,1.]):
            features.vertex(fid,xyz,identity(source),'EPSG:6447')
        features.metadata(fid,'Smoke wall','Wall top','Accepted')
        export_dxf(features.items,Path(temp)/'features.dxf')
        from pyargus.linework import read_dxf
        layers,skipped=read_dxf(Path(temp)/'features.dxf','EPSG:6447')
        app.workspace.linework.imported(layers,skipped)
        assert len(app.workspace.linework.layers)==1
        assert app.workspace.layer_tree.parent('dxf:'+layers[0]['id'])=='group:Linework'
        route=app.workspace.review.route
        route.activate(layers[0],0)
        assert route.state['segment']==0
        from pyargus.route_sections import corridor_at
        a,b,total=corridor_at(layers[0]['segments'][0],1.,2.,1.)
        np.testing.assert_allclose(a,[1.,1.]);np.testing.assert_allclose(b,[1.,-1.])
        route.stop()
        app.workspace.features.restore(features)
        assert app.workspace.features.model.get(fid)['status']=='Accepted'


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
    if getattr(sys,'frozen',False):
        import moderngl,glcontext
    viewer = Viewer(window)
    viewer.window.withdraw()
    points = np.array([[0.,0,0],[1,2,3],[3,1,2]])
    viewer.scene = (points, np.full(3,2), np.arange(3), np.zeros(3,dtype=int), 3, None)
    viewer.visible = [tk.BooleanVar(master=viewer.window,value=True)]
    viewer.center = np.ones(3); viewer.span = 4.
    viewer.draw(); viewer.view(40,30)
    assert viewer.photo.width() > 0
    if require_gpu:
        assert viewer.gpu is not None, viewer.render_note.get()
    if viewer.gpu is not None:
        device=viewer.gpu.device
        viewer.stereo.set(True);viewer.draw();assert viewer.photo.width()>0
        assert viewer.gpu is not None, viewer.render_note.get()
        report["gpu"]={"device":device,"mono":True,"stereo":True}
    else:
        report["gpu"]={"device":None,"fallback":viewer.render_note.get()}
    viewer.renderer.set('CPU');viewer.change_renderer();assert viewer.photo.width()>0
    viewer.close()
    from pyargus.classify.job import classify_ground_tiled
    with tempfile.TemporaryDirectory(prefix="pyargus-multicore-") as temp:
        x,y=np.meshgrid(np.arange(31.),np.arange(31.))
        sample=laspy.LasData(laspy.LasHeader(point_format=6,version="1.4"))
        sample.header.add_crs(CRS("EPSG:6447"))
        sample.x=x.ravel()+2400000.;sample.y=y.ravel()+400000.
        sample.z=1000.+.02*x.ravel()
        sample.return_number=np.ones(x.size,dtype=np.uint8)
        sample.number_of_returns=np.ones(x.size,dtype=np.uint8)
        src=Path(temp)/"input.las";out=Path(temp)/"classified.las";sample.write(src)
        result=classify_ground_tiled(src,out,cell=1.,window=2.,tile_size=10.,workers=2,
            memory_mb=512,log=lambda _:None)
        assert result["total"]==x.size and result["workers"]==2 and result["peak_tasks"]==2
        assert len(laspy.read(out).points)==x.size
        report["multicore"]={"workers":2,"peak_tasks":result["peak_tasks"],"points":int(x.size)}
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
    if "--self-test" in sys.argv:
        import argparse,json,traceback
        parser=argparse.ArgumentParser()
        parser.add_argument("--self-test",action="store_true")
        parser.add_argument("--require-gpu",action="store_true")
        parser.add_argument("--self-test-report",type=Path)
        args=parser.parse_args()
        result={}
        try:
            code=self_test(require_gpu=args.require_gpu,report=result)
            result["passed"]=code==0
        except Exception:
            code=1;result["passed"]=False;result["error"]=traceback.format_exc()
        if args.self_test_report:
            args.self_test_report.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        raise SystemExit(code)
    raise SystemExit(main())
