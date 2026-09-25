"""Points an operator measured, and everything needed to doubt them.

A stereo measurement is a survey observation, and a survey observation
that arrives as three numbers is not worth much. What makes it usable
later is knowing where it came from: which frames, which pixels, how
far apart those frames saw it, how well the rays agreed, and how much
height one pixel of pointing was worth at that spot. All of that is
cheap to record at the moment of measurement and impossible to
reconstruct afterwards.

So a measurement is written twice, on purpose.

The CSV is deliberately the SAME shape the control reader already
takes -- id, northing, easting, elevation, description -- because the
other thing these points must do is join a surface, and the surveyors'
field shots arrive in that shape too. One ingest, two sources. The
column order is stated and never guessed, which is the rule the
control reader already enforces and for the same reason: a file that
is read northing-first when it was written easting-first produces a
site that looks plausible and is transposed.

The JSON sidecar beside it holds what the CSV has no room for: the
image observations, the geometry, and the refusals that were in force.
A point whose rays met 4 degrees apart and a point whose rays met 27
degrees apart look identical in a CSV and are not the same measurement
at all.

Nothing here decides whether a point is good enough. That is the
caller's, because the threshold belongs to the job and not to the
format -- but the numbers needed to decide are all present, and a
measurement written without them is refused.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CSV_HEADER = "id,northing,easting,elevation,description"
SCHEMA = 1


@dataclass(frozen=True)
class Observation:
    """One image's view of a point: which frame, and where in it."""
    frame: str
    col: float
    row: float
    score: float = float("nan")

    def __post_init__(self):
        if not str(self.frame).strip():
            raise ValueError("an observation must name the frame it is in")


@dataclass
class Measurement:
    """One measured ground point, with the evidence for it."""
    point_id: str
    easting: float
    northing: float
    elevation: float
    observations: list
    max_angle_deg: float
    residual: float
    height_per_pixel: float = float("nan")
    disparity: float = float("nan")
    method: str = "stereo"
    description: str = ""
    refused_below_deg: float = float("nan")

    def __post_init__(self):
        if len(self.observations) < 2:
            raise ValueError(
                f"point {self.point_id} carries {len(self.observations)} "
                f"observation(s); a measured coordinate needs at least two, "
                f"and a record that cannot say where it came from is not a "
                f"measurement")
        for o in self.observations:
            if not isinstance(o, Observation):
                raise TypeError(f"observations must be Observation, got "
                                f"{type(o).__name__}")
        if not (self.max_angle_deg > 0):
            raise ValueError(
                f"point {self.point_id} has no ray geometry recorded; "
                f"without it nobody downstream can tell a strong "
                f"measurement from a guess")

    @property
    def strength(self):
        """A one-word reading of the geometry, for an operator."""
        if self.max_angle_deg < 8:
            return "weak"
        if self.max_angle_deg < 15:
            return "marginal"
        return "good"


def write(path, measurements, *, order="pnez", log=print):
    """Write the CSV and its sidecar. Returns both paths.

    ``order`` names the CSV column order, as the control reader spells
    it, and is written into the sidecar so a later read cannot be wrong
    about it.
    """
    path = Path(path)
    measurements = list(measurements)
    if not measurements:
        raise ValueError("nothing to write; refusing to create an empty "
                         "measurement file that would read as a finished "
                         "survey of nothing")
    if order not in ("pnez", "penz"):
        raise ValueError(f"order must be pnez or penz, got {order!r}")
    seen = {}
    for m in measurements:
        if m.point_id in seen:
            raise ValueError(f"point id {m.point_id!r} appears twice; ids "
                             f"are what ties a point to its evidence")
        seen[m.point_id] = m

    lines = [CSV_HEADER if order == "pnez"
             else "id,easting,northing,elevation,description"]
    for m in measurements:
        a, b = ((m.northing, m.easting) if order == "pnez"
                else (m.easting, m.northing))
        lines.append(f"{m.point_id},{a:.4f},{b:.4f},{m.elevation:.4f},"
                     f"{m.description}")
    temp = path.with_name(path.name + ".partial")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(path)

    sidecar = path.with_name(path.name + ".measurements.json")
    body = {"schema": SCHEMA, "order": order, "count": len(measurements),
            "points": [asdict(m) for m in measurements]}
    sidecar.write_text(json.dumps(body, indent=1), encoding="utf-8")
    log(f"measured: {len(measurements)} points -> {path}")
    log(f"evidence: {sidecar}")
    return path, sidecar


def read(path):
    """Read back the sidecar, which is the whole record.

    The CSV alone is readable by the control reader; this returns the
    measurements with their evidence attached.
    """
    path = Path(path)
    sidecar = (path if path.name.endswith(".measurements.json")
               else path.with_name(path.name + ".measurements.json"))
    if not sidecar.is_file():
        raise ValueError(
            f"{path.name} has no evidence sidecar beside it. The CSV can be "
            f"read as plain control, but the geometry that says whether "
            f"these points are trustworthy is in {sidecar.name}, and it is "
            f"not there.")
    body = json.loads(sidecar.read_text(encoding="utf-8"))
    if body.get("schema") != SCHEMA:
        raise ValueError(f"{sidecar.name} is schema {body.get('schema')!r}, "
                         f"this reader knows {SCHEMA}")
    out = []
    for row in body["points"]:
        row = dict(row)
        row["observations"] = [Observation(**o) for o in row["observations"]]
        out.append(Measurement(**row))
    return out, body["order"]
