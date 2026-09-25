"""Surveyed control CSVs.

Survey exports come as id, then two coordinates, then elevation, then
an optional description -- and whether the coordinates are N,E or E,N
depends on who exported them. Guessing the order silently is how a
checkpoint lands ~1,900 miles from the cloud (the Summerville CSVs are
northing-first), so the order is a required argument, never inferred.
"""

import csv

import numpy as np

ORDERS = ("pnez", "penz")


def read_control_csv(path, order):
    """Read one control CSV as (ids, easting, northing, elevation).

    ``order`` is "pnez" (id, northing, easting, elevation) or "penz"
    (id, easting, northing, elevation), stated by whoever knows the
    export. Blank lines are skipped; a malformed row raises with its
    line number.
    """
    if order not in ORDERS:
        raise ValueError(f"order must be one of {ORDERS}, got {order!r}")
    ids, e, n, z = [], [], [], []
    with open(path, newline="") as fh:
        for lineno, row in enumerate(csv.reader(fh), start=1):
            if not row or not row[0].strip():
                continue
            try:
                c1, c2, elev = float(row[1]), float(row[2]), float(row[3])
            except (IndexError, ValueError) as exc:
                # A header row is unambiguous: a data row always has
                # numbers in its coordinate columns, so a FIRST row that
                # does not is a header and nothing else. Only the first
                # one -- an unparseable row later in the file is damaged
                # and still refuses, because skipping it would drop a
                # control point without saying so. A real client GCP
                # file arrived with a header row, and before this it had
                # to be hand-stripped.
                if lineno == 1 and not ids:
                    continue
                raise ValueError(
                    f"{path}: line {lineno} is not id,coord,coord,elev[,desc]: "
                    f"{row!r}") from exc
            ids.append(row[0].strip())
            if order == "pnez":
                n.append(c1), e.append(c2)
            else:
                e.append(c1), n.append(c2)
            z.append(elev)
    if not ids:
        raise ValueError(f"{path}: no control rows")
    return ids, np.array(e), np.array(n), np.array(z)


def read_control_csvs(paths, order):
    """Concatenate several CSVs of the same column order."""
    ids, e, n, z = [], [], [], []
    for path in paths:
        i2, e2, n2, z2 = read_control_csv(path, order)
        ids.extend(i2)
        e.append(e2), n.append(n2), z.append(z2)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate control point ids across files")
    return ids, np.concatenate(e), np.concatenate(n), np.concatenate(z)
