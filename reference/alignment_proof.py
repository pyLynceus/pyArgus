"""Phase-4 proof at Summerville scale: recover injected errors.

Real-SBET application waits on the map-frame trajectory plumbing
(Phase 4.5), so this is the strongest available acceptance: a
Summerville-like block -- survey feet, ~330 ft AGL, four strips in a
chain with alternating headings, 0.1 ft measurement noise, rolling
terrain -- with a known boresight error and per-strip vertical offsets
injected through the same forward model reality uses. The solver must
recover the injected truth and collapse the strip dZ.

Run by hand: python -m reference.alignment_proof
Three configurations are measured, because Summerville itself has no
crossing line: with a cross strip (full yaw observability),
parallel-only (the honest hard case), and the cross-strip block again
with a sinusoidal GNSS wander injected into one line. The drift case
runs the workflow reality requires: boresight CALIBRATED ON THE CLEAN
BLOCK, carried over, and the wander solved drift-only with the
calibration held. A wandering block is not calibration data -- the
constant solve's own boresight comes out ~1e-3 rad wrong in pitch
there (worse than the injected error; measured and pinned below), and
solving boresight and drift together is no better, because over
smooth terrain pitch's along-track dz signature is a slow function of
time that each strip's drift can absorb.
"""

import time

import numpy as np

from pyargus.align import solve_alignment
from pyargus.qa import overlap
from tests.synthetic import misaligned_strip

TRUE_BETA = (0.0005, -0.0008, 0.0015)   # radians: 0.03-0.09 deg
TRUE_OFFSETS = ((0, 0, 0.0), (0, 0, 0.12), (0, 0, -0.08), (0, 0, 0.05))
AGL = 330.0
NOISE = 0.10
DRIFT_PERIOD = 25.0                     # seconds; strip 1 wanders
DRIFT_AMPLITUDE = 0.10                  # ft, on top of its 0.12 constant


def true_drift(t):
    return DRIFT_AMPLITUDE * np.sin(2 * np.pi * np.asarray(t) / DRIFT_PERIOD)


def terrain_ft(x, y):
    return 650.0 + 12.0 * np.sin(x / 120.0) + 8.0 * np.cos(y / 90.0)


def build(with_cross, seed=11, drifted_strip=None):
    specs = []
    for i in range(4):
        yaw = 0.0 if i % 2 == 0 else np.pi
        origin = (0.0, 130.0 * i) if yaw == 0.0 else (1500.0, 130.0 * i)
        specs.append((yaw, origin, 1500.0, TRUE_OFFSETS[i], 90.0 * i))
    if with_cross:
        specs.append((np.pi / 2, (750.0, -100.0), 600.0, (0, 0, 0.03), 380.0))
    bundles = []
    for i, (yaw, origin, length, toff, t0) in enumerate(specs):
        b, _ = misaligned_strip(
            yaw, origin, length, terrain=terrain_ft, agl=AGL, swath=220.0,
            n=250_000, true_boresight=TRUE_BETA, true_offset=toff,
            true_drift=true_drift if i == drifted_strip else None, t0=t0,
            noise=NOISE, seed=seed + 7 * i)
        bundles.append(b)
    return bundles


def dz01(xyzs):
    a = {"x": xyzs[0][:, 0], "y": xyzs[0][:, 1], "z": xyzs[0][:, 2]}
    b = {"x": xyzs[1][:, 0], "y": xyzs[1][:, 1], "z": xyzs[1][:, 2]}
    return overlap.strip_dz(a, b, cell=6.0).summary()


def report(label, with_cross):
    results = {}
    print(f"\n== {label}")
    bundles = build(with_cross)
    before = dz01([b.xyz for b in bundles])
    print(f"dz 0-1 before: median {before['median']:+.3f}  "
          f"rmse {before['rmse']:.3f} ft")
    t0 = time.perf_counter()
    try:
        result = solve_alignment(bundles, cell=6.0, min_points=6)
    except ValueError as exc:
        print(f"solver refused: {exc}")
        return {"refused": True}
    err = result.boresight - np.array(TRUE_BETA)
    results["beta_err_max"] = float(np.abs(err).max())
    results["dz_before_median"] = before["median"]
    results["boresight"] = result.boresight     # for the drift stage
    print(f"solved in {time.perf_counter() - t0:.1f} s, "
          f"{result.n_observations:,} observations, "
          f"{result.iterations} iterations")
    print(f"boresight error: roll {err[0]:+.2e}  pitch {err[1]:+.2e}  "
          f"yaw {err[2]:+.2e} rad  "
          f"(true {TRUE_BETA[0]:+.1e}/{TRUE_BETA[1]:+.1e}/{TRUE_BETA[2]:+.1e})")
    wants = [TRUE_OFFSETS[s][2] for s in range(1, 4)]
    if with_cross:
        wants.append(0.03)          # the crossing line's injected offset
    results["offset_err_max"] = float(max(
        abs(result.offsets[s + 1, 2] + want)
        for s, want in enumerate(wants)))
    for s in range(1, 4):
        got = result.offsets[s, 2]
        want = -TRUE_OFFSETS[s][2]
        print(f"offset strip {s}: {got:+.4f} ft (want {want:+.4f}, "
              f"err {got - want:+.4f})")
    corrected = result.corrected(bundles)
    after = dz01(corrected)
    print(f"dz 0-1 after:  median {after['median']:+.3f}  "
          f"rmse {after['rmse']:.3f} ft")
    return results


def report_drift(label, calibrated, spacing=5.0):
    from pyargus.align.bundles import StripBundle, corrected_xyz

    results = {}
    print(f"\n== {label}")
    bundles = build(True, drifted_strip=1)
    before = dz01([b.xyz for b in bundles])
    print(f"dz 0-1 before: median {before['median']:+.3f}  "
          f"rmse {before['rmse']:.3f} ft")
    # what calibrating ON the wandering block would cost (pinned: this
    # is the number behind "a wandering block is not calibration data")
    t0 = time.perf_counter()
    try:
        contaminated = solve_alignment(bundles, cell=6.0, min_points=6)
    except ValueError as exc:
        print(f"constant solve refused: {exc}")
        return {"refused": True}
    cerr = contaminated.boresight - np.array(TRUE_BETA)
    results["contaminated_beta_err_max"] = float(np.abs(cerr).max())
    print(f"calibrating on this block anyway ({time.perf_counter() - t0:.1f}"
          f" s) errs roll {cerr[0]:+.2e}  pitch {cerr[1]:+.2e}  "
          f"yaw {cerr[2]:+.2e} rad -- the wander poisons the calibration")
    # ... and solving boresight AND drift together is no better
    t0 = time.perf_counter()
    try:
        together = solve_alignment(bundles, cell=6.0, min_points=6,
                                   drift_spacing=spacing)
    except ValueError as exc:
        print(f"together solve refused: {exc}")
        return {"refused": True}
    terr = together.boresight - np.array(TRUE_BETA)
    results["together_beta_err_max"] = float(np.abs(terr).max())
    print(f"boresight+drift TOGETHER ({time.perf_counter() - t0:.1f} s) "
          f"errs roll {terr[0]:+.2e}  pitch {terr[1]:+.2e}  "
          f"yaw {terr[2]:+.2e} rad -- pitch leaks into the curves")
    # the real workflow: the CLEAN block's boresight, held
    held = [StripBundle(xyz=corrected_xyz(b, calibrated, (0, 0, 0)),
                        nav_xyz=b.nav_xyz, rpy=b.rpy, times=b.times)
            for b in bundles]
    t0 = time.perf_counter()
    try:
        stage2 = solve_alignment(held, solve_boresight=False, cell=6.0,
                                 min_points=6, drift_spacing=spacing)
    except ValueError as exc:
        print(f"drift solve refused: {exc}")
        return {"refused": True}
    print(f"drift solve (clean-block boresight held) in "
          f"{time.perf_counter() - t0:.1f} s, "
          f"{stage2.n_observations:,} observations, "
          f"{stage2.iterations} iterations")
    # drift shape on the wandering strip: mean-removed (the constant
    # 0.12 and the datum both live in the mean), interior nodes (ends
    # see half a bracket and are stiffness-damped)
    nt = stage2.drift.node_times[1]
    got = stage2.drift.values[1]
    want = -true_drift(nt)
    shape_err = np.abs((got - got.mean()) - (want - want.mean()))[1:-1]
    results["drift_shape_err_max"] = float(shape_err.max())
    lo, hi = stage2.drift.span(1)
    print(f"drift strip 1: span {lo:+.3f} .. {hi:+.3f} ft over "
          f"{len(nt)} nodes; shape error vs injected sinusoid "
          f"{shape_err.max():.4f} ft max (interior nodes)")
    corrected = stage2.corrected(held)
    after = dz01(corrected)
    results["dz_after_median"] = after["median"]
    results["dz_after_rmse"] = after["rmse"]
    print(f"dz 0-1 after:  median {after['median']:+.3f}  "
          f"rmse {after['rmse']:.3f} ft")
    return results


def main():
    with_cross = report("with crossing line", True)
    parallel = report("parallel lines only (Summerville-like)", False)
    drift = ({"refused": True} if with_cross.get("refused")
             else report_drift("crossing block + sinusoidal wander on "
                               "strip 1, calibrate-then-drift workflow",
                               with_cross["boresight"]))
    return {"with_cross": with_cross, "parallel": parallel, "drift": drift}


if __name__ == "__main__":
    main()
