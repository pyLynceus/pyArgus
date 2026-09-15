"""The colorize job, once, for every front end.

The CLI and the desktop application need the same sequence -- resolve
a camera per role tag, gate the datum, colorize, judge coverage,
stream the RGB out -- and the Phase-7 review round is the reason it
lives here rather than twice: the GUI's alignment defaults had quietly
drifted from the CLI's, and nothing noticed until a panel went
looking. One function, two thin callers, and the defaults come from
``pyargus.cli.build_parser`` in the test that pins them.

Every refusal raises ValueError with the reason. The CLI turns those
into SystemExit, the GUI shows them in its log; neither invents its
own wording.
"""

from pathlib import Path

import numpy as np

RGB_POINT_FORMATS = frozenset({2, 3, 5, 7, 8, 10})
"""LAS point formats carrying red/green/blue. 6 and 9 do not, and a
cloud in one of those is converted on the way out."""


def resolve_cameras(eo, image_paths, *, cal=None, quarter_turns=3,
                    log=None, provenance=None):
    """Check every matched frame before sharing one camera per role.

    Equivalent projection parameters may come from different sidecars. A
    role is not a physical camera ID: conflicting parameters must not be
    collapsed to the first frame's lens. An explicit cal overrides sidecars.
    Optional provenance receives one record per distinct matched image.
    """
    import hashlib
    from pyargus.formats import eo as eo_mod
    from pyargus.imagery import camera as camera_mod

    fields = ("focal_px", "width_px", "height_px", "cx_px", "cy_px",
              "k1", "k2", "k3", "p1", "p2", "quarter_turns")
    cameras, sources, cached, seen = {}, {}, {}, set()
    records = []
    for name in eo["filename"]:
        key = name.lower()
        sample = image_paths.get(key)
        if sample is None or key in seen:
            continue
        seen.add(key)
        sample = Path(sample)
        tag = eo_mod.camera_tag(name)
        found = Path(cal) if cal else camera_mod.find_cal(sample)
        if found is None:
            raise ValueError(f"no .cal calibration sidecar found for {sample.name}; "
                             "supply that image's calibration or an explicit --cal file")
        found = found.resolve()
        if found not in cached:
            digest = hashlib.sha256(found.read_bytes()).hexdigest()
            cam = camera_mod.read_cal(found, quarter_turns=quarter_turns)
            if hashlib.sha256(found.read_bytes()).hexdigest() != digest:
                raise ValueError(f"calibration changed while reading: {found}")
            params = {f: getattr(cam, f) for f in fields}
            if not all(np.isfinite(v) for v in params.values()):
                raise ValueError(f"nonfinite camera parameters in {found}")
            cached[found] = cam, params, digest
        cam, params, digest = cached[found]
        if tag in cameras:
            differing = [f for f in fields if getattr(cameras[tag], f) != params[f]]
            if differing:
                raise ValueError(
                    f"conflicting calibrations for camera role {tag or '(untagged)'}: "
                    f"{sources[tag]} versus {found} for image {sample.name}; "
                    f"differing parameters: {', '.join(differing)}. "
                    "Separate the camera groups or provide a verified common "
                    "calibration explicitly; refusing to use the first frame's lens.")
        else:
            cameras[tag], sources[tag] = cam, found
        records.append(dict(image=str(sample.resolve()), role=tag,
                            calibration=str(found), sha256=digest,
                            selection="explicit" if cal else "sidecar",
                            parameters=params))
        if log is not None and len(records) % 100 == 0:
            log(f"calibration: checked {len(records)} matched images")
    if not cameras:
        raise ValueError("none of the EO rows' images exist under the imagery "
                         "directory; wrong imagery path, or the wrong flight?")
    if provenance is not None:
        provenance.extend(records)
    if log is not None:
        for tag, cam in sorted(cameras.items(), key=lambda kv: str(kv[0])):
            count = sum(r["role"] == tag for r in records)
            log(f"camera {tag or '-'}: verified {count} images; "
                f"f {cam.focal_px:.1f} px, pp ({cam.cx_px:+.1f}, "
                f"{cam.cy_px:+.1f}) px; {cam.width_px}x{cam.height_px}; "
                f"quarter turns {cam.quarter_turns}; "
                f"{'explicit override' if cal else 'sidecar consistency checked'}")
    return cameras


def check_datum(eo, xyz):
    """Refuse an EO/cloud pairing that cannot be the same site.

    Returns the median flying height. The unit and CRS traps arrive as
    geometry: EO that does not overlap the cloud, or that sits below
    its ground, is a frame mismatch however plausible the numbers look
    in isolation. What this CANNOT catch is a mismatch that merely
    SCALES the two (metres written over survey feet keeps the boxes
    overlapping on a site-local grid) -- coverage is what that looks
    like, and the caller judges it after colorizing.
    """
    if xyz.shape[0] == 0:
        raise ValueError(
            "the cloud holds no points, so there is nothing to colorize "
            "and no extent to check the EO against")
    lo = xyz[:, :2].min(axis=0)
    hi = xyz[:, :2].max(axis=0)
    olo = eo["origin"][:, :2].min(axis=0)
    ohi = eo["origin"][:, :2].max(axis=0)
    if (ohi < lo).any() or (olo > hi).any():
        raise ValueError(
            "the EO positions do not overlap the cloud horizontally -- "
            "that is what a wrong unit (the LP360 header says [m] even "
            "when the values are survey feet) or a different CRS looks "
            "like. Refusing to colorize.")
    agl = float(np.median(eo["origin"][:, 2]) - np.median(xyz[:, 2]))
    if agl <= 0:
        raise ValueError(
            f"the EO heights sit {-agl:.0f} map units BELOW the cloud's "
            f"ground -- a vertical datum or unit mismatch. Refusing to "
            f"colorize.")
    return agl


def colorize_cloud(cloud, eo_path, images, out, *, cal=None,
                   quarter_turns=3, neighbors=8, occlusion_tol=3.0,
                   min_coverage=5.0, memory_budget_mb=None,
                   coverage_label="the coverage floor",
                   log=print, progress=None, should_stop=None):
    """Paint ``cloud`` from oriented imagery and write ``out``.

    Returns the stats dict from the colorizer plus ``pct_colored`` and
    ``point_format``. ``should_stop()`` is polled before the write, so
    a cancelled run leaves nothing on disk.
    """
    from pyargus.formats import eo as eo_mod
    from pyargus.formats import las as las_mod
    from pyargus.imagery import colorize as colorize_mod

    cloud, out = Path(cloud), Path(out)
    if out.resolve() == cloud.resolve():
        raise ValueError("refusing to overwrite the input cloud; the "
                         "coloured cloud must be a new file")

    eo = eo_mod.read_eo_csv(eo_path)
    image_paths = colorize_mod.find_images(images)
    if not image_paths:
        raise ValueError(f"no images found under {images}")
    calibration_provenance = []
    cameras = resolve_cameras(eo, image_paths, cal=cal,
                              quarter_turns=quarter_turns, log=log,
                              provenance=calibration_provenance)

    points = las_mod.read_points(cloud, fields=("x", "y", "z"))
    xyz = np.column_stack([points["x"], points["y"], points["z"]])
    del points
    agl = check_datum(eo, xyz)
    log(f"eo:      {len(eo['filename'])} rows, flying height "
        f"~{agl:.0f} above the cloud median")

    # memory_budget_mb stays UNSET unless a caller asks: passing a
    # number here would silently override colorize()'s own default,
    # which is what the extraction did (256 -> 512) with nothing to
    # notice
    budget = ({} if memory_budget_mb is None
              else {"memory_budget_mb": memory_budget_mb})
    rgb, stats = colorize_mod.colorize(
        xyz, eo, cameras, image_paths, neighbors=neighbors,
        occlusion_tol=occlusion_tol, progress=progress, **budget)
    del xyz
    stats["calibration_provenance"] = calibration_provenance
    pct = 100.0 * stats["n_colored"] / stats["n_points"]
    stats["pct_colored"] = pct
    log(f"colored: {stats['n_colored']:,} of {stats['n_points']:,} points "
        f"({pct:.1f}%) from {stats['n_images_used']} images")
    log(f"skipped: {stats['n_occluded']:,} hidden in every candidate "
        f"frame, {stats['n_unseen']:,} seen by no nearby photo"
        + (f"; {stats['n_eo_dropped']} EO rows had no image file"
           if stats["n_eo_dropped"] else ""))
    if pct < min_coverage:
        raise ValueError(
            f"only {pct:.1f}% of the cloud got a color, below the "
            f"{min_coverage}% set by {coverage_label}. That is what a "
            f"unit or datum mismatch between the EO and the cloud looks "
            f"like (metres vs survey feet, ellipsoidal vs orthometric "
            f"heights), or imagery from the wrong flight. Nothing was "
            f"written; lower it to colorize a subset deliberately.")
    if pct < 50.0:
        log("caution: less than half the cloud got a color. That is "
            "normal when the imagery covers only part of the block -- "
            "and it is also what a vertical datum or unit mismatch looks "
            "like, since a flying height in metres over a survey-feet "
            "cloud shrinks every footprint by 3.28. Check the flying "
            "height above against the mission.")

    if should_stop is not None and should_stop():
        return stats

    source_format = las_mod.cloud_info(cloud)["point_format"]
    target_format = None
    if source_format not in RGB_POINT_FORMATS:
        target_format = 7
        log(f"format:  point format {source_format} carries no RGB; "
            f"converting to 7")

    def paint(chunk, start):
        block = rgb[start:start + chunk["x"].size]
        return {"red": block[:, 0], "green": block[:, 1],
                "blue": block[:, 2]}

    las_mod.stream_update(cloud, out, paint, fields=("x",),
                          point_format=target_format)
    stats["point_format"] = target_format or source_format
    log(f"wrote:   {out}")
    return stats
