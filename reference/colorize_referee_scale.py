"""What does the cross-camera referee's number MEAN? Its scale.

`summerville_colorize` recolors nadir-colored points through the
oblique cameras and reports a median |dRGB|. That number is only
interpretable against two anchors, and quoting anchors no code
reproduces is exactly the unhonored claim this repo refuses
elsewhere -- so they are measured here:

* the RADIOMETRIC FLOOR: recolor the same points through OTHER NADIR
  frames. Same lens, same look angle, different exposure -- whatever
  this measures is frame-to-frame radiometry, not geometry;
* a GEOMETRIC FAULT: recolor through the obliques with a deliberately
  wrong ``quarter_turns``, i.e. the sensor mounting mis-stated.

A healthy cross-camera number should sit near the radiometric floor
and far from the fault. Run by hand (it recolors three times, so it
is slower than the acceptance itself):

    python -m reference.colorize_referee_scale
"""

import time

import numpy as np

from pyargus.formats import eo as eo_mod
from pyargus.formats import las as las_mod
from pyargus.imagery import camera as camera_mod
from pyargus.imagery import colorize as colorize_mod
from reference.summerville_colorize import CLOUD, EO_CSV, FLIGHT

SAMPLE = 100_000


def main():
    eo = eo_mod.read_eo_csv(EO_CSV)
    image_paths = colorize_mod.find_images(FLIGHT)
    tag_sample = {}
    for name in eo["filename"]:
        found = image_paths.get(name.lower())
        if found is not None:
            tag_sample.setdefault(eo_mod.camera_tag(name), found)
    cameras = {tag: camera_mod.read_cal(camera_mod.find_cal(s),
                                        quarter_turns=3, name=str(tag))
               for tag, s in tag_sample.items()}
    wrong = {tag: camera_mod.read_cal(camera_mod.find_cal(s),
                                      quarter_turns=1, name=str(tag))
             for tag, s in tag_sample.items()}

    points = las_mod.read_points(CLOUD, fields=("x", "y", "z"))
    xyz = np.column_stack([points["x"], points["y"], points["z"]])

    ctx = colorize_mod.prepare(eo, cameras, image_paths)
    plan = colorize_mod.plan_colorization(xyz, ctx["origins"],
                                          ctx["rotations"], ctx["cameras"])
    rgb, _, _ = colorize_mod.apply_plan(plan, ctx["paths"], ctx["cameras"])
    tags = np.array(ctx["tags"])
    colored = rgb.any(axis=1)

    nadir_rows = np.flatnonzero(tags == "N")
    order = nadir_rows[np.argsort(eo["time"][nadir_rows])]
    even = set(order[0::2].tolist())
    odd_names = {eo["filename"][j] for j in order[1::2]}
    oblique_names = {n for n in eo["filename"]
                     if eo_mod.camera_tag(n) in ("P", "S")}

    # points whose best photo is an EVEN nadir frame, so the odd
    # frames are a genuinely independent look at the same ground
    best_even = colored & (plan.image >= 0)
    best_even[best_even] = np.isin(plan.image[best_even], list(even)) \
        & (tags[plan.image[best_even]] == "N")
    rng = np.random.default_rng(11)
    pool = np.flatnonzero(best_even)
    sample = rng.choice(pool, size=min(SAMPLE, pool.size), replace=False)
    print(f"sample:  {sample.size:,} points coloured by even nadir frames")

    def recolor(names, cams):
        rows = [j for j, n in enumerate(eo["filename"]) if n in names]
        sub = {"time": eo["time"][rows],
               "filename": [eo["filename"][j] for j in rows],
               "origin": eo["origin"][rows],
               "direction": eo["direction"][rows],
               "up": eo["up"][rows]}
        out, _ = colorize_mod.colorize(xyz[sample], sub, cams, image_paths)
        both = out.any(axis=1)
        d = np.abs((rgb[sample][both] >> 8).astype(float)
                   - (out[both] >> 8).astype(float))
        return int(both.sum()), np.median(d, axis=0)

    results = {}
    for label, names, cams, key in (
            ("nadir vs other nadir frames (radiometric floor)",
             odd_names, cameras, "same_camera"),
            ("nadir vs obliques (the referee itself)",
             oblique_names, cameras, "cross_camera"),
            ("nadir vs obliques, quarter_turns MIS-STATED (fault)",
             oblique_names, wrong, "corrupted")):
        t0 = time.perf_counter()
        n, med = recolor(names, cams)
        results[key] = float(med.max())
        print(f"{label}: {n:,} shared, median |dRGB| "
              f"({med[0]:.0f}, {med[1]:.0f}, {med[2]:.0f}) of 255  "
              f"[{time.perf_counter() - t0:.0f} s]")
    return results


if __name__ == "__main__":
    main()
