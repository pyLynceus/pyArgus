"""Persistent per-attempt job records. Large inputs use metadata, not hashes."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import time
import uuid

from pyargus import __version__
from pyargus.publication import atomic_write_json


SMALL_TEXT_LIMIT = 8 * 1024**2
SMALL_TEXT_SUFFIXES = frozenset({'.csv', '.tsv', '.txt', '.json', '.cal',
                                 '.yaml', '.yml', '.wkt', '.prj'})


def identity(path, *, hash_content=None):
    path = Path(path).resolve()
    stat = path.stat()
    result = dict(path=str(path), size_bytes=stat.st_size,
                  mtime_ns=stat.st_mtime_ns, identity_method="size_and_mtime")
    if hash_content is None:
        hash_content = (path.suffix.lower() in SMALL_TEXT_SUFFIXES and
                        stat.st_size <= SMALL_TEXT_LIMIT)
    if hash_content:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024**2), b''):
                digest.update(chunk)
        after = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError(f'Input changed while hashing: {path}')
        result.update(sha256=digest.hexdigest(), identity_method="sha256_and_metadata")
    return result


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class JobRecord:
    """One unique JSON per attempt; interrupted runs retain running status.

    Atomic JSON replacement prevents half-written records. This is not an
    atomic transaction with the output file. A failed run may leave output.
    """
    def __init__(self, operation, output, settings):
        self.started = time.monotonic()
        run_id = uuid.uuid4().hex
        output = Path(output).resolve()
        self.path = output.with_name(output.name + ".job-" + run_id + ".json")
        self.data = dict(schema_version=1, run_id=run_id, operation=operation,
                         status="running", started_utc=utc_now(), settings=settings,
                         software=dict(pyargus=__version__, python=platform.python_version()),
                         intended_output=str(output), inputs=[], results={})

    def save(self):
        atomic_write_json(self.path, self.data)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.save()
        return self

    def finish(self, status, results):
        if status not in {"completed", "cancelled"}:
            raise ValueError("invalid terminal job status")
        self.data.update(status=status, results=results)

    def __exit__(self, kind, error, traceback):
        if error is not None and hasattr(error, "recovery_path"):
            self.data["recovery_path"] = str(error.recovery_path)
        if error is not None and error is not getattr(self, "_cancelled_exception", None):
            self.data.update(status="failed", error=dict(type=kind.__name__, message=str(error)))
        elif self.data["status"] == "running":
            self.data.update(status="failed", error=dict(type="IncompleteJob", message="No terminal result recorded"))
        self.data.update(finished_utc=utc_now(), elapsed_seconds=time.monotonic()-self.started)
        try:
            self.save()
        except OSError as save_error:
            if error is None:
                raise
            message = f"Could not update job record {self.path}: {save_error}"
            if hasattr(error, 'add_note'):
                error.add_note(message)
            else:  # Python 3.10 supports the application, but not exception notes.
                import logging
                logging.getLogger(__name__).warning(message)
        return False
