"""SH 151 case study, step 3: two sensors over one control network.

The step-2 workup proved the lidar block is RIGID and the misses are
POSITION-LOCKED at individual marks, then stopped at a fork: a busted
mark and a busted vendor LCP adjustment produce the same signature.
It recorded that the aerotriangulation could not adjudicate, because
"at exactly the worst marks the AT residuals are 0.000 -- those
points were CONSTRAINED control".

That reading was wrong, and this script is the correction. In
rtesults.txt the resX and resY columns are 0.000 by MEASUREMENT
PROCEDURE -- the stereo operator navigates to the mark's known
planimetric position and reads height there -- so resZ is a
photogrammetric-minus-surveyed height difference at the mark. 58 of
the 65 marks carry a nonzero one, and their mean is -0.002 ft: the
imagery has no systematic vertical bias against this network.

That makes the imagery an INDEPENDENT SENSOR over the same marks. A
mark that is genuinely mis-surveyed pulls both sensors off it,
because the AT's geometry is held by the other 64 marks and one bad
point cannot drag the block onto itself. A mark that is fine, read
wrong only by the lidar, is the vendor's adjustment.

    |AT| small, |lidar| large  -> the imagery CONFIRMS the mark
    both large                 -> the mark itself needs re-observing

Both tests are on MAGNITUDE. The sign convention of resZ (measured
minus control, or the reverse) is not documented in the report and
cannot be recovered from the data -- the signed correlation between
the two sensors is ~0 at every grade band, which is itself the point:
their errors are independent, so neither is dominated by shared mark
error. Nothing here rests on the sign.

Marks whose resZ is exactly 0.000 in every model ARE non-informative
-- step 2's objection, but for 7 marks rather than all 65 -- and are
excluded, never counted as evidence.

``dz_plane`` already evaluates a local plane AT the mark, so grade is
corrected before comparison; the slope cut below is a proxy for
vegetation risk (step 2's Population A sat on 11-27% faces), not for
grade error. Median grade here is 4.5% and p90 is 10.3%.

Runs off the step-1 strip cache (reference/reports/sh151_cache) and
the two Z: reports; Z: stays read-only.
Run: python -m reference.sh151_cross_sensor
"""

from pathlib import Path

import numpy as np

from pyargus.qa import control_by_strip as cbs
from reference.sh151_gather import CACHE

SURVEY = Path("Z:/Users/BJordan/SH 151/SURVEY")
LIDAR_REPORT = SURVEY / "ControlReport_OSSDACheckShots_reduxlidar.txt"
AT_REPORT = SURVEY / "rtesults.txt"

MISS = 0.10          # ft; clean marks read +/-0.01 grade-corrected
AT_NOISE = 0.11      # ft; the AT's own global Z rms, its noise floor
FLAT = 0.08          # rise/run; above this, vegetation risk dominates


def read_lidar_report():
    """{mark: (easting, northing, known_z, laser_z, dz)} as delivered."""
    out = {}
    for line in LIDAR_REPORT.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0].isdigit():
            out[parts[0]] = tuple(float(v) for v in parts[1:6])
    return out


def read_at_report():
    """{mark: list of per-model photogrammetric-vs-surveyed dZ}.

    Parsed from the per-model rows, whose columns are unambiguous
    (ModelName resX resY resZ ...). The summary lines above them have
    different field counts for "Root mean squared errors:" and
    "Minimum differences:", which is a live trap: reading the wrong
    offset there is what produced step 2's mistaken conclusion.
    """
    out = {}
    mark = None
    for line in AT_REPORT.read_text().splitlines():
        parts = line.split()
        if line.startswith("Point:"):
            mark = parts[1]
            out.setdefault(mark, [])
        elif mark and parts and parts[0].endswith(".vmf"):
            out[mark].append(float(parts[3]))
    return out


def lidar_by_mark(marks):
    """Grade-corrected lidar dz per mark, from the per-strip cache."""
    ids = sorted(marks)
    index = {m: i for i, m in enumerate(ids)}
    e = np.array([marks[m][0] for m in ids])
    n = np.array([marks[m][1] for m in ids])
    z = np.array([marks[m][2] for m in ids])
    gathered = {}
    for npz_path in sorted(CACHE.glob("*.npz")):
        data = np.load(npz_path, allow_pickle=False)
        if data["mark"].size == 0:
            continue
        per_mark = {}
        labels = data["mark"]
        for label in np.unique(labels):
            if str(label) not in index:
                continue
            m = labels == label
            per_mark[index[str(label)]] = (data["x"][m], data["y"][m],
                                           data["z"][m])
        if per_mark:
            gathered[npz_path.stem[:7]] = per_mark
    result = cbs.decompose(gathered, ids, e, n, z)
    slopes = {}
    for cell in result.cells:
        slopes.setdefault(ids[cell.mark], []).append(cell.slope)
    table = result.per_mark()
    for mark, row in table.items():
        row["slope"] = float(np.median(slopes[mark]))
    return table


def main():
    marks = read_lidar_report()
    at = read_at_report()
    lidar = lidar_by_mark(marks)

    rows = []
    for mark in sorted(marks):
        if mark not in at or mark not in lidar:
            continue
        res = at[mark]
        rows.append({
            "mark": mark,
            "dz_lidar": lidar[mark]["dz_plane"],
            "spread": lidar[mark]["spread"],
            "slope": lidar[mark]["slope"],
            "dz_at": float(np.mean(res)) if res else float("nan"),
            "n_models": len(res),
            "informative": bool(res) and any(abs(v) > 0 for v in res),
        })

    informative = [r for r in rows if r["informative"]]
    bias = float(np.mean([r["dz_at"] for r in informative]))
    print(f"marks:   {len(rows)} check shots carry both a cached lidar "
          f"surface and an AT measurement")
    print(f"AT:      {len(informative)} give an independent height check; "
          f"their mean dZ is {bias:+.3f} ft, so the imagery carries no "
          f"systematic vertical bias against this network")

    usable = [r for r in informative if r["slope"] < FLAT]
    print(f"grade:   {len(usable)} of those sit under {FLAT:.0%} "
          f"(vegetation risk; grade itself is already corrected)")

    for r in rows:
        if not r["informative"]:
            r["verdict"] = "no AT check"
        elif abs(r["dz_lidar"]) <= MISS:
            r["verdict"] = "both clean"
        elif abs(r["dz_at"]) <= AT_NOISE:
            r["verdict"] = "imagery confirms the mark"
        else:
            r["verdict"] = "both sensors miss"

    worst = sorted([r for r in usable if abs(r["dz_lidar"]) > MISS],
                   key=lambda r: -abs(r["dz_lidar"]))
    print()
    print(f"{'mark':<9}{'lidar dz':>9}{'spread':>8}{'grade':>7}"
          f"{'|AT dz|':>9}{'mdl':>5}   verdict")
    for r in worst:
        print(f"{r['mark']:<9}{r['dz_lidar']:>+9.3f}{r['spread']:>8.3f}"
              f"{r['slope']:>7.1%}{abs(r['dz_at']):>9.3f}"
              f"{r['n_models']:>5}   {r['verdict']}")

    confirmed = [r for r in worst if r["verdict"] == "imagery confirms the mark"]
    both = [r for r in worst if r["verdict"] == "both sensors miss"]
    clean = [r for r in usable if abs(r["dz_lidar"]) <= MISS]
    agree = [r for r in clean if abs(r["dz_at"]) <= AT_NOISE]

    print()
    print(f"lidar misses more than {MISS:.2f} ft at {len(worst)} of "
          f"{len(usable)} usable marks.")
    if confirmed:
        arr = np.array([abs(r["dz_lidar"]) for r in confirmed])
        print(f"  {len(confirmed)}: the imagery lands within its own "
              f"{AT_NOISE:.2f} ft noise of the surveyed elevation while "
              f"the lidar misses by {arr.min():.2f}-{arr.max():.2f} ft. "
              f"The marks are good; the lidar is wrong there.")
    if both:
        print(f"  {len(both)}: both sensors miss "
              f"({', '.join(r['mark'] for r in both)}) -- re-observe "
              f"these before quoting them against anyone.")
    print(f"Where the lidar is clean ({len(clean)} marks), the imagery "
          f"agrees at {len(agree)} of them.")

    # --- a second, separable component: a corridor-scale tilt --------
    e = np.array([marks[r["mark"]][0] for r in usable])
    n = np.array([marks[r["mark"]][1] for r in usable])
    dl = np.array([r["dz_lidar"] for r in usable])
    da = np.array([r["dz_at"] for r in usable])
    design = np.column_stack([e - e.mean(), n - n.mean(), np.ones(e.size)])
    coef, *_ = np.linalg.lstsq(design, dl, rcond=None)
    residual = dl - design @ coef
    tilt_east = float(coef[0] * 5280.0)
    tilt_north = float(coef[1] * 5280.0)
    rms_before = float(np.sqrt(np.mean(dl ** 2)))
    rms_after = float(np.sqrt(np.mean(residual ** 2)))
    at_coef, *_ = np.linalg.lstsq(design, da, rcond=None)
    print()
    print(f"tilt:    the lidar misfit carries a corridor-scale tilt of "
          f"{tilt_east:+.3f} ft/mile east, {tilt_north:+.3f} ft/mile "
          f"north over a {e.max() - e.min():,.0f} ft span "
          f"(corr with easting {np.corrcoef(e, dl)[0, 1]:+.2f}); "
          f"removing it drops the rms from {rms_before:.3f} to "
          f"{rms_after:.3f} ft, and mark-local residuals are the rest.")
    print(f"         The imagery's own tilt is "
          f"{float(at_coef[0] * 5280.0):+.3f} ft/mile east -- but it is "
          f"ADJUSTED to these marks, so it would absorb a tilt in the "
          f"network itself and CANNOT adjudicate this component. A geoid "
          f"model difference remains a live explanation for the tilt, "
          f"which is why the geoid question matters.")

    return {
        "tilt_east_ft_per_mile": tilt_east,
        "tilt_north_ft_per_mile": tilt_north,
        "rms_before_tilt": rms_before,
        "rms_after_tilt": rms_after,
        "n_marks": len(rows),
        "n_informative": len(informative),
        "at_bias": bias,
        "n_usable": len(usable),
        "n_lidar_misses": len(worst),
        "n_imagery_confirms_mark": len(confirmed),
        "n_both_miss": len(both),
        "confirmed_marks": [r["mark"] for r in confirmed],
        "both_miss_marks": [r["mark"] for r in both],
    }


if __name__ == "__main__":
    main()
