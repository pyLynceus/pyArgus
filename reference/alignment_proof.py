"""Phase-4 proof at Summerville scale: recover injected errors.

Real-SBET application waits on the map-frame trajectory plumbing
(Phase 4.5), so this is the strongest available acceptance: a
Summerville-like block -- survey feet, ~330 ft AGL, four strips in a
chain with alternating headings, 0.1 ft measurement noise, rolling
terrain -- with a known boresight error and per-strip vertical offsets
injected through the same forward model reality uses. The solver must
recover the injected truth and collapse the strip dZ.

Run by hand: python -m reference.alignment_proof
Two configurations are measured, because Summerville itself has no
crossing line: with a cross strip (full yaw observability) and
parallel-only (the honest hard case).
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


def terrain_ft(x, y):
    return 650.0 + 12.0 * np.sin(x / 120.0) + 8.0 * np.cos(y / 90.0)


def build(with_cross, seed=11):
    specs = []
    for i in range(4):
        yaw = 0.0 if i % 2 == 0 else np.pi
        origin = (0.0, 130.0 * i) if yaw == 0.0 else (1500.0, 130.0 * i)
        specs.append((yaw, origin, 1500.0, TRUE_OFFSETS[i]))
    if with_cross:
        specs.append((np.pi / 2, (750.0, -100.0), 600.0, (0, 0, 0.03)))
    bundles = []
    for i, (yaw, origin, length, toff) in enumerate(specs):
        b, _ = misaligned_strip(
            yaw, origin, length, terrain=terrain_ft, agl=AGL, swath=220.0,
            n=250_000, true_boresight=TRUE_BETA, true_offset=toff,
            noise=NOISE, seed=seed + 7 * i)
        bundles.append(b)
    return bundles


def dz01(xyzs):
    a = {"x": xyzs[0][:, 0], "y": xyzs[0][:, 1], "z": xyzs[0][:, 2]}
    b = {"x": xyzs[1][:, 0], "y": xyzs[1][:, 1], "z": xyzs[1][:, 2]}
    return overlap.strip_dz(a, b, cell=6.0).summary()


def report(label, with_cross):
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
        return
    err = result.boresight - np.array(TRUE_BETA)
    print(f"solved in {time.perf_counter() - t0:.1f} s, "
          f"{result.n_observations:,} observations, "
          f"{result.iterations} iterations")
    print(f"boresight error: roll {err[0]:+.2e}  pitch {err[1]:+.2e}  "
          f"yaw {err[2]:+.2e} rad  "
          f"(true {TRUE_BETA[0]:+.1e}/{TRUE_BETA[1]:+.1e}/{TRUE_BETA[2]:+.1e})")
    for s in range(1, 4):
        got = result.offsets[s, 2]
        want = -TRUE_OFFSETS[s][2]
        print(f"offset strip {s}: {got:+.4f} ft (want {want:+.4f}, "
              f"err {got - want:+.4f})")
    corrected = result.corrected(bundles)
    after = dz01(corrected)
    print(f"dz 0-1 after:  median {after['median']:+.3f}  "
          f"rmse {after['rmse']:.3f} ft")


def main():
    report("with crossing line", True)
    report("parallel lines only (Summerville-like)", False)


if __name__ == "__main__":
    main()
