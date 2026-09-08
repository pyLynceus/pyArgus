"""Above-ground classification: a random forest over the features.

ASPRS targets: 3 low vegetation, 4 medium, 5 high, 6 building. The
forest is trained on a labeled reference cloud (a delivered
classification is the free answer key) and applied to new clouds with
the caveat every transferred model carries: it learned one site's
sensor, density, and season. A provenance note travels in the model
file; the acceptance numbers live in reference/RESULTS.md and do not
transfer with the pickle -- quote them from there, with their site.

scikit-learn stays behind the lazy-import pattern; persistence is
joblib, which is a pickle -- a model file is bound to the sklearn
major version that wrote it, and load() says so instead of crashing
downstream.
"""

from dataclasses import dataclass

import numpy as np

from pyargus.classify.features import FEATURE_NAMES, point_features


def _sklearn():
    try:
        import sklearn  # noqa: F401
        from sklearn.ensemble import RandomForestClassifier
    except ImportError as exc:
        raise ImportError(
            "above-ground classification needs scikit-learn: "
            "uv pip install -e \".[ml]\"") from exc
    return RandomForestClassifier


@dataclass
class AboveModel:
    forest: object
    feature_names: tuple
    classes: tuple
    notes: str = ""


def train(matrix, labels, *, subsample_per_class=150_000,
          n_estimators=100, seed=0, notes=""):
    """Train the forest on labeled feature rows.

    Classes are whatever the labels carry (typically 3/4/5/6). Each
    class is capped at ``subsample_per_class`` rows so one dominant
    class cannot drown the others and training stays in minutes.
    """
    RandomForestClassifier = _sklearn()
    matrix = np.asarray(matrix, dtype=float)
    labels = np.asarray(labels)
    if matrix.shape[0] != labels.shape[0]:
        raise ValueError("features and labels must align")
    classes = np.unique(labels)
    if classes.size < 2:
        raise ValueError(f"training needs at least two classes, got "
                         f"{classes.tolist()}")
    rng = np.random.default_rng(seed)
    keep = []
    for value in classes:
        rows = np.flatnonzero(labels == value)
        if rows.size > subsample_per_class:
            rows = rng.choice(rows, subsample_per_class, replace=False)
        keep.append(rows)
    keep = np.concatenate(keep)
    forest = RandomForestClassifier(
        n_estimators=n_estimators, min_samples_leaf=5, n_jobs=-1,
        class_weight="balanced_subsample", random_state=seed)
    forest.fit(matrix[keep], labels[keep])
    return AboveModel(forest=forest, feature_names=tuple(FEATURE_NAMES),
                      classes=tuple(int(v) for v in classes), notes=notes)


def predict(model, matrix):
    return model.forest.predict(np.asarray(matrix, dtype=float))


def save(model, path):
    import joblib
    import sklearn

    joblib.dump({"forest": model.forest,
                 "feature_names": model.feature_names,
                 "classes": model.classes,
                 "notes": model.notes,
                 "sklearn_version": sklearn.__version__}, path)


def load(path):
    """Load a model written by save(). A joblib file is a pickle:
    loading it executes code, so only open model files you made or
    trust."""
    import joblib
    import sklearn

    data = joblib.load(path)
    required = {"forest", "feature_names", "classes"}
    if not isinstance(data, dict) or not required <= set(data):
        raise ValueError(
            f"{path} is not a pyArgus model file (expected a dict with "
            f"{sorted(required)}; got {type(data).__name__}). Train one "
            f"with 'pyargus train-above'.")
    written = data.get("sklearn_version", "unknown")
    if written.split(".")[0] != sklearn.__version__.split(".")[0]:
        raise ValueError(
            f"{path} was written by scikit-learn {written}; this "
            f"environment runs {sklearn.__version__}. A forest pickle "
            f"does not cross major versions -- retrain, or match the "
            f"version.")
    if tuple(data["feature_names"]) != tuple(FEATURE_NAMES):
        raise ValueError(
            f"{path} was trained on features {data['feature_names']}; "
            f"this code computes {FEATURE_NAMES}. Retrain.")
    return AboveModel(forest=data["forest"],
                      feature_names=tuple(data["feature_names"]),
                      classes=tuple(data["classes"]),
                      notes=data.get("notes", ""))


def classify_above(points, ground_mask, model, *, ignore_mask=None,
                   cell=3.0):
    """Full-cloud classification: ground stays 2, above-ground points
    get the forest's answer, points without an honest HAG stay 1.
    Points in ``ignore_mask`` (noise) are excluded from the features
    AND the statistics; the caller restores their labels.

    Returns (classification array, n_unclassifiable)."""
    matrix, above_index, valid = point_features(
        points, ground_mask, ignore_mask=ignore_mask, cell=cell)
    classification = np.full(points["x"].size, 1, dtype=np.uint8)
    classification[np.asarray(ground_mask, dtype=bool)] = 2
    if valid.any():
        predicted = predict(model, matrix[valid])
        classification[above_index[valid]] = predicted.astype(np.uint8)
    return classification, int((~valid).sum())
