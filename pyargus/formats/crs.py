"""Trajectory coordinates into the delivery frame.

An SBET is geographic NAD83(2011) with ELLIPSOIDAL heights in meters;
a delivery cloud lives in a projected CRS with orthometric heights.
The vertical gap is the geoid -- about 95 ft at Summerville -- and a
trajectory carried across without it poisons the boresight lever arm
(the solver needs nav heights good to roughly 1% of AGL).

The trap this module exists to refuse: a delivered LAS often declares
only a HORIZONTAL CRS (Summerville does). Hand that to pyproj and it
transforms E/N into survey feet while passing the height through in
ellipsoidal METERS -- no error, no warning, coordinates that look
plausible on a map and are ~450 ft wrong vertically. So heights are
never transformed implicitly here: the caller states the vertical
story, or this module raises.
"""

import numpy as np

NAD83_2011_GEOGRAPHIC_2D = "EPSG:6318"
NAD83_2011_GEOGRAPHIC_3D = "EPSG:6319"


def _pyproj():
    try:
        import pyproj
    except ImportError as exc:
        raise ImportError(
            "transforming trajectories needs pyproj: "
            "uv pip install -e \".[crs]\"") from exc
    return pyproj


def sbet_to_map(sbet, map_crs, *, vertical=None, allow_network=False):
    """Transform SBET lat/lon/alt into the delivery map frame.

    ``map_crs`` is anything pyproj accepts (the LAS header's CRS, an
    EPSG string). ``vertical`` states how heights become orthometric:

    * a vertical CRS (e.g. ``"EPSG:6360"`` for NAVD88 ftUS) -- composed
      with map_crs's horizontal part; PROJ then needs the geoid grid
      (``allow_network=True`` lets it fetch and cache one).
    * a float -- geoid undulation N in METERS (H = h - N), heights then
      converted into the map CRS's linear unit. A constant is fine for
      a project site: N varies by centimeters over a mile.
    * None -- allowed only when map_crs is already compound.

    Returns (e, n, z) arrays in map units.
    """
    pyproj = _pyproj()
    if allow_network:
        pyproj.network.set_network_enabled(True)
    crs = pyproj.CRS.from_user_input(map_crs)
    lon = np.degrees(np.asarray(sbet["lon"], dtype=float))
    lat = np.degrees(np.asarray(sbet["lat"], dtype=float))
    h = np.asarray(sbet["alt"], dtype=float)

    horizontal = crs.sub_crs_list[0] if crs.is_compound else crs
    if horizontal.is_geographic:
        raise ValueError(f"map_crs must be projected, got {horizontal.name}")

    if isinstance(vertical, (int, float)) and not isinstance(vertical, bool):
        # Height unit: the compound's VERTICAL component when there is
        # one (a metric-horizontal + ftUS-height delivery is a real DOT
        # convention), else the horizontal linear unit.
        unit_source = crs.sub_crs_list[1] if crs.is_compound else horizontal
        factor = unit_source.axis_info[0].unit_conversion_factor  # m per unit
        tf = pyproj.Transformer.from_crs(NAD83_2011_GEOGRAPHIC_2D, horizontal,
                                         always_xy=True)
        e, n = tf.transform(lon, lat)
        z = (h - float(vertical)) / factor
    else:
        if vertical is not None:
            target = pyproj.crs.CompoundCRS(
                name=f"{horizontal.name} + {vertical}",
                components=[horizontal, pyproj.CRS.from_user_input(vertical)])
        elif crs.is_compound:
            target = crs
        else:
            raise ValueError(
                f"{crs.name} declares no vertical CRS; transforming the "
                f"trajectory through it would keep heights in ellipsoidal "
                f"meters. State the vertical story: vertical=\"EPSG:6360\" "
                f"(NAVD88 ftUS, composed with the horizontal), or "
                f"vertical=<geoid undulation N in meters>.")
        # allow_ballpark=False: without it, a missing geoid grid makes
        # PROJ silently substitute a "ballpark vertical transformation"
        # that returns FINITE heights still ellipsoidal -- ~95 ft wrong
        # here and invisible to any finiteness check (only_best alone
        # does NOT stop it; measured). Adversarially verified; never
        # remove either flag.
        try:
            tf = pyproj.Transformer.from_crs(
                NAD83_2011_GEOGRAPHIC_3D, target, always_xy=True,
                allow_ballpark=False, only_best=True)
            e, n, z = tf.transform(lon, lat, h, errcheck=True)
        except pyproj.exceptions.ProjError as exc:
            raise ValueError(
                "the vertical transform is not available -- PROJ is missing "
                "the geoid grid. Pass allow_network=True to let it fetch and "
                "cache one, or supply vertical=<geoid shift in meters>."
            ) from exc
        if not (np.all(np.isfinite(e)) and np.all(np.isfinite(n))
                and np.all(np.isfinite(z))):
            raise ValueError(
                "the vertical transform produced non-finite heights -- PROJ "
                "is missing the geoid grid. Pass allow_network=True to let "
                "it fetch one, or supply vertical=<geoid shift in meters>.")
    return np.asarray(e), np.asarray(n), np.asarray(z)
