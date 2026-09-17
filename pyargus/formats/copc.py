"""Writing COPC, which laspy cannot do.

A COPC file is a LAZ whose points are arranged into an octree and
indexed, so a reader can ask for a bounding box or a resolution and
decompress only the nodes it needs. laspy READS that happily
(``las.copc_query``); nothing in laspy or lazrs writes it, and no
amount of care with headers can add an octree to a file that has
none. Building one means an external tool: pdal, untwine or copc-lib.

This module shells out to pdal, and is deliberate about three things
the recon measured:

* **It probes rather than assuming.** pdal is commonly present only
  inside a QGIS install and not on PATH. ``find_pdal`` looks on PATH
  first, then at the usual QGIS locations, and the caller can name
  one. Absent, it refuses with the reason and the options rather than
  producing a confusing failure deep inside a subprocess.
* **It always forwards the metadata.** pdal's COPC writer SILENTLY
  drops extra dimensions unless told otherwise -- Summerville's
  Amplitude/Reflectance/Deviation would vanish with no error and no
  warning -- and the scales, offsets and CRS need ``forward=all`` for
  the same reason. Both are passed on every call, never optional.
* **It verifies the result.** After pdal returns, the output is
  reopened and its point count, extra dimensions and COPC VLR are
  checked against the source. A converter that quietly loses a
  dimension is worse than one that fails.

POINT ORDER DOES NOT SURVIVE. Building the octree REORDERS the points,
so row *i* of a COPC copy is not row *i* of its source. Anything that
pairs the two by index -- applying a per-point array computed against
the original, diffing two classifications element-wise -- is wrong on
a COPC file and will look like a scattering of disagreements rather
than an error. (It cost an afternoon here: a tiled-classification
check read as 4,330 mismatches until the orders were matched, at which
point it was exact.)
"""

import os
import shutil
import subprocess
from pathlib import Path

_QGIS_GLOBS = (
    r"C:/Program Files/QGIS */bin/pdal.exe",
    r"C:/OSGeo4W/bin/pdal.exe",
    r"C:/OSGeo4W64/bin/pdal.exe",
)


def find_pdal(explicit=None):
    """The pdal executable, or None.

    Order: an explicit path, then ``PDAL_EXE`` in the environment,
    then PATH, then the usual QGIS/OSGeo4W install locations (pdal
    ships inside QGIS on Windows and is not put on PATH).
    """
    if explicit:
        path = Path(explicit)
        return str(path) if path.is_file() else None
    from_env = os.environ.get("PDAL_EXE")
    if from_env and Path(from_env).is_file():
        return from_env
    found = shutil.which("pdal")
    if found:
        return found
    import glob
    for pattern in _QGIS_GLOBS:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None


def write_copc(src, dst, *, pdal=None, timeout=None):
    """Rewrite a LAS/LAZ as COPC. Returns a dict about the result.

    Refuses rather than guessing when pdal is missing, when the
    conversion fails, or when the output lost points or dimensions on
    the way through.
    """
    from pyargus.formats import las as las_mod

    # The caller's own arguments are judged FIRST: a bad output name is
    # knowable without any external tool, and probing for pdal ahead of
    # it answered "install pdal" to someone whose real mistake was the
    # filename -- and left the naming rule unreachable, and untested, on
    # every machine without pdal.
    src, dst = Path(src), Path(dst)
    if not str(dst).endswith(".copc.laz"):
        raise ValueError(
            f"a COPC file is conventionally named *.copc.laz so readers "
            f"can tell; got {dst.name}")
    exe = find_pdal(pdal)
    if exe is None:
        raise ValueError(
            "writing COPC needs pdal, which is not on PATH, in PDAL_EXE, "
            "or in a QGIS/OSGeo4W install. laspy reads COPC but cannot "
            "write it. Install pdal (conda-forge, or the QGIS bundle) or "
            "pass its path.")
    before = las_mod.cloud_info(src)

    command = [exe, "translate", str(src), str(dst),
               "--writers.copc.forward=all",
               # without this, extra dimensions are dropped in silence
               "--writers.copc.extra_dims=all"]
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ValueError(f"pdal failed to write {dst.name}: "
                         f"{detail[-500:] or 'no output'}")
    if not dst.is_file():
        raise ValueError(f"pdal reported success but {dst} does not exist")

    after = las_mod.cloud_info(dst)
    if not after["is_copc"]:
        raise ValueError(f"{dst.name} came back without a COPC VLR; the "
                         f"writer did not build an octree")
    if after["point_count"] != before["point_count"]:
        raise ValueError(
            f"{dst.name} holds {after['point_count']:,} points against "
            f"{before['point_count']:,} in the source")
    lost = set(before["extra_dims"]) - set(after["extra_dims"])
    if lost:
        raise ValueError(
            f"{dst.name} lost extra dimension(s) {sorted(lost)}; pdal "
            f"drops them silently without --writers.copc.extra_dims")
    return {
        "pdal": exe,
        "reordered": True,      # always: the octree decides the order
        "point_count": after["point_count"],
        "extra_dims": after["extra_dims"],
        "size_ratio": dst.stat().st_size / max(src.stat().st_size, 1),
        "crs": after["crs"].name if after["crs"] else None,
    }
