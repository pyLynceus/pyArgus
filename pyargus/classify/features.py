"""Per-point geometric features for above-ground classification.

The feature set is handcrafted and explainable on purpose (the
roadmap's bet: a tunable forest before any deep model): height above
the ground surface, the eigenvalue shape of the point's cell
neighborhood (a roof is planar, a canopy is scattered), the cell's
vertical roughness, and the return structure (vegetation splits
pulses, roofs do not).

Neighborhoods are grid cells, not kNN balls -- at UAS densities a
3-ft cell holds tens of points, the whole cloud vectorizes through
bincount accumulations and one batched eigvalsh, and 14M points take
seconds instead of the minutes a tree query costs. Cells too thin to
have a shape (< 3 points) get zero shape features and let the forest
lean on the other columns.
"""

import numpy as np

from pyargus.core import gridding

FEATURE_NAMES = ("hag", "planarity", "linearity", "sphericity",
                 "cell_hag_range", "cell_count", "return_ratio",
                 "number_of_returns")


def eigen_shape(x, y, z, cell):
    """Per-point eigenvalue shape of the point's cell: (linearity,
    planarity, sphericity), each in [0, 1], zeros where the cell has
    fewer than 3 points."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    x_edges, y_edges = gridding.grid_edges(x, y, cell)
    ix, iy = gridding.cell_indices(x, y, x_edges, y_edges)
    ny = len(y_edges) - 1
    cid = ix * ny + iy
    n_cells = (len(x_edges) - 1) * ny

    count = np.bincount(cid, minlength=n_cells).astype(float)
    n = np.maximum(count, 1.0)
    # Two passes on purpose: the one-pass E[x^2] - mean^2 form cancels
    # catastrophically at state-plane magnitudes (~2e6 ft) and made the
    # shape features translation-VARIANT -- sphericity halved when the
    # same cell moved from the origin to Summerville coordinates
    # (measured by the review panel). Deviations first, squares second.
    mean_x = np.bincount(cid, weights=x, minlength=n_cells) / n
    mean_y = np.bincount(cid, weights=y, minlength=n_cells) / n
    mean_z = np.bincount(cid, weights=z, minlength=n_cells) / n
    dx = x - mean_x[cid]
    dy = y - mean_y[cid]
    dz = z - mean_z[cid]
    cov = np.zeros((n_cells, 3, 3))
    cov[:, 0, 0] = np.bincount(cid, weights=dx * dx, minlength=n_cells) / n
    cov[:, 1, 1] = np.bincount(cid, weights=dy * dy, minlength=n_cells) / n
    cov[:, 2, 2] = np.bincount(cid, weights=dz * dz, minlength=n_cells) / n
    cov[:, 0, 1] = cov[:, 1, 0] = np.bincount(
        cid, weights=dx * dy, minlength=n_cells) / n
    cov[:, 0, 2] = cov[:, 2, 0] = np.bincount(
        cid, weights=dx * dz, minlength=n_cells) / n
    cov[:, 1, 2] = cov[:, 2, 1] = np.bincount(
        cid, weights=dy * dz, minlength=n_cells) / n

    thin = count < 3
    cov[thin] = np.eye(3)  # placeholder; zeroed below
    lam = np.linalg.eigvalsh(cov)[:, ::-1]     # descending
    lam = np.maximum(lam, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        l1 = np.maximum(lam[:, 0], 1e-12)
        linearity = (lam[:, 0] - lam[:, 1]) / l1
        planarity = (lam[:, 1] - lam[:, 2]) / l1
        sphericity = lam[:, 2] / l1
    for feat in (linearity, planarity, sphericity):
        feat[thin] = 0.0
    return (linearity[cid], planarity[cid], sphericity[cid],
            count[cid], cid, n_cells)


def point_features(points, ground_mask, *, ignore_mask=None, cell=3.0,
                   dtm_cell=3.0, max_fill=10):
    """Features for every NON-ground point not in ``ignore_mask``.

    ``ignore_mask`` exists for noise: a class-7 blunder fed through the
    cell statistics poisons the eigenfeatures and HAG span of every
    legitimate point sharing its cell (three injected low-noise points
    flipped 249 building points in the panel's reproduction), so noise
    is excluded from the computation, never merely relabeled after.

    Returns (matrix, above_index, valid) where ``matrix`` is
    (n_above, len(FEATURE_NAMES)), ``above_index`` are the point
    indices it describes, and ``valid`` marks rows whose height above
    ground is defined -- points beyond ``max_fill`` cells of any
    ground data have no honest HAG and must not be classified by it
    (the caller reports them, class 1).
    """
    from pyargus.surfaces import dtm

    for name in ("x", "y", "z", "return_number", "number_of_returns"):
        if name not in points:
            raise ValueError(f"points need field {name!r} for features")
    ground_mask = np.asarray(ground_mask, dtype=bool)
    if not ground_mask.any():
        raise ValueError("no ground points; classify ground first")
    keep = ~ground_mask
    if ignore_mask is not None:
        keep &= ~np.asarray(ignore_mask, dtype=bool)
    above_index = np.flatnonzero(keep)
    if above_index.size == 0:
        raise ValueError("every point is ground; nothing to classify")

    grid, x_edges, y_edges = dtm.dtm_grid(
        points["x"][ground_mask], points["y"][ground_mask],
        points["z"][ground_mask], dtm_cell, max_fill=max_fill)
    ax = points["x"][above_index]
    ay = points["y"][above_index]
    az = points["z"][above_index]
    ground_z = gridding.bilinear_sample(
        np.where(np.isfinite(grid), grid, np.nan), ax, ay,
        x_edges, y_edges)
    hag = az - ground_z
    # bilinear_sample CLAMPS to the grid, so a point far outside the
    # ground extent would silently read the edge cell's elevation --
    # its HAG must be declared unknowable instead (caught by test).
    inside = ((ax >= x_edges[0]) & (ax <= x_edges[-1])
              & (ay >= y_edges[0]) & (ay <= y_edges[-1]))
    valid = inside & np.isfinite(hag)

    linearity, planarity, sphericity, cell_count, cid, n_cells = \
        eigen_shape(ax, ay, az, cell)
    # per-cell HAG roughness: max - min of finite HAG in the cell
    safe = np.where(valid, hag, 0.0)
    top = np.full(n_cells, -np.inf)
    bottom = np.full(n_cells, np.inf)
    np.maximum.at(top, cid[valid], safe[valid])
    np.minimum.at(bottom, cid[valid], safe[valid])
    span = np.where(np.isfinite(top) & np.isfinite(bottom),
                    top - bottom, 0.0)

    ratio = (points["return_number"][above_index].astype(float)
             / np.maximum(points["number_of_returns"][above_index], 1))
    matrix = np.column_stack([
        np.where(valid, hag, 0.0), planarity, linearity, sphericity,
        span[cid], cell_count, ratio,
        points["number_of_returns"][above_index].astype(float)])
    return matrix, above_index, valid
