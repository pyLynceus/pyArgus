"""The strip-QA report: one call, one folder, one HTML page.

``generate`` takes a points dict (as ``formats.las.read_points``
returns), optional control and trajectory, and writes into ``out_dir``:

* ``report.html`` -- self-contained (maps embedded), openable anywhere
* ``density.png`` + ``.pgw`` and ``dz_<a>-<b>.png`` + ``.pgw`` -- the
  same maps as GIS-loadable rasters beside the delivery

It returns the numbers it printed as a dict, so tests and the
Summerville reference run assert on data rather than scraping HTML.
The control comparison quoted is the local-median measure (see
``qa.checkpoints.local_median_residuals``); ASPRS statistics are
computed over the same testable marks.
"""

import base64
import datetime
import html as html_mod
from pathlib import Path

import numpy as np

import pyargus
from pyargus.qa import checkpoints, density, overlap, raster


def generate(points, out_dir, *, title, control=None, traj_time=None,
             ground_class=2, density_cell=3.0, dz_cell=6.0, dz_min_points=3,
             dz_limit=0.25, control_radius=3.0, control_min_neighbours=5,
             units="ft", time_mode="week"):
    """Write the QA report for one cloud; returns the summary dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"title": title, "points": int(points["x"].size), "units": units}
    sections = []

    # --- cloud overview ------------------------------------------------
    extent = {k: (float(points[k].min()), float(points[k].max()))
              for k in ("x", "y", "z")}
    summary["extent"] = extent
    strip_ids = np.unique(points["point_source_id"])
    ground = points["classification"] == ground_class
    summary["ground_points"] = int(ground.sum())
    per_strip = []
    for sid in strip_ids:
        m = points["point_source_id"] == sid
        per_strip.append({"strip": int(sid), "points": int(m.sum()),
                          "ground": int((m & ground).sum())})
    summary["strips"] = per_strip

    # --- time base -----------------------------------------------------
    if traj_time is not None and "gps_time" in points:
        from pyargus.formats.trajectory import match_times
        _, week, inside = match_times(points["gps_time"], traj_time, time_mode)
        summary["time_base"] = {"gps_week": week, "fraction_inside": inside}

    # --- density -------------------------------------------------------
    dens, dx_edges, dy_edges = density.density_grid(
        points["x"], points["y"], cell=density_cell)
    covered = dens[dens > 0]
    summary["density"] = {
        "cell": density_cell,
        "median": float(np.median(covered)),
        "p5": float(np.percentile(covered, 5)),
        "p95": float(np.percentile(covered, 95)),
        "covered_cells": int(covered.size), "cells": int(dens.size)}
    rgba = raster.sequential_rgba(dens)
    raster.write_png(out_dir / "density.png", rgba)
    raster.write_world_file(out_dir / "density.pgw", dx_edges, dy_edges)
    sections.append(("density", "Density", rgba))

    # --- strip-to-strip dZ on ground returns ---------------------------
    strips = {int(s["strip"]): None for s in per_strip}
    for sid in strips:
        m = ground & (points["point_source_id"] == sid)
        strips[sid] = {k: points[k][m] for k in ("x", "y", "z")}
    pairs = []
    sids = sorted(strips)
    for i, a in enumerate(sids):
        for b in sids[i + 1:]:
            result = overlap.strip_dz(strips[a], strips[b], cell=dz_cell,
                                      min_points=dz_min_points)
            if result.overlap_cells == 0:
                continue
            stats = result.summary()
            stats.update({"a": a, "b": b})
            pairs.append(stats)
            rgba = raster.diverging_rgba(result.dz, dz_limit)
            name = f"dz_{a}-{b}"
            raster.write_png(out_dir / f"{name}.png", rgba)
            raster.write_world_file(out_dir / f"{name}.pgw",
                                    result.x_edges, result.y_edges)
            sections.append((name, f"Strip {a} - strip {b} dZ", rgba))
    summary["strip_dz"] = pairs

    # --- control -------------------------------------------------------
    if control is not None:
        ids, ce, cn, cz = control
        gxyz = np.column_stack(
            [points["x"][ground], points["y"][ground], points["z"][ground]])
        comparison = checkpoints.local_median_residuals(
            gxyz, ids, np.column_stack([ce, cn, cz]),
            radius=control_radius, min_neighbours=control_min_neighbours)
        from pyargus.qa import control_by_strip as cbs
        gathered = {}
        psid_ground = points["point_source_id"][ground]
        for sid in np.unique(psid_ground):
            m = psid_ground == sid
            sx, sy, sz = gxyz[m, 0], gxyz[m, 1], gxyz[m, 2]
            marks = {}
            for k in range(len(ids)):
                near = ((np.abs(sx - ce[k]) <= control_radius)
                        & (np.abs(sy - cn[k]) <= control_radius))
                if near.any():
                    marks[k] = (sx[near], sy[near], sz[near])
            if marks:
                gathered[f"{int(sid)}"] = marks
        try:
            deco = cbs.decompose(gathered, ids, ce, cn, cz,
                                 min_points=control_min_neighbours)
            summary["control_by_strip"] = deco.per_strip()
        except ValueError:
            pass
        values = comparison.values()
        summary["control"] = {
            "residuals": dict(comparison.residuals),
            "skipped": dict(comparison.skipped)}
        if values.size:
            summary["control"].update(checkpoints.robust_summary(values))
            acc = checkpoints.asprs_vertical(values)
            summary["control"].update(
                {"mean": acc.mean, "rmse_z": acc.rmse_z, "nva": acc.nva})

    _write_html(out_dir / "report.html", summary, sections,
                dz_limit=dz_limit, density_cell=density_cell,
                dz_cell=dz_cell, control_radius=control_radius)
    summary["report"] = str(out_dir / "report.html")
    return summary


def _png_data_uri(rgba):
    return ("data:image/png;base64,"
            + base64.b64encode(raster.encode_png(rgba)).decode())


def _write_html(path, summary, sections, *, dz_limit, density_cell, dz_cell,
                control_radius):
    esc = html_mod.escape
    u = esc(summary["units"])
    rows = []

    def h2(text):
        rows.append(f"<h2>{esc(text)}</h2>")

    rows.append("<style>"
                "body{font:15px/1.5 'Segoe UI',system-ui,sans-serif;"
                "color:#22282a;background:#f7f8f5;margin:0}"
                ".wrap{max-width:900px;margin:0 auto;padding:32px 20px}"
                "h1{font-size:1.7rem;margin:0 0 2px}"
                "h2{font-size:1.15rem;margin:32px 0 8px;"
                "border-bottom:2px solid #22282a;padding-bottom:4px}"
                ".meta{color:#5c6670;font-size:.85rem;margin-bottom:8px}"
                "table{border-collapse:collapse;font-size:.9rem;"
                "font-variant-numeric:tabular-nums}"
                "th,td{padding:5px 12px;border-bottom:1px solid #d7dcd6;"
                "text-align:right}"
                "th:first-child,td:first-child{text-align:left}"
                "th{font-size:.72rem;text-transform:uppercase;"
                "letter-spacing:.08em;color:#5c6670}"
                "img{max-width:100%;border:1px solid #d7dcd6;"
                "background:#fff;image-rendering:pixelated}"
                ".note{color:#5c6670;font-size:.85rem;max-width:70ch}"
                "</style>")
    rows.append('<div class="wrap">')
    rows.append(f"<h1>{esc(summary['title'])}</h1>")
    rows.append(f'<div class="meta">pyArgus {esc(pyargus.__version__)} strip QA '
                f"&middot; {datetime.date.today().isoformat()} &middot; "
                f"{summary['points']:,} points, {summary['ground_points']:,} "
                f"ground &middot; units {u}</div>")

    h2("Strips")
    rows.append("<table><tr><th>strip</th><th>points</th><th>ground</th></tr>")
    for s in summary["strips"]:
        rows.append(f"<tr><td>{s['strip']}</td><td>{s['points']:,}</td>"
                    f"<td>{s['ground']:,}</td></tr>")
    rows.append("</table>")

    if "time_base" in summary:
        tb = summary["time_base"]
        h2("Time base")
        time_label = f"GPS week {tb['gps_week']}" if tb["gps_week"] is not None else "Same stored timestamps"
        rows.append(f'<p class="note">{time_label}: '
                    f'{100 * tb["fraction_inside"]:.2f}% of returns inside the '
                    f"trajectory window. Incomplete coverage may mean a partial "
                    f"trajectory, the wrong file, or a time-base mismatch.</p>")

    d = summary["density"]
    h2("Density")
    rows.append(f'<p class="note">{density_cell:g} {u} cells: median '
                f'{d["median"]:.2f} pts/{u}&sup2;, p5 {d["p5"]:.2f}, '
                f'p95 {d["p95"]:.2f} over {d["covered_cells"]:,} covered '
                f"cells. Uncovered cells are transparent.</p>")

    if summary["strip_dz"]:
        h2("Strip-to-strip dZ (ground returns)")
        rows.append(f'<p class="note">Median Z per {dz_cell:g} {u} cell, '
                    f"differenced where both strips have coverage; positive "
                    f"means the second strip sits higher. Maps are scaled to "
                    f"&plusmn;{dz_limit:g} {u} (blue low, red high).</p>")
        rows.append("<table><tr><th>pair</th><th>median</th><th>rmse</th>"
                    "<th>p95 |dz|</th><th>cells</th></tr>")
        for p in summary["strip_dz"]:
            rows.append(f"<tr><td>{p['a']}&ndash;{p['b']}</td>"
                        f"<td>{p['median']:+.3f}</td><td>{p['rmse']:.3f}</td>"
                        f"<td>{p['p95_abs']:.3f}</td><td>{p['cells']:,}</td></tr>")
        rows.append("</table>")

    if "control" in summary:
        c = summary["control"]
        h2("Control")
        rows.append(f'<p class="note">Median of ground returns within '
                    f"{control_radius:g} {u} of each mark, lidar &minus; "
                    f"control; marks without local ground returns are "
                    f"reported, not interpolated.</p>")
        rows.append("<table><tr><th>mark</th><th>dz</th></tr>")
        for pid, dz in c["residuals"].items():
            rows.append(f"<tr><td>{esc(str(pid))}</td><td>{dz:+.3f}</td></tr>")
        for pid, reason in c["skipped"].items():
            rows.append(f"<tr><td>{esc(str(pid))}</td>"
                        f'<td style="text-align:left;color:#5c6670">skipped: '
                        f"{esc(reason)}</td></tr>")
        rows.append("</table>")
        if summary.get("control_by_strip"):
            rows.append('<p class="note">Per strip (median dz over its '
                        'marks) -- matching biases across strips mean the '
                        'miss is position-locked, not misalignment:</p>')
            rows.append("<table><tr><th>strip</th><th>marks</th>"
                        "<th>median dz</th><th>nmad</th></tr>")
            for strip, st in summary["control_by_strip"].items():
                rows.append(f"<tr><td>{esc(strip)}</td><td>{st['n']}</td>"
                            f"<td>{st['median']:+.3f}</td>"
                            f"<td>{st['nmad']:.3f}</td></tr>")
            rows.append("</table>")
        if "median" in c:
            rows.append(f'<p><b>n {c["n"]} &middot; median {c["median"]:+.3f} '
                        f'&middot; NMAD {c["nmad"]:.3f} {u}</b> &middot; '
                        f'mean {c["mean"]:+.3f} &middot; RMSEz '
                        f'{c["rmse_z"]:.3f} &middot; NVA (1.96&middot;RMSEz) '
                        f'{c["nva"]:.3f} {u}</p>')

    for name, caption, rgba in sections:
        h2(caption)
        rows.append(f'<img alt="{esc(caption)}" src="{_png_data_uri(rgba)}">')
        rows.append(f'<p class="note">Also written as {esc(name)}.png with a '
                    f"world file for GIS.</p>")

    rows.append("</div>")
    Path(path).write_text("\n".join(rows), encoding="utf-8")
