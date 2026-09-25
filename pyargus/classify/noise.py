"""Flag gross outliers by elevation window: class 7 below, 18 above.

A vendor's strip export can carry returns a thousand feet under the
ground and a few hundred above the canopy -- multipath, a bird, an
out-of-range echo. They are few (a hundred-odd in tens of millions of
returns on the delivery that proved this necessary), which is why
they are dangerous: nothing else in the cloud looks like them, and
SMRF's minimum surface takes each one as the ground of its cell. See
``classify.job.NOISE_CLASSES`` for what the surface then does with a
flagged point.

Why a WINDOW the operator declares, rather than a detector that guesses:
these outliers sit outside the elevations the site holds, so a bound
read off the site is exact, cheap, recorded, and refuses by name when
it would flag more than a declared fraction of the cloud (a window that
catches 1% of a cloud is catching the site, not its noise). How far
outside is a property of the job, not a law -- on the motivating
delivery the nearest one caught sat only tens of feet below the site's
own minimum -- so the margin is the operator's to choose and the
sidecar records what the choice caught. In-band strays need a
neighbourhood test; that is a separate tool, not a looser window.

Nothing but the classification of the flagged points changes: every
other point field, the point format, extra dimensions, scales, offsets,
and the CRS records pass through ``formats.las.stream_update``
untouched. The one exception is a COPC index, which no chunked copy can
carry: a COPC input yields a plain LAS/LAZ (re-run ``pyargus copc`` if
the octree is wanted). The write is atomic. A sidecar
``<out>.noise.json`` lists every flagged point (index, x, y, z,
previous class) so the decision can be audited against the source
without re-reading it, and a schema-1 job record sits beside the output
-- including when the run refuses, which is recorded as a failed
attempt.
"""

import json
import math
from pathlib import Path

import numpy as np

from pyargus.analysis_records import analysis_job, finish
from pyargus.formats import las as las_mod
from pyargus.job_manifest import identity

LOW_NOISE, HIGH_NOISE = 7, 18
DEFAULT_MAX_FRACTION = 0.001


def _check_bounds(path, z_min, z_max, max_fraction, out, force=False):
    """Everything that can be refused before a file or record exists."""
    if z_min is None and z_max is None:
        raise ValueError("at least one bound is needed: --z-min and/or "
                         "--z-max (map units)")
    for name, value in (("z-min", z_min), ("z-max", z_max)):
        if value is not None and not math.isfinite(value):
            raise ValueError(f"--{name} must be a finite elevation, "
                             f"got {value}")
    if z_min is not None and z_max is not None and z_min >= z_max:
        raise ValueError(f"--z-min {z_min:.15g} must be below --z-max "
                         f"{z_max:.15g}")
    if not 0.0 < max_fraction <= 1.0:
        raise ValueError(f"--max-fraction must be in (0, 1], got "
                         f"{max_fraction}")
    if Path(out).resolve() == Path(path).resolve():
        raise ValueError("refusing to overwrite the input cloud; the "
                         "output must be a new file")
    # The CLI guarded this and the function did not, so the desktop app
    # and any script calling noise_cut directly replaced a finished
    # cloud without a word -- and its provenance sidecar then described
    # a different run. Every sibling writer in this suite refuses.
    if Path(out).exists() and not force:
        raise FileExistsError(f"Output already exists: {out}; pass force to "
                              f"replace it")


def noise_cut(path, out, *, z_min=None, z_max=None,
              max_fraction=DEFAULT_MAX_FRACTION, force=False,
              chunk_size=las_mod.DEFAULT_CHUNK, log=print):
    """Copy ``path`` to ``out`` with points below ``z_min`` set to class
    7 and points above ``z_max`` to class 18. Returns the counts.

    Two streaming passes: the first counts and lists what the window
    would flag and REFUSES before any cloud is written if that exceeds
    ``max_fraction`` of the cloud; the second writes. A point already
    carrying a noise class keeps it, inside the window or out.

    The refusals come in cost order. The window is checked against the
    header's own z range before a single point is read, because the
    case the fraction refusal exists for -- a bound from the wrong job,
    or metres typed for a cloud in feet -- is exactly the case where
    every point in the file is a candidate, and a refusal that first
    walks every chunk of a large cloud accumulating them is no refusal
    at all.
    """
    path, out = Path(path), Path(out)
    # This one cannot move inside the job record: the record hashes its
    # inputs, so a missing cloud has nothing to open a record about.
    if not path.is_file():
        raise ValueError(f"{path} does not exist")
    fields = ("x", "y", "z", "classification")
    settings = dict(z_min=z_min, z_max=z_max, max_fraction=max_fraction)

    # The job record opens FIRST. Every refusal below used to raise
    # before it existed, so nine of the thirteen left no trace at all
    # while the docstring promised that a refusal is recorded as a
    # failed attempt -- and the one the docstring cites as the reason
    # the check exists, metres typed for a cloud in feet, was one of the
    # nine. Opening the record costs nothing and reads no points, so it
    # does not disturb the cost order the refusals are arranged in.
    with analysis_job("noise-cut", out, settings, inputs=[path],
                      log=log) as record:
        _check_bounds(path, z_min, z_max, max_fraction, out, force)
        info = las_mod.cloud_info(path)
        expected = info["point_count"]
        z_lo, z_hi = info["mins"][2], info["maxs"][2]
        if expected == 0:
            raise ValueError(f"{path} holds no points")
        refuse_outside_header(z_min, z_max, z_lo, z_hi)
        budget = int(max_fraction * expected)
        before = identity(path)
        # --- pass 1: what would change, before any cloud is written ---
        parts, total, already, caught = [], 0, 0, 0
        for chunk in las_mod.iter_points(path, fields=fields,
                                         chunk_size=chunk_size):
            z = np.asarray(chunk["z"], dtype=float)
            codes = np.asarray(chunk["classification"])
            noise = (codes == LOW_NOISE) | (codes == HIGH_NOISE)
            low = (z < z_min) & ~noise if z_min is not None \
                else np.zeros(z.shape, dtype=bool)
            high = (z > z_max) & ~noise if z_max is not None \
                else np.zeros(z.shape, dtype=bool)
            for mask, code in ((low, LOW_NOISE), (high, HIGH_NOISE)):
                hit = np.flatnonzero(mask)
                if hit.size:
                    parts.append((hit + total, np.asarray(chunk["x"])[hit],
                                  np.asarray(chunk["y"])[hit], z[hit],
                                  codes[hit], code))
                    caught += hit.size
            already += int(noise.sum())
            total += z.size
            if caught > budget:
                # the running count is enough to refuse: do it here
                # rather than after accumulating the whole cloud
                raise ValueError(too_many(caught, total, expected,
                                          max_fraction, record=record.path))
        if total != expected:
            raise ValueError(miscounted(path, total, expected))
        fraction = caught / total
        if caught > budget:
            raise ValueError(too_many(caught, total, expected, max_fraction,
                                      record=record.path))

        index = np.concatenate([p[0] for p in parts]) if parts \
            else np.empty(0, dtype=np.int64)
        code = np.concatenate([np.full(p[0].size, p[5], dtype=np.uint8)
                               for p in parts]) if parts \
            else np.empty(0, dtype=np.uint8)
        order = np.argsort(index, kind="stable")
        index, code = index[order].astype(np.int64), code[order]
        n_low = int(np.count_nonzero(code == LOW_NOISE))
        n_high = int(code.size - n_low)
        log("window:  " + (f"z < {z_min:.15g}" if z_min is not None
                           else "no lower bound"))
        log("         " + (f"z > {z_max:.15g}" if z_max is not None
                           else "no upper bound"))
        log(f"flags:   {n_low:,} low (class {LOW_NOISE}), {n_high:,} high "
            f"(class {HIGH_NOISE}) of {total:,} points "
            f"({100 * fraction:.4f}%); {already:,} already flagged, untouched")

        # --- pass 2: the copy, classification only -------------------
        if identity(path) != before:
            raise ValueError(f"{path} changed while it was being read; the "
                             f"flags were chosen against the file as it was, "
                             f"so nothing was written.")

        def update(points, start):
            n = np.asarray(points["z"]).size
            lo = np.searchsorted(index, start)
            hi = np.searchsorted(index, start + n)
            if lo == hi:
                return None
            codes = np.array(points["classification"], dtype=np.uint8,
                             copy=True)
            codes[index[lo:hi] - start] = code[lo:hi]
            return {"classification": codes}

        written = las_mod.stream_update(path, out, update, fields=fields,
                                        chunk_size=chunk_size)
        if written != total:
            out.unlink(missing_ok=True)
            raise ValueError(f"wrote {written:,} points for {total:,} read; "
                             f"the output was removed")

        sidecar = out.with_name(out.name + ".noise.json")
        results = {"points": total, "flagged_low": n_low,
                   "flagged_high": n_high, "already_flagged": already,
                   "fraction": fraction}
        flagged = [{"index": int(i), "x": float(px), "y": float(py),
                    "z": float(pz), "previous_class": int(pc),
                    "class": int(c)}
                   for p in parts
                   for i, px, py, pz, pc, c in zip(p[0], p[1], p[2], p[3],
                                                   p[4], [p[5]] * p[0].size)]
        flagged.sort(key=lambda f: f["index"])
        sidecar.write_text(json.dumps({
            "source": str(path.resolve()), "output": str(out.resolve()),
            "z_min": z_min, "z_max": z_max, "max_fraction": max_fraction,
            "low_class": LOW_NOISE, "high_class": HIGH_NOISE,
            **results, "flagged": flagged}, indent=1, allow_nan=False),
            encoding="utf-8")
        log(f"sidecar: {sidecar}")
        log(f"wrote:   {out}")
        finish(record, results, outputs=[out, sidecar])
        return results


def refuse_outside_header(z_min, z_max, z_lo, z_hi, *, low="--z-min",
                          high="--z-max"):
    """Refuse, from the header's own z range, a window that would flag
    every point in the cloud.

    Shared by ``noise-cut`` and by screening during classification
    (``classify.job``), which name their bounds differently -- hence
    ``low``/``high``. It reads no points: the case it exists for, a
    bound from the wrong job or metres typed for a cloud in feet, is
    exactly the case where a running count would have to walk the
    whole file to say so.
    """
    if z_min is not None and z_min > z_hi:
        raise ValueError(
            f"{low} {z_min:.15g} is above every point in the cloud (the "
            f"header reads {z_lo:.15g} .. {z_hi:.15g}): that would flag "
            f"the whole delivery as low noise. Check the bounds and the "
            f"units.")
    if z_max is not None and z_max < z_lo:
        raise ValueError(
            f"{high} {z_max:.15g} is below every point in the cloud (the "
            f"header reads {z_lo:.15g} .. {z_hi:.15g}): that would flag "
            f"the whole delivery as high noise. Check the bounds and the "
            f"units.")


def miscounted(path, seen, expected):
    """The refusal when a cloud holds a different number of point
    records from the one its header claims -- shared with screening
    during classification, whose budget is a share of that count."""
    return (f"{path} holds {seen:,} point records but its header claims "
            f"{expected:,}: the file is truncated or its header is "
            f"stale, and a copy of it would silently drop or invent "
            f"points. No cloud written.")


def too_many(caught, seen, expected, max_fraction, *, option="--max-fraction",
             record=None, nothing="No cloud and no sidecar written"):
    """The refusal when a window flags more than ``max_fraction`` of the
    cloud -- one wording for both routes, naming the option that raises
    the limit on purpose."""
    recorded = (f"; the refusal is recorded in {record.name}"
                if record is not None else "")
    return (f"the window has already flagged {caught:,} points of the "
            f"{seen:,} read ({expected:,} in the cloud), above the declared "
            f"max fraction of {100 * max_fraction:.3f}%: that is not gross "
            f"noise, it is the site. {nothing}{recorded}. Check the bounds "
            f"against the cloud's elevation range (pyargus info), or raise "
            f"{option} on purpose.")
