"""The pyLynceus launcher's handover, read and translated.

The launcher (pyLynceus's Projects window) writes ``cache/<log>.handover.json``
into the job folder, immediately before a launch, and passes its path as
``--handover`` (and in ``PYLYNCEUS_HANDOVER``). The file's format is
``pylynceus-handover``; the CONSUMER translates it into its own concepts --
the launcher does not tailor the file per app.

Version 2 is what this suite's launcher writes: the shape that changed
with pyLynceus's job file (``job_plj`` became ``job_file``; no
``inputs.eo``). A version 1 file -- Plumbline 0.2.0's envelope -- is
refused BY ITS VERSION, not by a missing key.

What pyArgus takes from it:

* ``inputs.clouds[]`` -- the job's point clouds, LAS/LAZ the job lists on
  a datum. These open as project inputs -- the seam's acceptance. A
  listed cloud that is not on disk is a note; the other clouds still load.
* ``project_dir`` -- the job folder. The window's pickers start there and
  the job's own words (number, title, units, datum) come from ``context``.
* ``inputs.control`` / ``inputs.adjustment`` -- offered as project layers
  only when they are on disk; the control file's column order is the
  operator's to choose (never guessed), so control is noted, not loaded.

Nothing here imports the launcher's code: the envelope is the contract,
and it is read as data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = "pylynceus-handover"
VERSION = 2

# The formats the launcher's write_handover can have written before this
# reader. Named so a refusal can say "version 1" rather than "a key".
_KNOWN_OLDER = (1,)


class HandoverRefused(ValueError):
    """The handover cannot be read; the message says which one and why."""


@dataclass
class Handover:
    """One launcher handover, translated.

    ``path`` is the envelope itself (None when the window was opened on a
    bare ``--project`` with no handover); the rest is what pyArgus takes
    from it. ``notes`` says what could not be taken, in the handover's
    own terms -- never a guess.
    """

    path: Path | None = None
    app: str = ""
    project_dir: Path | None = None
    job_file: Path | None = None
    run_mode: str = ""
    clouds: list[Path] = field(default_factory=list)
    control: Path | None = None
    adjustment: Path | None = None
    units: str = ""
    job_id: str = ""
    title: str = ""
    datum: str = ""
    outputs: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _there(value: str, project_dir: Path) -> Path:
    """A handed-over path as a path: absolute as given; a relative one is
    the job folder's (the launcher resolves them before writing; this is
    the contract's fallback, re-resolved against ``project_dir``)."""
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = project_dir / candidate
    return candidate


def _offered(value, project_dir: Path, notes: list[str], what: str) -> Path | None:
    """An optional handed-over file, or a note saying why not."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = _there(value, project_dir)
    if not candidate.is_file():
        notes.append(f"the handover offers the {what} {candidate}, which is not on disk")
        return None
    return candidate


def read_handover(path) -> Handover:
    """The handover at ``path``, translated. Raises :class:`HandoverRefused`
    saying which file and why, by name."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HandoverRefused(f"the handover {path} cannot be read ({exc})") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise HandoverRefused(f"the handover {path} is not JSON ({exc})") from None
    if not isinstance(data, dict):
        raise HandoverRefused(f"the handover {path} is not an object")

    fmt = data.get("format")
    if fmt != FORMAT:
        raise HandoverRefused(
            f"{path} is not a pyLynceus handover (format {fmt!r}, not {FORMAT!r})")
    version = data.get("version")
    if version != VERSION:
        if version in _KNOWN_OLDER:
            raise HandoverRefused(
                f"the handover {path} is a version-{version} envelope (Plumbline "
                f"0.2.0's), which this reader does not translate; version {VERSION} "
                f"is what this suite's launcher writes")
        raise HandoverRefused(
            f"the handover {path} names version {version!r}; this reader knows "
            f"version {VERSION}")

    raw_project = data.get("project_dir")
    if not isinstance(raw_project, str) or not raw_project.strip():
        raise HandoverRefused(f"the handover {path} names no project_dir")
    project_dir = Path(raw_project)
    if not project_dir.is_dir():
        raise HandoverRefused(
            f"the handover {path} names the job folder {project_dir}, which is "
            f"not there")

    inputs = data.get("inputs")
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        raise HandoverRefused(f"the handover {path}: inputs is not an object")

    notes: list[str] = []
    clouds: list[Path] = []
    listed = inputs.get("clouds") or []
    if not isinstance(listed, list):
        notes.append("the handover's inputs.clouds is not a list")
        listed = []
    for item in listed:
        if not isinstance(item, str) or not item.strip():
            notes.append(f"the handover lists a cloud that is not a path: {item!r}")
            continue
        candidate = _there(item, project_dir)
        if candidate.suffix.lower() not in (".las", ".laz"):
            notes.append(f"the handover lists {candidate}, which is not a LAS/LAZ cloud")
            continue
        if candidate.is_file():
            clouds.append(candidate)
        else:
            notes.append(f"the handover lists the cloud {candidate}, which is not on disk")

    context = data.get("context")
    if not isinstance(context, dict):
        context = {}

    return Handover(
        path=path,
        app=str(data.get("app") or ""),
        project_dir=project_dir,
        job_file=(_there(data["job_file"], project_dir)
                  if isinstance(data.get("job_file"), str) else None),
        run_mode=str(data.get("run_mode") or ""),
        clouds=clouds,
        control=_offered(inputs.get("control"), project_dir, notes, "control file"),
        adjustment=_offered(inputs.get("adjustment"), project_dir, notes, "adjustment"),
        units=str(context.get("units") or ""),
        job_id=str(context.get("job_id") or ""),
        title=str(context.get("title") or ""),
        datum=str(context.get("datum") or ""),
        outputs=data.get("outputs") if isinstance(data.get("outputs"), dict) else {},
        notes=notes,
        raw=data,
    )


def resolve(handover=None, project=None, environ=None) -> Handover | None:
    """The launch context for this window: ``--handover`` / ``--project``,
    with the launcher's environment (``PYLYNCEUS_HANDOVER`` /
    ``PYLYNCEUS_PROJECT``) as the fallback. Both absent: None -- a plain
    window. A handover wins; a ``project`` naming a different job than the
    handover is refused, not reconciled."""
    environ = os.environ if environ is None else environ
    handover_path = (handover or environ.get("PYLYNCEUS_HANDOVER") or "").strip()
    project_dir = (project or environ.get("PYLYNCEUS_PROJECT") or "").strip()
    if handover_path:
        read = read_handover(handover_path)
        if project_dir:
            same = (os.path.normcase(str(read.project_dir.resolve()))
                    == os.path.normcase(str(Path(project_dir).resolve())))
            if not same:
                raise HandoverRefused(
                    f"{Path(handover_path)} names the job {read.project_dir}, not "
                    f"--project's {project_dir}")
        return read
    if project_dir:
        folder = Path(project_dir)
        if not folder.is_dir():
            raise HandoverRefused(f"the job folder {folder} is not there")
        return Handover(
            path=None, app="pyargus", project_dir=folder,
            notes=["no handover given -- add files to begin"],
        )
    return None
