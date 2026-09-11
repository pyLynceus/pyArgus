"""Command line: the commands that are real today.

    pyargus sbet-info trajectory.sbet
    pyargus info cloud.las
    pyargus copc cloud.las --out cloud.copc.laz
    pyargus density cloud.las --cell 2.0
    pyargus qa-report cloud.las --out qa/ --control pts.csv --control-order pnez
    pyargus classify-ground cloud.las --out classified.las --cell 3
    pyargus train-above labeled.las --out forest.joblib
    pyargus classify-above classified.las --model forest.joblib --out full.las
    pyargus dtm classified.las --out dtm.asc --cell 3
    pyargus align cloud.las --sbet traj.out --vertical=-29.077 --write fixed.las
    pyargus control-by-strip strips/*.las --control pts.csv --control-order pnez
    pyargus contours classified.las --out contours.dxf --interval 1
    pyargus colorize cloud.las --eo eo_Photos.csv --images Flight_dir --out rgb.las
    pyargus gui

More subcommands arrive as their phases land; nothing appears here
before it works.
"""

import argparse

import numpy as np

import pyargus

# LAS point formats that carry red/green/blue (2/3/5 legacy, 7/8/10
# in the 1.4 family); 6 and 9 deliberately do not
_RGB_POINT_FORMATS = frozenset({2, 3, 5, 7, 8, 10})


def _cmd_trajectory_info(args):
    from pyargus.formats import trajectory, trj
    if trajectory.is_trj(args.path):
        print(trj.read_trj(args.path).summary())
        return 0
    return _cmd_sbet_info(args)


def _cmd_sbet_info(args):
    from pyargus.formats import sbet
    data = sbet.read_sbet(args.path)
    t = data["time"]
    rate = (data.shape[0] - 1) / (t[-1] - t[0]) if data.shape[0] > 1 else float("nan")
    print(f"records:   {data.shape[0]}")
    print(f"gps time:  {t[0]:.3f} .. {t[-1]:.3f}  ({t[-1] - t[0]:.1f} s)")
    print(f"rate:      {rate:.1f} Hz")
    print(f"altitude:  {data['alt'].min():.2f} .. {data['alt'].max():.2f} m")
    return 0


def _cmd_density(args):
    from pyargus.formats import las
    from pyargus.qa import density
    # the header fixes the grid, so this never holds more than one
    # chunk -- a 350M-point delivery is a few hundred MB, not 20 GB
    info = las.cloud_info(args.path)

    def stream():
        return las.iter_points(args.path, fields=("x", "y"),
                               chunk_size=args.chunk_size)

    if args.rescan:
        mins, maxs = density.scan_extent(stream())
        print(f"rescanned:     extent from the points, not the header")
    else:
        mins, maxs = info["mins"][:2], info["maxs"][:2]
    try:
        dens, _, _ = density.density_grid_streamed(
            stream(), mins, maxs, cell=args.cell)
    except ValueError as exc:
        raise SystemExit(f"{exc}  (pass --rescan to take the extent from "
                         f"the points, at the cost of one extra pass)")
    covered = dens[dens > 0]
    if covered.size == 0:
        raise SystemExit("no cell received a point; the extent and the "
                         "data do not overlap")
    print(f"points:        {info['point_count']}")
    print(f"cell size:     {args.cell} (data units)")
    print(f"covered cells: {covered.size} of {dens.size}")
    print(f"density/unit2: median {np.median(covered):.2f}, "
          f"p5 {np.percentile(covered, 5):.2f}, p95 {np.percentile(covered, 95):.2f}")
    return 0


def _cmd_qa_report(args):
    from pathlib import Path

    from pyargus.formats import las
    from pyargus.qa import report

    if args.control and not args.control_order:
        raise SystemExit("--control-order is required with --control; the "
                         "column order is never guessed (pnez or penz)")

    fields = ["x", "y", "z", "classification", "point_source_id"]
    if args.sbet:
        fields.append("gps_time")
    points = las.read_points(args.path, fields=tuple(fields))

    control = None
    if args.control:
        from pyargus.formats import control as control_mod
        control = control_mod.read_control_csvs(args.control, args.control_order)

    traj_time, time_mode = None, "week"
    if args.sbet:
        from pyargus.formats.trajectory import read_times
        traj_time, time_mode = read_times(args.sbet, trj_time=args.trj_time)

    summary = report.generate(
        points, args.out, title=args.title or Path(args.path).name,
        control=control, traj_time=traj_time, time_mode=time_mode, ground_class=args.ground_class,
        density_cell=args.density_cell, dz_cell=args.dz_cell,
        dz_limit=args.dz_limit, control_radius=args.radius, units=args.units)

    d = summary["density"]
    print(f"points:  {summary['points']:,} ({summary['ground_points']:,} ground, "
          f"{len(summary['strips'])} strips)")
    if "time_base" in summary:
        tb = summary["time_base"]
        clock_label = f"week {tb['gps_week']}" if tb['gps_week'] is not None else "same stored timestamps"
        print(f"time:    {clock_label}, "
              f"{100 * tb['fraction_inside']:.2f}% inside trajectory")
    print(f"density: median {d['median']:.2f} pts/{args.units}^2 "
          f"(p5 {d['p5']:.2f}, p95 {d['p95']:.2f})")
    for p in summary["strip_dz"]:
        print(f"dz {p['a']}-{p['b']}:  median {p['median']:+.3f}  "
              f"rmse {p['rmse']:.3f}  p95|dz| {p['p95_abs']:.3f}  "
              f"({p['cells']} cells)")
    if "control" in summary:
        c = summary["control"]
        if "median" in c:
            print(f"control: n {c['n']}  median {c['median']:+.3f}  "
                  f"nmad {c['nmad']:.3f}  rmse {c['rmse_z']:.3f} {args.units} "
                  f"({len(c['skipped'])} skipped)")
        else:
            print(f"control: no marks with local ground returns "
                  f"({len(c['skipped'])} skipped)")
    print(f"report:  {summary['report']}")
    return 0


def _cmd_classify_ground(args):
    from pathlib import Path

    import laspy

    from pyargus.classify import ground

    src, dst = Path(args.path), Path(args.out)
    if src.resolve() == dst.resolve():
        raise SystemExit("refusing to overwrite the input cloud; --out must "
                         "be a new file")
    if dst.exists() and not args.force:
        raise SystemExit(f"{dst} exists; pass --force to replace it")

    with laspy.open(str(src)) as reader:
        las = reader.read()
    x = np.asarray(las.x)
    y = np.asarray(las.y)
    z = np.asarray(las.z)

    # Only returns that can see the ground are candidates: last returns
    # when the file carries return numbers, everything otherwise.
    try:
        eligible = (np.asarray(las.return_number)
                    == np.asarray(las.number_of_returns))
    except AttributeError:
        eligible = np.ones(x.size, dtype=bool)

    result = ground.smrf(
        x[eligible], y[eligible], z[eligible], cell=args.cell,
        slope=args.slope, window=args.window, threshold=args.threshold,
        scalar=args.scalar, low_cut=args.low_cut)

    classification = np.ones(x.size, dtype=np.uint8)  # 1: processed, unclassified
    idx = np.flatnonzero(eligible)
    classification[idx[result.ground]] = 2
    las.classification = classification
    las.write(str(dst))

    n_ground = int(result.ground.sum())
    print(f"points:  {x.size:,} ({int(eligible.sum()):,} last-return candidates)")
    print(f"ground:  {n_ground:,} ({100.0 * n_ground / x.size:.1f}% of cloud)")
    print(f"cells:   {int(result.object_cells.sum()):,} object, "
          f"{int(result.low_cells.sum()):,} low-outlier")
    print(f"wrote:   {dst}")
    return 0


def _cmd_dtm(args):
    from pyargus.formats import las
    from pyargus.surfaces import dtm

    points = las.read_points(args.path, fields=("x", "y", "z", "classification"))
    if args.dsm:
        m = np.ones(points["x"].size, dtype=bool)
        grid, x_edges, y_edges = dtm.dsm_grid(
            points["x"], points["y"], points["z"], args.cell,
            max_fill=args.max_fill)
    else:
        m = points["classification"] == args.ground_class
        if not m.any():
            raise SystemExit(f"no class-{args.ground_class} points in {args.path}; "
                             f"classify first or pass --ground-class")
        grid, x_edges, y_edges = dtm.dtm_grid(
            points["x"][m], points["y"][m], points["z"][m], args.cell,
            max_fill=args.max_fill)
    dtm.write_esri_ascii(args.out, grid, x_edges, y_edges)
    finite = grid[np.isfinite(grid)]
    label = "points" if args.dsm else "ground"
    print(f"{label}:  {int(m.sum()):,} points -> {grid.shape[0]}x{grid.shape[1]} "
          f"cells at {args.cell:g} ({finite.size:,} with data)")
    print(f"z:       {finite.min():.2f} .. {finite.max():.2f}")
    print(f"wrote:   {args.out}")
    return 0




def _cmd_train_above(args):
    from pathlib import Path

    from pyargus.classify import above, features
    from pyargus.formats import las

    if Path(args.out).exists() and not args.force:
        raise SystemExit(f"{args.out} exists; pass --force to replace it")
    points = las.read_points(
        args.path, fields=("x", "y", "z", "classification",
                           "return_number", "number_of_returns"))
    ground = points["classification"] == 2
    noise = points["classification"] == 7
    matrix, above_index, valid = features.point_features(
        points, ground, ignore_mask=noise, cell=args.cell)
    labels = points["classification"][above_index]
    try:
        classes = tuple(int(c) for c in args.classes.split(",") if c.strip())
    except ValueError:
        raise SystemExit(f"--classes must be integers separated by commas, "
                         f"got {args.classes!r}")
    if not classes:
        raise SystemExit("--classes named no classes")
    usable = valid & np.isin(labels, classes)
    if not usable.any():
        raise SystemExit(f"no labeled points in classes {classes}")
    model = above.train(matrix[usable], labels[usable],
                        notes=f"trained on {Path(args.path).name}")
    above.save(model, args.out)
    counts = dict(zip(*np.unique(labels[usable], return_counts=True)))
    print(f"trained: {int(usable.sum()):,} labeled points "
          f"{ {int(k): int(v) for k, v in counts.items()} }")
    ranked = sorted(zip(features.FEATURE_NAMES,
                        model.forest.feature_importances_),
                    key=lambda pair: -pair[1])
    print("features: " + "  ".join(f"{n}={v:.3f}" for n, v in ranked))
    print(f"wrote:   {args.out}")
    return 0


def _cmd_classify_above(args):
    from pathlib import Path

    import laspy

    from pyargus.classify import above

    src, dst = Path(args.path), Path(args.out)
    if src.resolve() == dst.resolve():
        raise SystemExit("refusing to overwrite the input cloud; --out must "
                         "be a new file")
    if dst.exists() and not args.force:
        raise SystemExit(f"{dst} exists; pass --force to replace it")

    model = above.load(args.model)
    with laspy.open(str(src)) as reader:
        las_data = reader.read()
    points = {name: np.asarray(las_data[name]) for name in
              ("x", "y", "z", "classification", "return_number",
               "number_of_returns")}
    ground = points["classification"] == 2
    if not ground.any():
        raise SystemExit("no class-2 ground in the cloud; run "
                         "classify-ground first")
    # noise is EXCLUDED from the features (it poisons its neighbors'
    # cell statistics), not merely relabeled after prediction
    noise = points["classification"] == 7
    classification, unclassifiable = above.classify_above(
        points, ground, model, ignore_mask=noise, cell=args.cell)
    classification[noise] = 7
    las_data.classification = classification
    las_data.write(str(dst))
    u, c = np.unique(classification, return_counts=True)
    print(f"classes: { {int(k): int(v) for k, v in zip(u, c)} }")
    if unclassifiable:
        print(f"no HAG:  {unclassifiable:,} points left class 1 (beyond "
              f"ground coverage)")
    print(f"model:   {model.notes or args.model}")
    print(f"wrote:   {dst}")
    return 0


def _cmd_contours(args):
    from pathlib import Path

    from pyargus.formats import dxf, geojson, las
    from pyargus.surfaces import contours as contours_mod
    from pyargus.surfaces import dtm, tin

    out = Path(args.out)
    if out.suffix.lower() not in (".dxf", ".geojson", ".json"):
        raise SystemExit(f"--out must end in .dxf or .geojson, got {out.name}")

    points = las.read_points(args.path, fields=("x", "y", "z", "classification"))
    m = points["classification"] == args.ground_class
    if not m.any():
        raise SystemExit(f"no class-{args.ground_class} points in {args.path}; "
                         f"classify first or pass --ground-class")

    if args.breaklines:
        breaks = []
        for path in args.breaklines:
            from pyargus.formats.breaklines import read_breaklines
            breaks.extend(read_breaklines(path))
        surface = tin.build_tin(
            np.column_stack([points["x"][m], points["y"][m], points["z"][m]]),
            breaklines=breaks, cell_hint=args.cell)
        grid, x_edges, y_edges = surface.grid(args.cell)
        # A TIN interpolates across every interior void; mask it back to
        # data coverage so a lake does not grow contours (--max-fill
        # means the same thing here as on the DTM path).
        from pyargus.core import gridding
        covered = gridding.coverage_mask(
            surface.points[:, 0], surface.points[:, 1], x_edges, y_edges,
            max_distance=args.max_fill)
        grid = np.where(covered, grid, np.nan)
        source = (f"TIN of {int(m.sum()):,} ground points + "
                  f"{surface.n_breakline_points:,} breakline vertices "
                  f"({len(breaks)} lines, soft enforcement)")
    else:
        grid, x_edges, y_edges = dtm.dtm_grid(
            points["x"][m], points["y"][m], points["z"][m], args.cell,
            max_fill=args.max_fill)
        source = f"mean-ground DTM of {int(m.sum()):,} points"

    lines = contours_mod.contour_grid(grid, x_edges, y_edges, args.interval,
                                      index_every=args.index_every)
    if not lines:
        raise SystemExit("surface relief is smaller than one interval; "
                         "no contours to write")
    if args.smooth:
        for line in lines:
            line.xy = contours_mod.smooth_chaikin(line.xy, args.smooth,
                                                  closed=line.closed)

    if out.suffix.lower() == ".dxf":
        dxf.write_contours_dxf(out, lines)
    else:
        geojson.write_contours_geojson(out, lines)

    levels = sorted({line.level for line in lines})
    total = sum(np.linalg.norm(np.diff(line.xy, axis=0), axis=1).sum()
                for line in lines)
    print(f"surface: {source}, {args.cell:g}-unit cells")
    print(f"levels:  {len(levels)} ({levels[0]:g} .. {levels[-1]:g} at "
          f"{args.interval:g}; index every {args.index_every})")
    print(f"lines:   {len(lines)} ({sum(1 for l in lines if l.is_index)} "
          f"index), total length {total:,.0f}"
          + (f", smoothed x{args.smooth} (vertices move OFF the measured "
             f"surface)" if args.smooth else ""))
    print(f"wrote:   {out}")
    return 0



def _cmd_control_by_strip(args):
    from pyargus.formats import control as control_mod
    from pyargus.qa import control_by_strip as cbs

    if not args.control_order:
        raise SystemExit("--control-order is required; the column order is "
                         "never guessed (pnez or penz)")
    ids, ce, cn, cz = control_mod.read_control_csvs(args.control,
                                                    args.control_order)
    gathered = cbs.gather_near_marks(
        args.paths, ce, cn, radius=args.radius,
        ground_class=args.ground_class)
    deco = cbs.decompose(gathered, ids, ce, cn, cz,
                         min_points=args.min_points)

    strips = sorted({c.strip for c in deco.cells})
    lookup = {(c.mark, c.strip): c for c in deco.cells}
    print("mark      knownZ   " + "  ".join(f"{s[:6]:>6}" for s in strips))
    for mark in sorted({c.mark for c in deco.cells}):
        cells = []
        for s in strips:
            cell = lookup.get((mark, s))
            cells.append(f"{cell.dz_median:+.2f}" if cell else "   . ")
        print(f"{ids[mark]:8s} {cz[mark]:8.2f}  "
              + "  ".join(f"{c:>6}" for c in cells))

    print("\n[per-strip bias: median dz over its marks]")
    for strip, stats in deco.per_strip().items():
        print(f"  {strip}: n {stats['n']:3d}  median {stats['median']:+.3f}"
              f"  nmad {stats['nmad']:.3f}")

    print("\n[per-mark: agreement across strips]")
    print("  mark      strips  mean_dz  spread  plane_dz  reading")
    for mark_id, stats in deco.per_mark().items():
        if (stats["n_strips"] < 2 and abs(stats["mean_dz"]) < 0.1
                and stats["spread"] < 0.1):
            continue
        reading = ("POSITION-LOCKED" if stats["n_strips"] >= 2
                   and stats["spread"] < 0.06
                   and abs(stats["mean_dz"]) > 0.1
                   else "strip-dependent" if stats["spread"] >= 0.1
                   else "")
        print(f"  {mark_id:8s}  {stats['n_strips']:4d}   "
              f"{stats['mean_dz']:+.3f}   {stats['spread']:.3f}   "
              f"{stats['dz_plane']:+.3f}   {reading}")
    print("\nposition-locked = every strip reads the same wrong value: "
          "look at the mark, the survey,\nor a pre-applied adjustment -- "
          "not at strip alignment. plane_dz is grade-corrected.")
    return 0


def _cmd_align(args):
    from pathlib import Path

    import laspy

    from pyargus.align import attach, solve_alignment
    from pyargus.formats import las as las_mod
    from pyargus.qa import overlap

    if args.write:
        dst = Path(args.write)
        if dst.resolve() == Path(args.path).resolve():
            raise SystemExit("refusing to overwrite the input cloud; --write "
                             "must be a new file")
        if dst.exists() and not args.force:
            raise SystemExit(f"{dst} exists; pass --force to replace it")

    points = las_mod.read_points(
        args.path, fields=("x", "y", "z", "gps_time", "point_source_id",
                           "classification"))
    from pyargus.formats.trajectory import load_alignment, is_trj

    map_crs = args.map_crs
    if map_crs is None:
        with laspy.open(args.path) as reader:
            map_crs = reader.header.parse_crs()
        if map_crs is None and not is_trj(args.sbet):
            raise SystemExit(f"{args.path} declares no CRS; pass --map-crs")
    vertical = args.vertical
    if vertical is not None:
        try:
            vertical = float(vertical)
        except ValueError:
            pass  # a vertical CRS string
    trajectory, (map_e, map_n, map_z), time_mode = load_alignment(
        args.sbet, map_crs, vertical=vertical, allow_network=args.proj_network,
        trj_time=args.trj_time, trj_confirmed=args.trj_confirmed)

    if args.control and not args.control_order:
        raise SystemExit("--control-order is required with --control; the "
                         "column order is never guessed (pnez or penz)")
    control = None
    if args.control:
        from pyargus.formats import control as control_mod
        _, ce, cn, cz = control_mod.read_control_csvs(args.control,
                                                      args.control_order)
        control = np.column_stack([ce, cn, cz])

    if args.any_class:
        mask = np.ones(points["x"].size, dtype=bool)
    else:
        mask = points["classification"] == args.ground_class
        if not mask.any():
            raise SystemExit(f"no class-{args.ground_class} points to solve "
                             f"on; classify first or pass --any-class")
    sub = {k: points[k][mask] for k in ("x", "y", "z", "gps_time",
                                        "point_source_id")}
    attached = attach.bundles_from_cloud(sub, trajectory, map_e, map_n, map_z,
                                         speed_floor=args.speed_floor, time_mode=time_mode)
    clock_label = f"week {attached.gps_week}" if attached.gps_week is not None else "same stored timestamps"
    print(f"attach:  {clock_label}, heading source "
          f"{attached.heading_source!r} (track error "
          f"{np.degrees(attached.track_error):.1f} deg), "
          f"AGL {attached.agl_median:.0f}, "
          f"nadir median {attached.nadir_median_deg:.1f} deg")
    print(f"strips:  {attached.strip_ids} "
          f"({[b.xyz.shape[0] for b in attached.bundles]} points)")

    if args.drift_spacing is not None and not args.no_boresight:
        print("caution: solving boresight and drift TOGETHER lets pitch "
              "leak into the per-strip curves over smooth terrain -- and "
              "a block that needs drift corrections is poor calibration "
              "data even in constant mode. Calibrate boresight on clean "
              "lines, --write that correction, then solve drift on the "
              "result with --no-boresight.")
    result = solve_alignment(
        attached.bundles, solve_boresight=not args.no_boresight,
        offsets=args.offsets, cell=args.cell, min_points=args.min_points,
        control=control, control_weight=args.control_weight,
        control_radius=args.control_radius,
        drift_spacing=args.drift_spacing,
        drift_stiffness=args.drift_stiffness)
    if result.absolute:
        print(f"datum:   ABSOLUTE, anchored by {result.n_control} control "
              f"observations; control rms "
              f"{result.control_rms_before:.3f} -> "
              f"{result.control_rms_after:.3f}")
    deg = np.degrees(result.boresight)
    print(f"solved:  {result.n_observations:,} observations, "
          f"{result.iterations} iterations, patch rms "
          f"{result.rms_before:.3f} -> {result.rms_after:.3f}")
    print(f"boresight: roll {result.boresight[0]:+.6f}  "
          f"pitch {result.boresight[1]:+.6f}  yaw {result.boresight[2]:+.6f} "
          f"rad  ({deg[0]:+.4f}/{deg[1]:+.4f}/{deg[2]:+.4f} deg)")
    for i, sid in enumerate(attached.strip_ids):
        tag = "  (gauge)" if i == 0 and not result.absolute else ""
        if result.drift is not None:
            lo, hi = result.drift.span(i)
            print(f"drift strip {sid}: mean dz "
                  f"{result.offsets[i, 2]:+.4f}  span {lo:+.4f} .. "
                  f"{hi:+.4f} over {len(result.drift.node_times[i])} "
                  f"nodes{tag}")
        else:
            extra = (f"  de {result.offsets[i, 0]:+.4f}  "
                     f"dn {result.offsets[i, 1]:+.4f}"
                     if args.offsets == "xyz" else "")
            print(f"offset strip {sid}: dz "
                  f"{result.offsets[i, 2]:+.4f}{extra}{tag}")

    def dz_map(xa, xb):
        return overlap.strip_dz(
            {"x": xa[:, 0], "y": xa[:, 1], "z": xa[:, 2]},
            {"x": xb[:, 0], "y": xb[:, 1], "z": xb[:, 2]}, cell=args.cell)

    corrected = result.corrected(attached.bundles)
    for i in range(len(attached.bundles)):
        for j in range(i + 1, len(attached.bundles)):
            before = dz_map(attached.bundles[i].xyz, attached.bundles[j].xyz)
            if before.overlap_cells == 0:
                continue
            after = dz_map(corrected[i], corrected[j])
            print(f"dz {attached.strip_ids[i]}-{attached.strip_ids[j]}: "
                  f"median {before.summary()['median']:+.3f} -> "
                  f"{after.summary()['median']:+.3f}   rmse "
                  f"{before.summary()['rmse']:.3f} -> "
                  f"{after.summary()['rmse']:.3f}")

    if args.write:
        offsets_by_sid = {sid: result.offsets[i]
                          for i, sid in enumerate(attached.strip_ids)}
        drift_by_sid = None
        if result.drift is not None:
            drift_by_sid = {sid: (result.drift.node_times[i],
                                  result.drift.values[i])
                            for i, sid in enumerate(attached.strip_ids)}
        xyz, skipped = attach.apply_corrections(
            points, trajectory, map_e, map_n, map_z,
            attached.heading_source, result.boresight, offsets_by_sid,
            drift_by_sid=drift_by_sid, time_mode=time_mode)
        # the corrected coordinates are already in hand; streaming the
        # copy means the original record is never materialized a second
        # time (this command used to read the whole file twice)
        def place(_points, start):
            stop = start + _points["x"].size
            block = xyz[start:stop]
            return {"x": block[:, 0], "y": block[:, 1], "z": block[:, 2]}

        las_mod.stream_update(args.path, dst, place, fields=("x",))
        note = (f" ({skipped:,} outside the trajectory left unchanged)"
                if skipped else "")
        print(f"wrote:   {dst}{note}")
    return 0


def _cmd_colorize(args):
    from pathlib import Path

    import laspy

    from pyargus.formats import eo as eo_mod
    from pyargus.formats import las as las_mod
    from pyargus.imagery import camera as camera_mod  # noqa: F401
    from pyargus.imagery import colorize as colorize_mod

    dst = Path(args.out)
    if dst.resolve() == Path(args.path).resolve():
        raise SystemExit("refusing to overwrite the input cloud; --out "
                         "must be a new file")
    if dst.exists() and not args.force:
        raise SystemExit(f"{dst} exists; pass --force to replace it")

    eo = eo_mod.read_eo_csv(args.eo)
    image_paths = colorize_mod.find_images(args.images)
    if not image_paths:
        raise SystemExit(f"no images found under {args.images}")

    # one camera per role tag, calibration auto-found beside that
    # camera's own images (LP360 writes a sidecar per frame)
    tag_sample = {}
    for name in eo["filename"]:
        found = image_paths.get(name.lower())
        if found is not None:
            tag_sample.setdefault(eo_mod.camera_tag(name), found)
    if not tag_sample:
        raise SystemExit("none of the EO rows' images exist under "
                         f"{args.images}; wrong --images path?")
    cameras = {}
    for tag, sample in tag_sample.items():
        # the sample image's OWN sidecar, not the folder's first: a
        # flattened multi-camera delivery would otherwise give every
        # camera the same lens
        cal = Path(args.cal) if args.cal else camera_mod.find_cal(sample)
        if cal is None:
            raise SystemExit(
                f"no .cal calibration sidecar found for {sample.name} "
                f"and no --cal given; refusing to project through an "
                f"uncalibrated lens (the distortion is ~30 px at the "
                f"frame corner)")
        try:
            cameras[tag] = camera_mod.read_cal(
                cal, quarter_turns=args.quarter_turns, name=str(tag))
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        cam = cameras[tag]
        print(f"camera {tag or '-'}: {cal.name}  f {cam.focal_mm:.3f} mm "
              f"({cam.focal_px:.1f} px)  pp ({cam.cx_px:+.1f}, "
              f"{cam.cy_px:+.1f}) px  {cam.width_px}x{cam.height_px}  "
              f"quarter turns {args.quarter_turns}")

    points = las_mod.read_points(args.path, fields=("x", "y", "z"))
    xyz = np.column_stack([points["x"], points["y"], points["z"]])

    # the units/CRS trap arrives as geometry: EO that does not overlap
    # the cloud, or sits below the ground, is a frame mismatch
    lo = xyz[:, :2].min(axis=0)
    hi = xyz[:, :2].max(axis=0)
    olo = eo["origin"][:, :2].min(axis=0)
    ohi = eo["origin"][:, :2].max(axis=0)
    if (ohi < lo).any() or (olo > hi).any():
        raise SystemExit(
            "the EO positions do not overlap the cloud horizontally -- "
            "that is what a wrong unit (the LP360 header says [m] even "
            "when the values are survey feet) or a different CRS looks "
            "like. Refusing to colorize.")
    agl = float(np.median(eo["origin"][:, 2]) - np.median(xyz[:, 2]))
    if agl <= 0:
        raise SystemExit(
            f"the EO heights sit {-agl:.0f} map units BELOW the cloud's "
            f"ground -- a vertical datum or unit mismatch. Refusing to "
            f"colorize.")
    print(f"eo:      {len(eo['filename'])} rows, flying height "
          f"~{agl:.0f} above the cloud median")

    def progress(done, total, name):
        print(f"  ... {done} of {total} images ({name})", flush=True)

    try:
        rgb, stats = colorize_mod.colorize(
            xyz, eo, cameras, image_paths, neighbors=args.neighbors,
            occlusion_tol=args.occlusion_tol, progress=progress)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    pct = 100.0 * stats["n_colored"] / stats["n_points"]
    print(f"colored: {stats['n_colored']:,} of {stats['n_points']:,} "
          f"points ({pct:.1f}%) from {stats['n_images_used']} images")
    print(f"skipped: {stats['n_occluded']:,} occluded, "
          f"{stats['n_unseen']:,} seen by no nearby photo"
          + (f"; {stats['n_eo_dropped']} EO rows had no image file"
             if stats["n_eo_dropped"] else ""))
    # The overlap and AGL gates catch a frame mismatch that separates
    # the two datasets, but not one that merely SCALES them (metres
    # written over survey feet keeps the boxes overlapping on a
    # site-local grid). Coverage is what that looks like from here.
    if pct < args.min_coverage:
        raise SystemExit(
            f"only {pct:.1f}% of the cloud got a color, below "
            f"--min-coverage {args.min_coverage}. That is what a unit or "
            f"datum mismatch between the EO and the cloud looks like "
            f"(metres vs survey feet, ellipsoidal vs orthometric "
            f"heights), or imagery from the wrong flight. Nothing was "
            f"written; lower --min-coverage to colorize a subset "
            f"deliberately.")
    if pct < 50.0:
        print("caution: less than half the cloud got a color. That is "
              "normal when the imagery covers only part of the block -- "
              "and it is also what a vertical datum or unit mismatch "
              "looks like, since a flying height in metres over a "
              "survey-feet cloud shrinks every footprint by 3.28. Check "
              "the flying height above against the mission.")

    source_format = las_mod.cloud_info(args.path)["point_format"]
    target_format = None
    if source_format not in _RGB_POINT_FORMATS:
        target_format = 7
        print(f"format:  point format {source_format} carries no RGB; "
              f"converting to 7")

    def paint(_points, start):
        block = rgb[start:start + _points["x"].size]
        return {"red": block[:, 0], "green": block[:, 1],
                "blue": block[:, 2]}

    las_mod.stream_update(args.path, dst, paint, fields=("x",),
                          point_format=target_format)
    print(f"wrote:   {dst}")
    return 0


def _cmd_copc(args):
    from pathlib import Path

    from pyargus.formats import copc as copc_mod

    dst = Path(args.out)
    if dst.exists() and not args.force:
        raise SystemExit(f"{dst} exists; pass --force to replace it")
    try:
        result = copc_mod.write_copc(args.path, dst, pdal=args.pdal)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    print(f"pdal:    {result['pdal']}")
    print(f"points:  {result['point_count']:,}"
          + (f"  extra {', '.join(result['extra_dims'])}"
             if result["extra_dims"] else ""))
    print(f"crs:     {result['crs'] or 'none declared'}")
    print(f"size:    {result['size_ratio']:.2f}x the source")
    print(f"wrote:   {dst}")
    return 0


def _cmd_info(args):
    from pyargus.formats import las

    info = las.cloud_info(args.path)
    span = info["maxs"] - info["mins"]
    # ~39 bytes per point for the default field set; the point of this
    # command is to answer "can I open this at all" before trying
    whole_gb = info["point_count"] * 39 / 1e9
    print(f"points:     {info['point_count']:,}")
    print(f"format:     point format {info['point_format']}, "
          f"LAS {info['version']}"
          + ("  (COPC)" if info["is_copc"] else ""))
    print(f"extent:     {info['mins'][0]:,.2f} .. {info['maxs'][0]:,.2f} E"
          f"  ({span[0]:,.1f} wide)")
    print(f"            {info['mins'][1]:,.2f} .. {info['maxs'][1]:,.2f} N"
          f"  ({span[1]:,.1f} tall)")
    print(f"            {info['mins'][2]:,.2f} .. {info['maxs'][2]:,.2f} Z"
          f"  ({span[2]:,.1f} range)")
    print(f"scales:     {info['scales']}")
    if info["extra_dims"]:
        print(f"extra:      {', '.join(info['extra_dims'])}")
    print(f"crs:        {info['crs'].name if info['crs'] else 'none declared'}")
    print(f"whole-read: ~{whole_gb:.1f} GB of RAM for the default fields; "
          f"streaming commands need one chunk instead")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="pyargus", description=pyargus.__doc__)
    parser.add_argument("--version", action="version", version=pyargus.__version__)
    sub = parser.add_subparsers(dest="command")

    p_traj = sub.add_parser("trajectory-info", help="inspect native TRJ or SBET")
    p_traj.add_argument("path")
    p_traj.set_defaults(func=_cmd_trajectory_info)

    p_sbet = sub.add_parser("sbet-info", help="summarize an SBET trajectory")
    p_sbet.add_argument("path")
    p_sbet.set_defaults(func=_cmd_sbet_info)

    p_info = sub.add_parser(
        "info", help="what the LAS/LAZ header says, without reading points")
    p_info.add_argument("path")
    p_info.set_defaults(func=_cmd_info)

    p_copc = sub.add_parser(
        "copc", help="rewrite a cloud as COPC (needs pdal; laspy reads "
                     "COPC but cannot write it)")
    p_copc.add_argument("path")
    p_copc.add_argument("--out", required=True,
                        help="output path, conventionally *.copc.laz")
    p_copc.add_argument("--pdal", help="path to the pdal executable "
                                       "(default: PATH, PDAL_EXE, then "
                                       "a QGIS/OSGeo4W install)")
    p_copc.add_argument("--force", action="store_true",
                        help="replace --out if it exists")
    p_copc.set_defaults(func=_cmd_copc)

    p_dens = sub.add_parser("density", help="point density summary for a LAS/LAZ file")
    p_dens.add_argument("path")
    p_dens.add_argument("--cell", type=float, default=1.0)
    p_dens.add_argument("--rescan", action="store_true",
                        help="take the extent from the points instead of "
                             "the header (one extra streaming pass); use "
                             "when the header does not describe its own "
                             "points")
    p_dens.add_argument("--chunk-size", type=int, default=1_000_000,
                        help="points held at once while streaming "
                             "(default 1M; below ~250k it gets slower "
                             "without saving much)")
    p_dens.set_defaults(func=_cmd_density)

    p_qa = sub.add_parser("qa-report", help="strip QA report for a LAS/LAZ file")
    p_qa.add_argument("path")
    p_qa.add_argument("--out", required=True, help="output directory")
    p_qa.add_argument("--title", help="report title (default: file name)")
    p_qa.add_argument("--control", action="append",
                      help="control CSV (repeatable)")
    p_qa.add_argument("--control-order", choices=("pnez", "penz"),
                      help="control column order; required with --control")
    p_qa.add_argument("--trajectory", "--sbet", dest="sbet", help="TRJ or SBET trajectory")
    p_qa.add_argument("--trj-time", choices=("same", "week"), help="TRJ timestamps: same as LAS, or GPS week seconds")
    p_qa.add_argument("--ground-class", type=int, default=2)
    p_qa.add_argument("--density-cell", type=float, default=3.0)
    p_qa.add_argument("--dz-cell", type=float, default=6.0)
    p_qa.add_argument("--dz-limit", type=float, default=0.25,
                      help="dZ map color scale, +/- this value")
    p_qa.add_argument("--radius", type=float, default=3.0,
                      help="control gather radius")
    p_qa.add_argument("--units", default="ft")
    p_qa.set_defaults(func=_cmd_qa_report)

    p_cls = sub.add_parser("classify-ground",
                           help="SMRF ground classification to a NEW file")
    p_cls.add_argument("path")
    p_cls.add_argument("--out", required=True,
                       help="output LAS/LAZ (never the input)")
    p_cls.add_argument("--force", action="store_true",
                       help="replace --out if it exists")
    p_cls.add_argument("--cell", type=float, default=1.0)
    p_cls.add_argument("--slope", type=float, default=0.15)
    p_cls.add_argument("--window", type=float, default=18.0,
                       help="largest opening radius, map units")
    p_cls.add_argument("--threshold", type=float, default=0.5,
                       help="point-to-DEM elevation threshold, map units")
    p_cls.add_argument("--scalar", type=float, default=1.25,
                       help="threshold growth per unit of DEM slope")
    p_cls.add_argument("--low-cut", type=float, default=None,
                       help="discard low-outlier cells deeper than this below "
                            "the opened inverted surface (map units)")
    p_cls.set_defaults(func=_cmd_classify_ground)

    p_dtm = sub.add_parser("dtm", help="mean-ground DTM as ESRI ASCII")
    p_dtm.add_argument("path")
    p_dtm.add_argument("--out", required=True, help="output .asc")
    p_dtm.add_argument("--cell", type=float, default=1.0)
    p_dtm.add_argument("--ground-class", type=int, default=2)
    p_dtm.add_argument("--max-fill", type=int, default=10,
                       help="max gap fill distance, cells (0 disables)")
    p_dtm.add_argument("--dsm", action="store_true",
                       help="highest surface from ALL returns instead of "
                            "mean ground")
    p_dtm.set_defaults(func=_cmd_dtm)

    p_ta = sub.add_parser("train-above",
                          help="train the above-ground forest on a "
                               "labeled cloud")
    p_ta.add_argument("path")
    p_ta.add_argument("--out", required=True, help="model file (.joblib)")
    p_ta.add_argument("--classes", default="3,4,5,6",
                      help="labels to learn (default 3,4,5,6)")
    p_ta.add_argument("--cell", type=float, default=3.0)
    p_ta.add_argument("--force", action="store_true")
    p_ta.set_defaults(func=_cmd_train_above)

    p_ca = sub.add_parser("classify-above",
                          help="apply a trained forest to a "
                               "ground-classified cloud")
    p_ca.add_argument("path")
    p_ca.add_argument("--model", required=True)
    p_ca.add_argument("--out", required=True,
                      help="output LAS/LAZ (never the input)")
    p_ca.add_argument("--cell", type=float, default=3.0)
    p_ca.add_argument("--force", action="store_true")
    p_ca.set_defaults(func=_cmd_classify_above)

    p_ct = sub.add_parser("contours", help="contour lines to DXF/GeoJSON")
    p_ct.add_argument("path")
    p_ct.add_argument("--out", required=True,
                      help="output .dxf or .geojson")
    p_ct.add_argument("--interval", type=float, default=1.0)
    p_ct.add_argument("--index-every", type=int, default=5,
                      help="every Nth level is an index contour")
    p_ct.add_argument("--cell", type=float, default=3.0)
    p_ct.add_argument("--ground-class", type=int, default=2)
    p_ct.add_argument("--max-fill", type=int, default=10)
    p_ct.add_argument("--breaklines", action="append",
                      help="DXF or 3D LineString GeoJSON (repeatable); switches "
                           "the surface to a TIN with soft breaklines")
    p_ct.add_argument("--smooth", type=int, default=0,
                      help="Chaikin iterations; drawing polish that moves "
                           "vertices off the measured surface")
    p_ct.set_defaults(func=_cmd_contours)

    p_cb = sub.add_parser(
        "control-by-strip",
        help="decompose control misses per strip (misalignment vs "
             "position-locked)")
    p_cb.add_argument("paths", nargs="+",
                      help="strip LAS/LAZ files (or one multi-strip cloud)")
    p_cb.add_argument("--control", action="append", required=True)
    p_cb.add_argument("--control-order", choices=("pnez", "penz"))
    p_cb.add_argument("--radius", type=float, default=3.0)
    p_cb.add_argument("--min-points", type=int, default=8)
    p_cb.add_argument("--ground-class", type=int, default=None,
                      help="filter to one class (default: all points -- "
                           "right for unclassified strips)")
    p_cb.set_defaults(func=_cmd_control_by_strip)

    p_al = sub.add_parser("align", help="strip alignment against a trajectory")
    p_al.add_argument("path")
    p_al.add_argument("--trajectory", "--sbet", dest="sbet", required=True)
    p_al.add_argument("--trj-time", choices=("same", "week"))
    p_al.add_argument("--trj-confirmed", action="store_true", help="confirm matching LAS XYZ frame/units/datum and grid-north clockwise heading, right-wing-down roll, nose-up pitch")
    p_al.add_argument("--map-crs", help="delivery CRS (default: from the LAS)")
    p_al.add_argument("--vertical",
                      help="vertical story: a vertical CRS (e.g. EPSG:6360) "
                           "or a geoid undulation N in meters (H = h - N; "
                           "N is NEGATIVE across CONUS, e.g. -29.077)")
    p_al.add_argument("--proj-network", action="store_true",
                      help="let PROJ fetch geoid grids from its CDN")
    p_al.add_argument("--ground-class", type=int, default=2,
                      help="class used for solving (default 2)")
    p_al.add_argument("--any-class", action="store_true",
                      help="solve on all points, not one class")
    p_al.add_argument("--control", action="append",
                      help="surveyed marks CSV (repeatable); lifts the "
                           "strip-0 gauge and anchors the ABSOLUTE datum")
    p_al.add_argument("--control-order", choices=("pnez", "penz"),
                      help="control column order; required with --control")
    p_al.add_argument("--control-weight", type=float, default=10.0)
    p_al.add_argument("--control-radius", type=float, default=6.0)
    p_al.add_argument("--offsets", choices=("z", "xyz", "none"), default="z")
    p_al.add_argument("--drift-spacing", type=float, default=None,
                      help="solve a piecewise-linear vertical correction in "
                           "time per strip (node spacing, seconds) instead "
                           "of constant offsets -- for GNSS wander WITHIN "
                           "a line")
    p_al.add_argument("--drift-stiffness", type=float, default=1.0,
                      help="smoothness weight on the drift curve's rate "
                           "of change (spacing-invariant; default 1.0, "
                           "must be positive)")
    p_al.add_argument("--no-boresight", action="store_true")
    p_al.add_argument("--speed-floor", type=float, default=None,
                      help="standstill cutoff for the heading-vs-track "
                           "check, map units/s (default: 0.25 * p95 speed)")
    p_al.add_argument("--cell", type=float, default=6.0)
    p_al.add_argument("--min-points", type=int, default=6)
    p_al.add_argument("--write", help="apply corrections, write a NEW cloud")
    p_al.add_argument("--force", action="store_true",
                      help="replace --write target if it exists")
    p_al.set_defaults(func=_cmd_align)

    p_col = sub.add_parser(
        "colorize", help="paint the cloud from oriented imagery "
                         "(LP360/pyLynceus EO)")
    p_col.add_argument("path")
    p_col.add_argument("--eo", required=True,
                       help="LP360-style EO CSV (eo_Photos_*.csv, or "
                            "pyLynceus adjusted_eo.csv)")
    p_col.add_argument("--images", required=True,
                       help="imagery directory, searched recursively; "
                            "filenames matched case-insensitively")
    p_col.add_argument("--cal",
                       help="calibration .cal sidecar for ALL cameras "
                            "(default: auto-find one beside each "
                            "camera's images)")
    p_col.add_argument("--quarter-turns", type=int, default=3,
                       help="stored-image grid rotation vs the photo "
                            "frame (TrueView 660: 3)")
    p_col.add_argument("--neighbors", type=int, default=8,
                       help="camera footprints considered per point")
    p_col.add_argument("--occlusion-tol", type=float, default=3.0,
                       help="map units; a point deeper than its pixel "
                            "cell's nearest by more than this stays "
                            "uncolored rather than painted through")
    p_col.add_argument("--min-coverage", type=float, default=5.0,
                       help="percent of points that must get a color "
                            "before anything is written; a unit or datum "
                            "mismatch shows up here (default 5)")
    p_col.add_argument("--out", required=True)
    p_col.add_argument("--force", action="store_true",
                       help="replace --out if it exists")
    p_col.set_defaults(func=_cmd_colorize)

    from pyargus.project_cli import register as register_project_commands
    register_project_commands(sub)

    p_gui = sub.add_parser(
        "gui", help="open the desktop application (tkinter; no extra "
                    "dependency)")
    p_gui.set_defaults(func=lambda args: __import__(
        "pyargus.gui", fromlist=["main"]).main())
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)
