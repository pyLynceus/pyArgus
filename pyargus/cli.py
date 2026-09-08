"""Command line: the commands that are real today.

    pyargus sbet-info trajectory.sbet
    pyargus density cloud.las --cell 2.0
    pyargus qa-report cloud.las --out qa/ --control pts.csv --control-order pnez
    pyargus classify-ground cloud.las --out classified.las --cell 3
    pyargus dtm classified.las --out dtm.asc --cell 3
    pyargus align cloud.las --sbet traj.out --vertical=-29.077 --write fixed.las
    pyargus contours classified.las --out contours.dxf --interval 1

More subcommands arrive as their phases land; nothing appears here
before it works.
"""

import argparse

import numpy as np

import pyargus


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
    points = las.read_points(args.path, fields=("x", "y", "z"))
    dens, _, _ = density.density_grid(points["x"], points["y"], cell=args.cell)
    covered = dens[dens > 0]
    print(f"points:        {points['x'].size}")
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

    traj_time = None
    if args.sbet:
        from pyargus.formats import sbet
        traj_time = sbet.read_sbet(args.sbet)["time"]

    summary = report.generate(
        points, args.out, title=args.title or Path(args.path).name,
        control=control, traj_time=traj_time, ground_class=args.ground_class,
        density_cell=args.density_cell, dz_cell=args.dz_cell,
        dz_limit=args.dz_limit, control_radius=args.radius, units=args.units)

    d = summary["density"]
    print(f"points:  {summary['points']:,} ({summary['ground_points']:,} ground, "
          f"{len(summary['strips'])} strips)")
    if "time_base" in summary:
        tb = summary["time_base"]
        print(f"time:    week {tb['gps_week']}, "
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
            breaks.extend(geojson.read_breaklines_geojson(path))
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


def _cmd_align(args):
    from pathlib import Path

    import laspy

    from pyargus.align import attach, solve_alignment
    from pyargus.formats import crs as crs_mod
    from pyargus.formats import las as las_mod
    from pyargus.formats import sbet as sbet_mod
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
    trajectory = sbet_mod.read_sbet(args.sbet)

    map_crs = args.map_crs
    if map_crs is None:
        with laspy.open(args.path) as reader:
            map_crs = reader.header.parse_crs()
        if map_crs is None:
            raise SystemExit(f"{args.path} declares no CRS; pass --map-crs")
    vertical = args.vertical
    if vertical is not None:
        try:
            vertical = float(vertical)
        except ValueError:
            pass  # a vertical CRS string
    map_e, map_n, map_z = crs_mod.sbet_to_map(
        trajectory, map_crs, vertical=vertical,
        allow_network=args.proj_network)

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
                                         speed_floor=args.speed_floor)
    print(f"attach:  week {attached.gps_week}, heading source "
          f"{attached.heading_source!r} (track error "
          f"{np.degrees(attached.track_error):.1f} deg), "
          f"AGL {attached.agl_median:.0f}, "
          f"nadir median {attached.nadir_median_deg:.1f} deg")
    print(f"strips:  {attached.strip_ids} "
          f"({[b.xyz.shape[0] for b in attached.bundles]} points)")

    result = solve_alignment(
        attached.bundles, solve_boresight=not args.no_boresight,
        offsets=args.offsets, cell=args.cell, min_points=args.min_points)
    deg = np.degrees(result.boresight)
    print(f"solved:  {result.n_observations:,} observations, "
          f"{result.iterations} iterations, patch rms "
          f"{result.rms_before:.3f} -> {result.rms_after:.3f}")
    print(f"boresight: roll {result.boresight[0]:+.6f}  "
          f"pitch {result.boresight[1]:+.6f}  yaw {result.boresight[2]:+.6f} "
          f"rad  ({deg[0]:+.4f}/{deg[1]:+.4f}/{deg[2]:+.4f} deg)")
    for i, sid in enumerate(attached.strip_ids):
        tag = "  (gauge)" if i == 0 else ""
        extra = (f"  de {result.offsets[i, 0]:+.4f}  "
                 f"dn {result.offsets[i, 1]:+.4f}"
                 if args.offsets == "xyz" else "")
        print(f"offset strip {sid}: dz {result.offsets[i, 2]:+.4f}{extra}{tag}")

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
        xyz, skipped = attach.apply_corrections(
            points, trajectory, map_e, map_n, map_z,
            attached.heading_source, result.boresight, offsets_by_sid)
        with laspy.open(args.path) as reader:
            las = reader.read()
        las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        las.write(str(dst))
        note = (f" ({skipped:,} outside the trajectory left unchanged)"
                if skipped else "")
        print(f"wrote:   {dst}{note}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pyargus", description=pyargus.__doc__)
    parser.add_argument("--version", action="version", version=pyargus.__version__)
    sub = parser.add_subparsers(dest="command")

    p_sbet = sub.add_parser("sbet-info", help="summarize an SBET trajectory")
    p_sbet.add_argument("path")
    p_sbet.set_defaults(func=_cmd_sbet_info)

    p_dens = sub.add_parser("density", help="point density summary for a LAS/LAZ file")
    p_dens.add_argument("path")
    p_dens.add_argument("--cell", type=float, default=1.0)
    p_dens.set_defaults(func=_cmd_density)

    p_qa = sub.add_parser("qa-report", help="strip QA report for a LAS/LAZ file")
    p_qa.add_argument("path")
    p_qa.add_argument("--out", required=True, help="output directory")
    p_qa.add_argument("--title", help="report title (default: file name)")
    p_qa.add_argument("--control", action="append",
                      help="control CSV (repeatable)")
    p_qa.add_argument("--control-order", choices=("pnez", "penz"),
                      help="control column order; required with --control")
    p_qa.add_argument("--sbet", help="SBET trajectory for the time-base check")
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
                      help="3D LineString GeoJSON (repeatable); switches "
                           "the surface to a TIN with soft breaklines")
    p_ct.add_argument("--smooth", type=int, default=0,
                      help="Chaikin iterations; drawing polish that moves "
                           "vertices off the measured surface")
    p_ct.set_defaults(func=_cmd_contours)

    p_al = sub.add_parser("align", help="strip alignment against the SBET")
    p_al.add_argument("path")
    p_al.add_argument("--sbet", required=True)
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
    p_al.add_argument("--offsets", choices=("z", "xyz", "none"), default="z")
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

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)
