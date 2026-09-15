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


def identity(path, *, hash_content=False):
    path = Path(path).resolve()
    stat = path.stat()
    result = dict(path=str(path), size_bytes=stat.st_size,
                  mtime_ns=stat.st_mtime_ns, identity_method="size_and_mtime")
    if hash_content:
        result.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      identity_method="sha256_and_metadata")
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
        temporary = self.path.with_suffix(".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.save()
        return self

    def finish(self, status, results):
        if status not in {"completed", "cancelled"}:
            raise ValueError("invalid terminal job status")
        self.data.update(status=status, results=results)

    def __exit__(self, kind, error, traceback):
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
            error.add_note(f"Could not update job record {self.path}: {save_error}")
        return False
