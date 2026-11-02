"""Bounded publication retries and recoverable, unpublished staging outputs."""
from contextlib import contextmanager
from pathlib import Path
import ctypes
import errno
import json
import logging
import os
import shutil
import sys
import tempfile
import time

RETRY_DELAYS = (.05, .1, .2, .4, .8)


class PublicationError(OSError):
    """A complete staged result is retained; the requested target was not replaced."""
    def __init__(self, source, target, cause):
        self.recovery_path = Path(source).resolve()
        self.target_path = Path(target).resolve()
        super().__init__(
            f"Could not publish {self.target_path}: {cause}. "
            f"Staged output retained for recovery at {self.recovery_path}")


class DestinationExistsError(PublicationError, FileExistsError):
    """Retained output and the existing public FileExistsError contract."""


def _retry(operation, source, target):
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return operation()
        except OSError as exc:
            if isinstance(exc, FileExistsError):
                raise DestinationExistsError(source, target, exc) from exc
            transient = (isinstance(exc, PermissionError) or
                         exc.errno in (errno.EACCES, errno.EBUSY, errno.EPERM) or
                         getattr(exc, 'winerror', None) in (5, 32, 33))
            if not transient or attempt == len(RETRY_DELAYS):
                raise PublicationError(source, target, exc) from exc
            time.sleep(RETRY_DELAYS[attempt])


def replace_retry(source, target):
    """Replace a record/output whose caller has explicitly allowed replacement."""
    source, target = Path(source), Path(target)
    _retry(lambda: os.replace(source, target), source, target)


def _cleanup(operation, path):
    """Cleanup failure must not undo publication or hide a processing error."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            operation()
            return
        except OSError as exc:
            if attempt == len(RETRY_DELAYS):
                logging.getLogger(__name__).warning(
                    "Cleanup could not remove %s; retained on disk: %s", path, exc)
                return
            time.sleep(RETRY_DELAYS[attempt])


def _rename_new(source, target):
    # File hard links are exclusive on POSIX; Windows rename is exclusive too.
    if os.name == 'nt':
        os.rename(source, target)
    elif source.is_file():
        os.link(source, target)
        # Publication is complete. Cleanup of the old link is not publication.
        _cleanup(source.unlink, source)
    elif sys.platform.startswith('linux'):
        # renameat2(RENAME_NOREPLACE) refuses even a competing empty directory.
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise OSError(errno.ENOTSUP, 'Exclusive directory rename is unavailable')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(target))
    else:
        raise OSError(errno.ENOTSUP, 'Exclusive directory publication is unsupported')


def publish_new(source, target):
    """Publish a complete file/directory without overwriting an existing target."""
    source, target = Path(source), Path(target)
    _retry(lambda: _rename_new(source, target), source, target)


@contextmanager
def staging_directory(parent, *, prefix):
    """Remove failed/cancelled work, retaining complete publication failures."""
    stage = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    retain = False
    try:
        yield stage
    except PublicationError as exc:
        retain = exc.recovery_path.is_relative_to(stage.resolve())
        raise
    finally:
        if not retain and stage.exists():
            _cleanup(lambda: shutil.rmtree(stage), stage)


def atomic_write_json(path, value):
    """Replace a JSON record atomically; retain a complete record on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    retain = False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        replace_retry(temporary, path)
    except PublicationError:
        retain = True
        raise
    finally:
        if not retain:
            _cleanup(lambda: temporary.unlink(missing_ok=True), temporary)
