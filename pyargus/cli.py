"""Command line: the two commands that are real today.

    pyargus sbet-info trajectory.sbet
    pyargus density cloud.las --cell 2.0

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

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)
