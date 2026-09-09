"""The acceptance battery as a regression gate.

Every phase's Summerville acceptance recorded its numbers in
RESULTS.md; this runs the whole battery and diffs what the scripts
measure NOW against those recorded expectations. Run it after any
substantive change to qa/, align/, classify/, surfaces/, or formats/:

    python -m reference.run_all

Needs Z: (the reference dataset) and the cached geoid grid. Exit code
0 only when every check passes. Tolerances are deliberate: exact-ish
where the computation is deterministic, bounds where it is a recovery
error, and slightly loose where a forest's threading is involved.
A FAILURE MEANS THE CODE CHANGED BEHAVIOR -- either fix the
regression, or (if the new number is better and understood) update
the expectation here AND the RESULTS.md entry together, never one
without the other.
"""

import contextlib
import io
import time

# (script module, key path, comparison, expected, tolerance)
#   "abs"   -> |value - expected| <= tol
#   "below" -> value <= expected  (tol unused)
#   "equal" -> value == expected
CHECKS = [
    ("summerville", "time_base_fraction", "abs", 1.0, 1e-9),
    ("summerville", "density_median", "abs", 8.33, 0.01),
    ("summerville", "density_p95", "abs", 22.89, 0.05),
    ("summerville", "dz_12_median", "abs", 0.000, 0.002),
    ("summerville", "dz_23_median", "abs", -0.005, 0.002),
    ("summerville", "dz_34_median", "abs", 0.030, 0.002),
    ("summerville", "dz_12_rmse", "abs", 0.210, 0.005),
    ("summerville", "tin_mean", "abs", -0.011, 0.005),
    ("summerville", "local_n", "equal", 6, 0),
    ("summerville", "local_median", "abs", 0.146, 0.002),
    ("summerville", "local_nmad", "abs", 0.148, 0.003),

    ("summerville_ground", "recall", "abs", 0.9992, 0.0005),
    ("summerville_ground", "fp_within_1ft", "abs", 0.962, 0.003),
    ("summerville_ground", "dtm_median", "abs", 0.111, 0.005),
    ("summerville_ground", "dtm_nmad", "abs", 0.126, 0.005),
    ("summerville_ground", "control_n", "equal", 6, 0),
    ("summerville_ground", "control_median", "abs", 0.193, 0.005),
    ("summerville_ground", "noise_as_ground", "abs", 1622, 50),

    ("alignment_proof", "with_cross.beta_err_max", "below", 2e-5, 0),
    ("alignment_proof", "with_cross.offset_err_max", "below", 2e-3, 0),
    ("alignment_proof", "with_cross.dz_before_median", "abs", 0.098, 0.005),
    ("alignment_proof", "parallel.beta_err_max", "below", 5e-5, 0),
    ("alignment_proof", "parallel.offset_err_max", "below", 2e-3, 0),
    ("alignment_proof", "drift.contaminated_beta_err_max", "abs", 1.05e-3, 2e-4),
    ("alignment_proof", "drift.together_beta_err_max", "abs", 1.24e-3, 2e-4),
    ("alignment_proof", "drift.drift_shape_err_max", "below", 0.04, 0),
    ("alignment_proof", "drift.dz_after_median", "abs", 0.0, 0.01),
    ("alignment_proof", "drift.dz_after_rmse", "abs", 0.081, 0.005),

    ("summerville_align", "track_error_deg", "abs", 0.53, 0.05),
    ("summerville_align", "agl_median", "abs", 331.9, 1.0),
    ("summerville_align", "baseline_beta_absmax", "below", 1.5e-3, 0),
    ("summerville_align", "baseline_offset_absmax", "below", 0.04, 0),
    ("summerville_align", "beta_err_max", "below", 5e-5, 0),
    ("summerville_align", "offset_err_max", "below", 3e-3, 0),
    ("summerville_align", "dz_after_median", "abs", 0.0, 0.01),

    ("summerville_contours", "n_lines", "equal", 2152, 0),
    ("summerville_contours", "n_levels", "equal", 40, 0),
    ("summerville_contours", "total_length", "abs", 181335, 50),
    ("summerville_contours", "vertex_err_max", "below", 1e-6, 0),
    ("summerville_contours", "dsm_dtm_median", "abs", 42.60, 0.1),
    ("summerville_contours", "below_dtm_cells", "abs", 33, 5),

    ("summerville_above", "agreement", "abs", 0.9972, 0.001),
    ("summerville_above", "kappa", "abs", 0.9881, 0.004),
    ("summerville_above", "building_recall", "abs", 0.918, 0.01),
    ("summerville_above", "building_precision", "abs", 0.558, 0.02),
    ("summerville_above", "deploy_agreement", "abs", 0.9946, 0.001),
]


def dig(mapping, dotted):
    for part in dotted.split("."):
        mapping = mapping[part]
    return mapping


def main():
    import importlib

    modules = []
    for name, *_ in CHECKS:
        if name not in modules:
            modules.append(name)

    measured, logs, failures = {}, {}, []
    for name in modules:
        module = importlib.import_module(f"reference.{name}")
        buffer = io.StringIO()
        t0 = time.perf_counter()
        try:
            with contextlib.redirect_stdout(buffer):
                measured[name] = module.main()
            if measured[name] is None:
                # A main() that runs but returns nothing is the exact
                # refactor mistake this gate exists to catch (panel
                # finding: the old 'skip on None' made the harness
                # unable to fail here).
                failures.append((name, "-",
                                 "main() returned None -- its checks "
                                 "cannot be evaluated"))
        except Exception as exc:
            measured[name] = None
            failures.append((name, "-", f"CRASHED: {exc}"))
        logs[name] = buffer.getvalue()
        print(f"{name}: ran in {time.perf_counter() - t0:.0f} s")

    print()
    n_pass = 0
    for name, key, kind, expected, tol in CHECKS:
        if measured.get(name) is None:
            continue
        try:
            value = dig(measured[name], key)
        except (KeyError, TypeError):
            failures.append((name, key, "metric missing from results"))
            continue
        if kind == "abs":
            ok = abs(value - expected) <= tol
            detail = f"{value:.6g} vs {expected:.6g} +/- {tol:g}"
        elif kind == "below":
            ok = value <= expected
            detail = f"{value:.6g} <= {expected:.6g}"
        else:
            ok = value == expected
            detail = f"{value} == {expected}"
        status = "pass" if ok else "FAIL"
        print(f"  {status}  {name}.{key}: {detail}")
        if ok:
            n_pass += 1
        else:
            failures.append((name, key, detail))

    print(f"\n{n_pass} passed, {len(failures)} failed "
          f"of {len(CHECKS)} checks")
    if not failures and n_pass != len(CHECKS):
        failures.append(("run_all", "-",
                         f"only {n_pass} of {len(CHECKS)} checks were "
                         f"evaluated -- refusing to pass a partial gate"))
    if failures:
        print("\nfull output of failing scripts:")
        for name in {f[0] for f in failures if f[0] in logs}:
            print(f"\n----- {name} -----\n{logs[name]}")
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
