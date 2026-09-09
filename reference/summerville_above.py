"""Phase-5 acceptance: the forest against Summerville's delivered
above-ground classes.

Spatial holdout, not a random split: train on the west half, evaluate
on the east, so the score measures transfer across ground the model
never saw rather than memorization of its own neighborhood. The
delivered classification is the answer key with the usual caveat: it
is a strong reference, not truth, and the confusion measures distance
from it.

Read-only against Z:. Run: python -m reference.summerville_above
"""

import time

import numpy as np

from pyargus.classify import above, features
from pyargus.formats import las
from reference.summerville import CLOUD

CLASSES = (3, 4, 5, 6)


def main():
    results = {}
    print(f"cloud: {CLOUD}")
    points = las.read_points(
        CLOUD, fields=("x", "y", "z", "classification",
                       "return_number", "number_of_returns"))
    delivered = points["classification"]
    ground = delivered == 2

    t0 = time.perf_counter()
    matrix, above_index, valid = features.point_features(points, ground)
    print(f"features: {matrix.shape[0]:,} above-ground points, "
          f"{int((~valid).sum()):,} without HAG, "
          f"{time.perf_counter() - t0:.0f} s")

    labels = delivered[above_index]
    labeled = valid & np.isin(labels, CLASSES)
    west = points["x"][above_index] < float(np.median(points["x"]))
    train_rows = labeled & west
    eval_rows = labeled & ~west
    print(f"train (west): "
          f"{ {int(c): int((labels[train_rows] == c).sum()) for c in CLASSES} }")
    print(f"eval  (east): "
          f"{ {int(c): int((labels[eval_rows] == c).sum()) for c in CLASSES} }")

    t0 = time.perf_counter()
    model = above.train(matrix[train_rows], labels[train_rows],
                        notes="Summerville west half")
    predicted = above.predict(model, matrix[eval_rows])
    truth = labels[eval_rows]
    print(f"train+predict: {time.perf_counter() - t0:.0f} s")

    agreement = float((predicted == truth).mean())
    expected = sum(float((truth == c).mean()) * float((predicted == c).mean())
                   for c in CLASSES)
    kappa = (agreement - expected) / (1.0 - expected)
    results["agreement"] = agreement
    results["kappa"] = float(kappa)
    print(f"\n[eval vs delivered] agreement {agreement:.4f}  "
          f"kappa {kappa:.4f}")
    for c in CLASSES:
        m = truth == c
        p = predicted == c
        recall = float((predicted[m] == c).mean()) if m.any() else float("nan")
        precision = float((truth[p] == c).mean()) if p.any() else float("nan")
        print(f"  class {c}: recall {recall:.3f}  precision {precision:.3f}"
              f"  n {int(m.sum()):,}")

    # the metric that matters most: building vs any vegetation
    b_truth = truth == 6
    b_pred = predicted == 6
    results["building_recall"] = float(
        (b_pred & b_truth).sum() / max(b_truth.sum(), 1))
    results["building_precision"] = float(
        (b_pred & b_truth).sum() / max(b_pred.sum(), 1))
    print(f"  building-vs-veg: recall "
          f"{float((b_pred & b_truth).sum() / max(b_truth.sum(), 1)):.3f}  "
          f"precision "
          f"{float((b_pred & b_truth).sum() / max(b_pred.sum(), 1)):.3f}")

    ranked = sorted(zip(features.FEATURE_NAMES,
                        model.forest.feature_importances_),
                    key=lambda pair: -pair[1])
    print("features: " + "  ".join(f"{n}={v:.3f}" for n, v in ranked))

    # --- deployment conditions: the SAME forest behind SMRF ground ---
    # The panel's honesty finding: the score above is measured behind
    # the delivered (thin, curated) ground, but deployment runs behind
    # SMRF ground, which is thicker (+0.111 ft DTM median, Phase 3).
    # Same eval half, same delivered labels; features and the HAG datum
    # now come from SMRF ground, and points SMRF swallowed into ground
    # leave the eval universe. The delta is the train/deploy shift.
    from pyargus.classify import ground as ground_mod

    t0 = time.perf_counter()
    last = points["return_number"] == points["number_of_returns"]
    smrf = ground_mod.smrf(points["x"][last], points["y"][last],
                           points["z"][last], cell=3.0, slope=0.15,
                           window=60.0, threshold=1.5, scalar=1.25)
    smrf_ground = np.zeros(points["x"].size, dtype=bool)
    smrf_ground[np.flatnonzero(last)[smrf.ground]] = True
    noise = delivered == 7
    matrix2, above2, valid2 = features.point_features(
        points, smrf_ground, ignore_mask=noise)
    labels2 = delivered[above2]
    east2 = points["x"][above2] >= float(np.median(points["x"]))
    eval2 = valid2 & east2 & np.isin(labels2, CLASSES)
    predicted2 = above.predict(model, matrix2[eval2])
    truth2 = labels2[eval2]
    agreement2 = float((predicted2 == truth2).mean())
    print(f"\n[deployment: same forest behind SMRF ground] "
          f"{time.perf_counter() - t0:.0f} s")
    print(f"  eval universe {int(eval2.sum()):,} "
          f"(delivered-ground eval had {int(eval_rows.sum()):,}; the "
          f"difference was absorbed into SMRF's thicker ground)")
    results["deploy_agreement"] = agreement2
    print(f"  agreement {agreement2:.4f}  (delta "
          f"{agreement2 - agreement:+.4f} vs delivered-ground scoring)")
    for c in CLASSES:
        m = truth2 == c
        if m.any():
            print(f"  class {c}: recall "
                  f"{float((predicted2[m] == c).mean()):.3f}  "
                  f"n {int(m.sum()):,}")

    # what does the forest call the delivered class-1 (unclassified)?
    rest = valid & (labels == 1) & ~west
    if rest.any():
        u, c = np.unique(above.predict(model, matrix[rest]),
                         return_counts=True)
        share = {int(k): round(float(v) / rest.sum(), 3)
                 for k, v in zip(u, c)}
        print(f"delivered class 1 (east, {int(rest.sum()):,} pts) "
              f"predicted as: {share}")
    return results


if __name__ == "__main__":
    main()
