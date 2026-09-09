"""Colorization acceptance: the real cloud through the real imagery.

Paints Summerville_SS.las (15.28M points, LAS 1.4 pf7 with empty RGB)
from the delivered TrueView 660 imagery -- 1083 JPEGs, three cameras,
LP360 EO CSV, per-camera .cal sidecars -- everything read from Z:
and nothing written there.

Referees (colors cannot be diffed against a truth cloud, so the
checks are cross-sensor):

* coverage: the fraction of points that get a color, and how many
  photos actually contribute. The ~29% marked OCCLUDED is the site
  itself: 42 ft median canopy, and ground under trees genuinely
  cannot be colored from aerial imagery -- the honest answer is no
  color, not the canopy's;
* CROSS-CAMERA consistency, the geometric referee: a sample of
  nadir-colored points recolored through the OBLIQUE cameras only.
  Nadir and obliques are different lenses on different mounts looking
  through different EO rows; a quarter-turn, principal-point, P2-sign
  or frame error decorrelates them immediately, while a correct
  projection leaves only exposure/BRDF differences;
* vegetation is GREENER than ground: mean (G - R) over the delivered
  vegetation classes minus the same over class 2. Wrong-frame
  sampling pulls both toward the scene average and the margin
  collapses.

(Intensity-vs-luminance was tried as a referee and measured
uninformative: r = -0.08 on ground points -- lidar NIR amplitude and
visible brightness legitimately decorrelate across grass vs asphalt,
so agreement there certifies nothing. Recorded so nobody retries it.)

Run by hand: python -m reference.summerville_colorize
"""

import time
from pathlib import Path

import numpy as np

from pyargus.formats import eo as eo_mod
from pyargus.formats import las as las_mod
from pyargus.imagery import camera as camera_mod
from pyargus.imagery import colorize as colorize_mod

ROOT = Path("Z:/Users/BJordan/Summerville_SS")
CLOUD = ROOT / "Summerville_SS.las"
FLIGHT = ROOT / "Area_/Cycle_250926_134000_122SN030/Flight_250926_134000"
EO_CSV = FLIGHT / "System/eo_Photos_C250926_134000_122SN030.csv"


def main():
    t0 = time.perf_counter()
    eo = eo_mod.read_eo_csv(EO_CSV)
    image_paths = colorize_mod.find_images(FLIGHT)
    print(f"eo:      {len(eo['filename'])} rows, "
          f"{len(image_paths)} image files on disk")

    tag_sample = {}
    for name in eo["filename"]:
        found = image_paths.get(name.lower())
        if found is not None:
            tag_sample.setdefault(eo_mod.camera_tag(name), found)
    cameras = {}
    for tag, sample in sorted(tag_sample.items()):
        cal = camera_mod.find_cal(sample)
        cameras[tag] = camera_mod.read_cal(cal, quarter_turns=3,
                                           name=str(tag))
        cam = cameras[tag]
        print(f"camera {tag}: {cal.name}  f {cam.focal_mm:.4f} mm "
              f"({cam.focal_px:.2f} px)  pp ({cam.cx_px:+.2f}, "
              f"{cam.cy_px:+.2f}) px")

    points = las_mod.read_points(
        CLOUD, fields=("x", "y", "z", "intensity", "classification"))
    xyz = np.column_stack([points["x"], points["y"], points["z"]])
    print(f"cloud:   {xyz.shape[0]:,} points")

    ctx = colorize_mod.prepare(eo, cameras, image_paths)
    plan = colorize_mod.plan_colorization(xyz, ctx["origins"],
                                          ctx["rotations"], ctx["cameras"])
    rgb, occluded, stats = colorize_mod.apply_plan(plan, ctx["paths"],
                                                   ctx["cameras"])
    stats["n_eo_dropped"] = ctx["n_eo_dropped"]
    runtime = time.perf_counter() - t0
    pct = 100.0 * stats["n_colored"] / stats["n_points"]
    pct_occ = 100.0 * stats["n_occluded"] / stats["n_points"]
    print(f"colored: {stats['n_colored']:,} of {stats['n_points']:,} "
          f"({pct:.2f}%) from {stats['n_images_used']} images, "
          f"{pct_occ:.2f}% occluded, {stats['n_unseen']:,} unseen, "
          f"{stats['n_eo_dropped']} EO rows without files; "
          f"{runtime:.0f} s")

    r8 = (rgb >> 8).astype(float)
    colored = rgb.any(axis=1)
    cls = points["classification"]

    # cross-camera referee: NADIR-colored points, recolored obliquely.
    # Restricting the sample to nadir assignments matters: off-track
    # points' best photo is already an oblique, and "recoloring" those
    # through the same photo would referee nothing (measured: median 0).
    t1 = time.perf_counter()
    tags = np.array(ctx["tags"])
    nadir_pts = colored & (plan.image >= 0)
    nadir_pts[nadir_pts] = tags[plan.image[nadir_pts]] == "N"
    oblique_rows = [j for j, n in enumerate(eo["filename"])
                    if eo_mod.camera_tag(n) in ("P", "S")]
    eo_obl = {"time": eo["time"][oblique_rows],
              "filename": [eo["filename"][j] for j in oblique_rows],
              "origin": eo["origin"][oblique_rows],
              "direction": eo["direction"][oblique_rows],
              "up": eo["up"][oblique_rows]}
    rng = np.random.default_rng(7)
    sample = np.flatnonzero(nadir_pts)
    sample = rng.choice(sample, size=min(300_000, sample.size),
                        replace=False)
    rgb_obl, _ = colorize_mod.colorize(xyz[sample], eo_obl, cameras,
                                       image_paths)
    both = rgb_obl.any(axis=1)
    dr = np.median(np.abs(r8[sample][both, 0] - (rgb_obl[both, 0] >> 8)))
    dg = np.median(np.abs(r8[sample][both, 1] - (rgb_obl[both, 1] >> 8)))
    db = np.median(np.abs(r8[sample][both, 2] - (rgb_obl[both, 2] >> 8)))
    cross = float(max(dr, dg, db))
    print(f"referee: {int(nadir_pts.sum()):,} nadir-colored points; "
          f"nadir vs oblique recolor over {int(both.sum()):,} "
          f"shared points: median |dRGB| ({dr:.1f}, {dg:.1f}, {db:.1f}) "
          f"of 255; {time.perf_counter() - t1:.0f} s")

    ground = colored & (cls == 2)
    veg = colored & np.isin(cls, (3, 4, 5))
    green_veg = float(np.mean(r8[veg, 1] - r8[veg, 0]))
    green_gnd = float(np.mean(r8[ground, 1] - r8[ground, 0]))
    margin = green_veg - green_gnd
    print(f"referee: vegetation G-R {green_veg:+.1f} vs ground "
          f"{green_gnd:+.1f} (margin {margin:+.1f} of 255)")

    return {
        "pct_colored": pct,
        "pct_occluded": pct_occ,
        "n_images_used": stats["n_images_used"],
        "n_eo_dropped": stats["n_eo_dropped"],
        "cross_camera_median_drgb": cross,
        "veg_green_margin": margin,
    }


if __name__ == "__main__":
    main()
