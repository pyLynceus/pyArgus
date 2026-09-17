"""Job provenance adapters for QA and alignment; no numerical algorithms."""
from contextlib import contextmanager
from dataclasses import asdict
from inspect import signature
import math
from pathlib import Path

from pyargus.job_manifest import JobRecord, identity


def plain(value):
    """Convert array/scalar summaries to strict JSON; missing metrics are null."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, Path):
        return str(value.resolve())
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def defaults(function):
    return {k: p.default for k, p in signature(function).parameters.items()
            if p.default is not p.empty}


@contextmanager
def analysis_job(operation, output, settings, *, inputs=(), controls=(), log=print):
    # Solve-only jobs must not create files beside read-only source datasets.
    target = output or (Path.cwd() / "pyargus-job-records" / "alignment-solve")
    with JobRecord(operation, target, plain(settings)) as record:
        record.data["intended_output"] = str(Path(output).resolve()) if output else None
        record.data["metric_note"] = "Nonfinite or unavailable metrics are null; completion is not accuracy acceptance."
        log(f"job record: {record.path}")
        try:
            for path in inputs:
                if path:
                    record.data["inputs"].append(identity(path))
            for path in controls:
                record.data["inputs"].append(dict(identity(path, hash_content=True), role="control"))
            record.save()
            yield record
        except BaseException as error:
            from pyargus.project import Cancelled
            if isinstance(error, Cancelled):
                record._cancelled_exception = error
                record.finish("cancelled", record.data["results"])
                # Preserve cancellation for the GUI while saving the terminal state.
                record.data["cancellation"] = str(error)
            raise


def finish(record, results, *, outputs=(), status="completed"):
    record.data["outputs"] = [identity(p) for p in outputs]
    record.finish(status, plain(results))


def alignment_result(result, strip_ids):
    values = dict(boresight_radians=result.boresight,
                  offsets_by_strip={str(s): result.offsets[i] for i, s in enumerate(strip_ids)},
                  patch_rms_before=result.rms_before, patch_rms_after=result.rms_after,
                  observations=result.n_observations, iterations=result.iterations,
                  control_anchored=result.absolute, control_observations=result.n_control,
                  control_rms_before=result.control_rms_before, control_rms_after=result.control_rms_after,
                  assessment="Solver metrics are not independent checkpoint accuracy.")
    if result.drift is not None:
        values["drift_by_strip"] = {str(s): dict(times=result.drift.node_times[i],
                                                values=result.drift.values[i])
                                   for i, s in enumerate(strip_ids)}
    return plain(values)


def project_settings(project, control, **settings):
    return plain(dict(project=asdict(project), control_values=control, **settings))
