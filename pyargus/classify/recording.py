"""Transactional publication and provenance for ground classification."""
from functools import wraps
from inspect import signature
import os
from pathlib import Path
import tempfile

from pyargus.analysis_records import analysis_job, finish
from pyargus.job_manifest import identity


def recorded_classification(function):
    """Keep failed writes away from the requested final path.

    ``force=True`` lets an existing output be replaced -- only once the
    new cloud has been written in full and verified, and in one atomic
    step, so a failed or cancelled run still leaves the old file as it
    was. The record says so (``replaced_existing``). The desktop stage
    and batch never pass it; ``classify-ground --force`` does.
    """
    @wraps(function)
    def run(path, out, *, force=False, **kwargs):
        source, target = Path(path).resolve(), Path(out).resolve()
        if source == target:
            raise ValueError("refusing to overwrite the input cloud")
        replacing = target.exists()
        if replacing and not force:
            raise FileExistsError(f"Output already exists: {target}")
        bound = signature(function).bind(path, out, **kwargs)
        bound.apply_defaults()
        settings = {k: v for k, v in bound.arguments.items()
                    if k not in {'path', 'out', 'log', 'progress', 'should_stop', 'keep_points'}}
        log = kwargs.get('log', print)
        with analysis_job(function.__name__.replace('_', '-'), target, settings,
                          inputs=[source], log=log) as record:
            record.data["replaced_existing"] = replacing
            before = identity(source)
            with tempfile.TemporaryDirectory(prefix='.pyargus-classify-', dir=target.parent) as temp:
                staged = Path(temp) / target.name
                result = function(source, staged, **kwargs)
                metrics = {k: v for k, v in result.items() if k != 'points'}
                stop = kwargs.get('should_stop')
                if result.get('cancelled') or (stop is not None and stop()):
                    finish(record, metrics, status='cancelled')
                    return {'cancelled': True}
                if identity(source) != before:
                    raise ValueError('Input changed during classification; output not published')
                import laspy
                # Read every point to catch incomplete/truncated writes before publication.
                with laspy.open(staged) as cloud:
                    expected = cloud.header.point_count
                    count = sum(len(chunk) for chunk in cloud.chunk_iterator(500_000))
                if count != expected or count != result['total']:
                    raise ValueError('Classified output point count failed validation')
                if stop is not None and stop():
                    finish(record, metrics, status='cancelled')
                    return {'cancelled': True}
                # Windows rename refuses an existing target; POSIX link is exclusive.
                # Replacing was asked for by name: os.replace is atomic on one
                # volume, and the staged file sits in the target's own folder.
                if replacing:
                    os.replace(staged, target)
                elif os.name == 'nt':
                    os.rename(staged, target)
                else:
                    os.link(staged, target)
                    staged.unlink()
                finish(record, metrics, outputs=[target])
                log(f'Published classified cloud: {target}')
                return result
    return run
