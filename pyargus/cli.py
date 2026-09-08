"""Command line: the commands that are real today.

    pyargus sbet-info trajectory.sbet
    pyargus density cloud.las --cell 2.0
    pyargus qa-report cloud.las --out qa/ --control pts.csv --control-order pnez
    pyargus classify-ground cloud.las --out classified.las --cell 3
    pyargus dtm classified.las --out dtm.asc --cell 3

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
    m = points["classification"] == args.ground_class
    if not m.any():
        raise SystemExit(f"no class-{args.ground_class} points in {args.path}; "
                         f"classify first or pass --ground-class")
    grid, x_edges, y_edges = dtm.dtm_grid(
        points["x"][m], points["y"][m], points["z"][m], args.cell,
        max_fill=args.max_fill)
    dtm.write_esri_ascii(args.out, grid, x_edges, y_edges)
    finite = grid[np.isfinite(grid)]
    print(f"ground:  {int(m.sum()):,} points -> {grid.shape[0]}x{grid.shape[1]} "
          f"cells at {args.cell:g} ({finite.size:,} with data)")
    print(f"z:       {finite.min():.2f} .. {finite.max():.2f}")
    print(f"wrote:   {args.out}")
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
    p_dtm.set_defaults(func=_cmd_dtm)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)
