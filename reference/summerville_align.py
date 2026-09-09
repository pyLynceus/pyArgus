"""Phase-4.5 acceptance: the real cloud, the real trajectory.

Three questions, in order:

1. Does the plumbing hold? Attach the real SBET (transformed through
   EPSG:6447 + NAVD88 via the geoid grid) to the delivered strips and
   let the built-in checks judge: heading vs flight track, AGL, the
   nadir fan of body vectors.
2. Does the solver leave an aligned delivery alone? The baseline solve
   should find corrections consistent with the measured dZ medians
   (<= 0.03 ft), not invent structure.
3. The ultimate test: inject a known boresight + offsets into the REAL
   strips through their REAL navigation state, re-solve, and require
   the recovery to match (relative to baseline, strip-0 gauge).

Read-only against Z:. Run: python -m reference.summerville_align
Needs the geoid grid (cached after one --proj-network style run; this
script enables PROJ network itself).
"""

import time

import numpy as np

from pyargus.align import attach, solve_alignment
from pyargus.align.bundles import StripBundle, corrected_xyz
from pyargus.formats import crs, las, sbet
from pyargus.qa import overlap
from reference.summerville import CLOUD, SBET

INJECT_BETA = np.array([0.0008, -0.0012, 0.0020])
INJECT_DZ = {0: 0.0, 1: 0.10, 2: -0.07, 3: 0.05}  # by bundle position
CELL = 6.0
MIN_POINTS = 5


def dz_summary(xyz_a, xyz_b):
    a = {"x": xyz_a[:, 0], "y": xyz_a[:, 1], "z": xyz_a[:, 2]}
    b = {"x": xyz_b[:, 0], "y": xyz_b[:, 1], "z": xyz_b[:, 2]}
    result = overlap.strip_dz(a, b, cell=CELL)
    return result.summary() if result.overlap_cells else None


def main():
    results = {}
    print(f"cloud: {CLOUD}")
    points = las.read_points(CLOUD, fields=("x", "y", "z", "gps_time",
                                            "point_source_id",
                                            "classification"))
    ground = points["classification"] == 2
    sub = {k: points[k][ground] for k in ("x", "y", "z", "gps_time",
                                          "point_source_id")}
    trajectory = sbet.read_sbet(SBET)
    map_e, map_n, map_z = crs.sbet_to_map(
        trajectory, "EPSG:6447", vertical="EPSG:6360", allow_network=True)

    attached = attach.bundles_from_cloud(sub, trajectory, map_e, map_n, map_z)
    print(f"\n[attach] week {attached.gps_week}, heading source "
          f"{attached.heading_source!r}")
    both = {k: round(float(np.degrees(v)), 2)
            for k, v in attached.track_errors.items()}
    print(f"  track error (deg): {both}")
    results["track_error_deg"] = float(np.degrees(attached.track_error))
    results["agl_median"] = attached.agl_median
    print(f"  AGL median {attached.agl_median:.1f} ft, nadir median "
          f"{attached.nadir_median_deg:.1f} deg")
    print(f"  strips {attached.strip_ids}: "
          f"{[b.xyz.shape[0] for b in attached.bundles]} ground points")

    # --- baseline: the delivery should need (almost) nothing ----------
    print("\n[baseline solve on the delivered strips]")
    t0 = time.perf_counter()
    try:
        base = solve_alignment(attached.bundles, cell=CELL,
                               min_points=MIN_POINTS)
        full_ok = True
    except ValueError as exc:
        print(f"  full solve refused: {exc}")
        print("  falling back to offsets-only")
        base = solve_alignment(attached.bundles, solve_boresight=False,
                               offsets="z", cell=CELL, min_points=MIN_POINTS)
        full_ok = False
    print(f"  {time.perf_counter() - t0:.0f} s, {base.n_observations:,} obs, "
          f"patch rms {base.rms_before:.3f} -> {base.rms_after:.3f} ft")
    results["baseline_beta_absmax"] = float(np.abs(base.boresight).max())
    results["baseline_offset_absmax"] = float(
        np.abs(base.offsets[:, 2]).max())
    print(f"  boresight {base.boresight}")
    for i, sid in enumerate(attached.strip_ids):
        print(f"  offset strip {sid}: {base.offsets[i, 2]:+.4f} ft")

    # --- injection: perturb the REAL strips, demand recovery ----------
    beta_inj = INJECT_BETA if full_ok else np.array([0.0, 0.0, 0.0])
    print(f"\n[injection] beta {beta_inj}, dz "
          f"{[INJECT_DZ[i] for i in range(4)]}")
    perturbed = []
    for i, bundle in enumerate(attached.bundles):
        xyz = corrected_xyz(bundle, beta_inj,
                            (0.0, 0.0, INJECT_DZ[i]))
        perturbed.append(StripBundle(xyz=xyz, nav_xyz=bundle.nav_xyz,
                                     rpy=bundle.rpy))
    before = dz_summary(perturbed[0].xyz, perturbed[1].xyz)
    results["dz_before_median"] = before["median"]
    print(f"  dz 1-2 after injection: median {before['median']:+.3f} ft, "
          f"rmse {before['rmse']:.3f}")

    t0 = time.perf_counter()
    solved = solve_alignment(perturbed, solve_boresight=full_ok,
                             offsets="z", cell=CELL, min_points=MIN_POINTS)
    print(f"  solved in {time.perf_counter() - t0:.0f} s, "
          f"{solved.n_observations:,} obs, {solved.iterations} iterations")

    beta_err = solved.boresight - (base.boresight - beta_inj)
    results["beta_err_max"] = float(np.abs(beta_err).max())
    results["offset_err_max"] = float(max(
        abs(solved.offsets[i, 2] - (base.offsets[i, 2] - INJECT_DZ[i]))
        for i in range(4)))
    print(f"  boresight recovery error: {beta_err} rad")
    for i, sid in enumerate(attached.strip_ids):
        want = base.offsets[i, 2] - INJECT_DZ[i]
        got = solved.offsets[i, 2]
        print(f"  offset strip {sid}: {got:+.4f} (want {want:+.4f}, "
              f"err {got - want:+.4f} ft)")

    corrected = solved.corrected(perturbed)
    after = dz_summary(corrected[0], corrected[1])
    print(f"  dz 1-2 after recovery: median {after['median']:+.3f} ft, "
          f"rmse {after['rmse']:.3f}")
    results["dz_after_median"] = after["median"]
    return results


if __name__ == "__main__":
    main()
