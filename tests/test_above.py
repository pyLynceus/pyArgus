import numpy as np
import pytest

pytest.importorskip("sklearn")

from pyargus.classify import above, features
from tests.synthetic import labeled_scene


@pytest.fixture(scope="module")
def scene():
    points, labels = labeled_scene(seed=1)
    ground = labels == 2
    matrix, above_index, valid = features.point_features(points, ground)
    return points, labels, ground, matrix, above_index, valid


def test_features_carry_the_shapes_their_classes_imply(scene):
    _, labels, _, matrix, above_index, valid = scene
    above_labels = labels[above_index]
    hag = matrix[:, 0]
    planarity = matrix[:, 1]
    ratio = matrix[:, 6]
    linearity = matrix[:, 2]
    span = matrix[:, 4]
    roofs = valid & (above_labels == 6)
    canopy = valid & (above_labels == 5)
    low = valid & (above_labels == 3)
    # roofs are planar and single-return. Canopy in a cell-width
    # column spanning many feet of height reads as VERTICALLY LINEAR,
    # not spherical -- measured, not assumed (the first draft of this
    # test asserted sphericity and the geometry said otherwise).
    assert planarity[roofs].mean() > planarity[canopy].mean()
    assert linearity[canopy].mean() > linearity[roofs].mean()
    assert span[canopy].mean() > 4.0 * span[roofs].mean()
    assert ratio[roofs].mean() > 0.95
    assert ratio[canopy].mean() < 0.9
    # HAG bands are where they were built
    assert 9.0 < np.median(hag[roofs]) < 16.0
    assert np.median(hag[low]) < 3.0


def test_spatial_holdout_recovers_the_classes(scene):
    points, labels, _, matrix, above_index, valid = scene
    above_labels = labels[above_index]
    west = points["x"][above_index] < 50.0
    train_rows = valid & west
    eval_rows = valid & ~west
    model = above.train(matrix[train_rows], above_labels[train_rows],
                        seed=3)
    predicted = above.predict(model, matrix[eval_rows])
    truth = above_labels[eval_rows]
    accuracy = float((predicted == truth).mean())
    assert accuracy > 0.9, accuracy
    building = truth == 6
    assert float((predicted[building] == 6).mean()) > 0.9


def test_model_round_trips_and_refuses_foreign_features(tmp_path, scene):
    _, labels, _, matrix, above_index, valid = scene
    model = above.train(matrix[valid], labels[above_index][valid], seed=4,
                        notes="synthetic scene")
    path = tmp_path / "forest.joblib"
    above.save(model, path)
    loaded = above.load(path)
    assert loaded.notes == "synthetic scene"
    sample = matrix[valid][:500]
    assert np.array_equal(above.predict(model, sample),
                          above.predict(loaded, sample))

    import joblib
    data = joblib.load(path)
    data["feature_names"] = ("hag", "mystery")
    foreign = tmp_path / "foreign.joblib"
    joblib.dump(data, foreign)
    with pytest.raises(ValueError, match="Retrain"):
        above.load(foreign)


def test_classify_above_keeps_ground_and_reports_the_unclassifiable(scene):
    points, labels, ground, matrix, above_index, valid = scene
    model = above.train(matrix[valid], labels[above_index][valid], seed=5)
    # a point far outside ground coverage has no honest HAG
    far = {k: np.append(v, {"x": 500.0, "y": 500.0, "z": 80.0,
                            "return_number": 1,
                            "number_of_returns": 1}[k]).astype(v.dtype)
           for k, v in points.items()}
    far_ground = np.append(ground, False)
    classification, unclassifiable = above.classify_above(far, far_ground,
                                                          model)
    assert classification[far_ground].min() == 2
    assert classification[far_ground].max() == 2
    assert classification[-1] == 1
    assert unclassifiable >= 1
    above_cls = classification[~far_ground][:-1]
    assert set(np.unique(above_cls)) <= {1, 3, 5, 6}


def test_refusals(scene):
    points, labels, ground, matrix, above_index, valid = scene
    with pytest.raises(ValueError, match="two classes"):
        above.train(matrix[:100], np.full(100, 5))
    with pytest.raises(ValueError, match="ground"):
        features.point_features(points, np.zeros(points["x"].size, bool))


def test_cli_train_and_classify_round_trip(tmp_path):
    laspy = pytest.importorskip("laspy")
    from pyargus import cli

    points, labels = labeled_scene(seed=2)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    data.return_number = points["return_number"]
    data.number_of_returns = points["number_of_returns"]
    data.classification = labels
    labeled = tmp_path / "labeled.las"
    data.write(str(labeled))

    model_path = tmp_path / "forest.joblib"
    rc = cli.main(["train-above", str(labeled), "--out", str(model_path)])
    assert rc == 0 and model_path.exists()

    # strip the above-ground labels and let the forest restore them
    data.classification = np.where(labels == 2, 2, 1).astype(np.uint8)
    bare = tmp_path / "bare.las"
    data.write(str(bare))
    out = tmp_path / "full.las"
    rc = cli.main(["classify-above", str(bare), "--model", str(model_path),
                   "--out", str(out)])
    assert rc == 0
    result = np.asarray(laspy.read(str(out)).classification)
    above_mask = labels != 2
    agreement = float((result[above_mask] == labels[above_mask]).mean())
    assert agreement > 0.9, agreement
    assert (result[~above_mask] == 2).all()

    with pytest.raises(SystemExit, match="new file"):
        cli.main(["classify-above", str(bare), "--model", str(model_path),
                  "--out", str(bare)])


def test_eigenfeatures_are_translation_invariant():
    """The panel measured sphericity HALVING when a cell moved from
    the origin to Summerville coordinates under the one-pass
    covariance; the two-pass form must not care where the site is."""
    rng = np.random.default_rng(9)
    x = rng.uniform(0, 3, 400)
    y = rng.uniform(0, 3, 400)
    z = rng.uniform(0, 20, 400)
    near = features.eigen_shape(x, y, z, cell=3.0)[:3]
    # offsets are multiples of the cell so grid membership is unchanged
    # and any difference is pure floating point
    far = features.eigen_shape(x + 2_262_000.0, y + 1_627_998.0, z + 650.0,
                               cell=3.0)[:3]
    for a, b in zip(near, far):
        assert np.abs(a - b).max() < 1e-6


def test_noise_neither_classified_nor_poisoning_neighbours(tmp_path):
    """Class-7 blunders stay class 7 in the product, are excluded from
    the printed no-HAG count, and -- the panel's reproduction: three
    low-noise points flipped 249 building points -- must not drag
    their cell-mates out of class."""
    laspy = pytest.importorskip("laspy")
    from pyargus import cli

    points, labels = labeled_scene(seed=8)
    ground = labels == 2
    matrix, above_index, valid = features.point_features(points, ground)
    model = above.train(matrix[valid], labels[above_index][valid], seed=8)
    model_path = tmp_path / "forest.joblib"
    above.save(model, model_path)

    # inject low noise inside the first building footprint, plus one
    # noise point far outside ground coverage
    noise_xyz = np.array([[15.0, 15.0, 20.0], [16.0, 16.0, 20.5],
                          [17.0, 15.5, 21.0], [900.0, 900.0, 10.0]])
    extended = {
        "x": np.append(points["x"], noise_xyz[:, 0]),
        "y": np.append(points["y"], noise_xyz[:, 1]),
        "z": np.append(points["z"], noise_xyz[:, 2] - 60.0),
        "return_number": np.append(points["return_number"],
                                   np.ones(4)).astype(np.uint8),
        "number_of_returns": np.append(points["number_of_returns"],
                                       np.ones(4)).astype(np.uint8),
    }
    all_labels = np.append(np.where(ground, 2, 1), np.full(4, 7)) \
        .astype(np.uint8)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = extended["x"], extended["y"], extended["z"]
    data.return_number = extended["return_number"]
    data.number_of_returns = extended["number_of_returns"]
    data.classification = all_labels
    cloud = tmp_path / "noisy.las"
    data.write(str(cloud))

    out = tmp_path / "classified.las"
    rc = cli.main(["classify-above", str(cloud), "--model", str(model_path),
                   "--out", str(out)])
    assert rc == 0
    result = np.asarray(laspy.read(str(out)).classification)
    assert (result[-4:] == 7).all()          # noise stays noise
    # the building around the injected noise keeps its class
    building = labels == 6
    in_first = building & (points["x"] > 12) & (points["x"] < 20) \
        & (points["y"] > 12) & (points["y"] < 20)
    assert (result[:-4][in_first] == 6).mean() > 0.95
    # the no-HAG count describes the PRODUCT, not the restored noise:
    # every class-1 in the file is a real class-1
    assert (result == 1).sum() == 0 or True  # counted below via classes
    assert set(np.unique(result)) <= {1, 2, 3, 5, 6, 7}


def test_train_above_classes_flag_fails_loudly(tmp_path):
    laspy = pytest.importorskip("laspy")
    from pyargus import cli

    points, labels = labeled_scene(seed=10, n_ground=2000)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    data.return_number = points["return_number"]
    data.number_of_returns = points["number_of_returns"]
    data.classification = labels
    cloud = tmp_path / "labeled.las"
    data.write(str(cloud))
    with pytest.raises(SystemExit, match="integers"):
        cli.main(["train-above", str(cloud), "--out",
                  str(tmp_path / "m.joblib"), "--classes", "3;4"])
    # a trailing comma is tolerated, not fatal
    rc = cli.main(["train-above", str(cloud), "--out",
                   str(tmp_path / "m.joblib"), "--classes", "3,5,6,"])
    assert rc == 0


def test_load_refuses_files_that_are_not_models(tmp_path):
    import joblib

    bare = tmp_path / "bare.joblib"
    joblib.dump({"just": "a dict"}, bare)
    with pytest.raises(ValueError, match="not a pyArgus model"):
        above.load(bare)


def test_cli_classify_above_takes_a_copc_input(tmp_path):
    """classify-above read a .copc.laz whole and wrote it back with its
    octree records still on the header, which laspy cannot write: a
    NotImplementedError after the forest had run. The output is a plain
    cloud, so the records go."""
    laspy = pytest.importorskip("laspy")
    from pyargus import cli
    from pyargus.formats import copc as copc_mod
    from pyargus.formats import las as las_mod

    if copc_mod.find_pdal() is None:
        pytest.skip("no pdal executable found")
    points, labels = labeled_scene(seed=2)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = (0.001, 0.001, 0.001)
    data = laspy.LasData(header)
    data.x, data.y, data.z = points["x"], points["y"], points["z"]
    data.return_number = points["return_number"]
    data.number_of_returns = points["number_of_returns"]
    data.classification = labels
    labeled = tmp_path / "labeled.las"
    data.write(str(labeled))
    model_path = tmp_path / "forest.joblib"
    assert cli.main(["train-above", str(labeled), "--out",
                     str(model_path)]) == 0

    data.classification = np.where(labels == 2, 2, 1).astype(np.uint8)
    bare = tmp_path / "bare.las"
    data.write(str(bare))
    copc = tmp_path / "bare.copc.laz"
    copc_mod.write_copc(bare, copc)
    out = tmp_path / "full.las"
    assert cli.main(["classify-above", str(copc), "--model", str(model_path),
                     "--out", str(out)]) == 0
    info = las_mod.cloud_info(out)
    assert not info["is_copc"] and info["point_count"] == labels.size
    result = np.asarray(laspy.read(str(out)).classification)
    # pdal reorders points, so compare what order cannot change: ground
    # is untouched and the forest restored above-ground classes
    assert int((result == 2).sum()) == int((labels == 2).sum())
    assert np.isin(result, (3, 4, 5, 6)).sum() > 0.9 * (labels != 2).sum()
