"""Read-only QA review models; never interpret a saved job as instructions."""
import json
import math
from pathlib import Path


def load_review(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Select a schema-1 pyArgus .job-*.json record.")
    if data.get("operation") not in {"qa", "align", "project-qa", "project-align", "classify-ground-whole", "classify-ground-tiled"}:
        raise ValueError("This record is not a supported QA, alignment or ground-classification job.")
    if not isinstance(data.get("results"), dict):
        raise ValueError("Job record has no results object.")
    data["record_path"] = str(path)
    if data["operation"] == "project-qa" and "inventory" not in data["results"]:
        report = data["results"].get("report")
        if report:
            inventory = Path(report).parent/"inventory.json"
            try:
                data["results"]["inventory"] = json.loads(inventory.read_text(encoding="utf-8"))
                data["inventory_note"] = "Trajectory counts loaded from the associated report inventory."
            except (OSError, ValueError):
                data["inventory_note"] = "Associated trajectory inventory is unavailable."
    return data


def review_rows(record, limit=0.25):
    """Display threshold is an investigation aid, never acceptance certification."""
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError("Review threshold must be positive and finite (map units).")
    result = record["results"]
    rows = []
    def row(label, before=None, after=None, note="", flag=False):
        rows.append(dict(label=label, before=before, after=after, note=note, flag=flag))
    def high(value):
        return isinstance(value, (int, float)) and (not math.isfinite(value) or abs(value)>limit)
    row("Job status", after=record.get("status"), note="Execution status, not accuracy acceptance",
        flag=record.get("status") != "completed")
    if record.get("operation", "").startswith("classify-ground-"):
        row("Total points", after=result.get("total"))
        row("Ground points", after=result.get("ground"))
        row("Ground fraction", after=result.get("ground_fraction"),
            note="Classification proportion, not accuracy; visual and independent QA still required")
    if record.get("inventory_note"):
        row("Inventory source", note=record["inventory_note"], flag="unavailable" in record["inventory_note"])
    if record.get("error"):
        row("Failure", after=record["error"].get("message"), flag=True)
    before, after = result.get("before_qa", {}), result.get("after_qa", {})
    if not after and "density" in result:
        after = result
    for key in ("points", "ground_points", "units"):
        if key in before or key in after:
            row(key.replace("_", " ").title(), before.get(key), after.get(key))
    if "density" in after:
        row("Median density", before.get("density", {}).get("median"), after["density"].get("median"), "points per square map unit")
    if "patch_rms_before" in result:
        row("Solver patch RMS", result.get("patch_rms_before"), result.get("patch_rms_after"), "Solver metric; not independent accuracy", high(result.get("patch_rms_after")))
    pairs = {(str(p["a"]), str(p["b"])): [p, {}] for p in before.get("strip_dz", [])}
    for p in after.get("strip_dz", []):
        pairs.setdefault((str(p["a"]), str(p["b"])), [{}, {}])[1] = p
    for p in result.get("overlap_before_after", []):
        pairs[(str(p["a"]), str(p["b"]))] = [p["before"], p["after"]]
    for (a, b), (old, new) in sorted(pairs.items()):
        for key in ("median", "rmse", "p95_abs"):
            if key in old or key in new:
                row(f"Strip {a} / {b}: {key}", old.get(key), new.get(key),
                    "Map units; review threshold" if high(new.get(key)) else "Map units", high(new.get(key)))
    if not pairs:
        row("Overlap evidence", note="No pairwise QA comparisons in this record", flag=True)
    for label, summary in (("Before", before), ("After", after)):
        ctl = summary.get("control", {})
        for name, value in ctl.get("residuals", {}).items():
            row(f"{label} control {name}", after=value, note="Lidar minus control; independence not established", flag=high(value))
        for name, reason in ctl.get("skipped", {}).items():
            row(f"{label} control {name}", note=f"Skipped: {reason}", flag=True)
    inv = result.get("inventory", {})
    # Large-project QA may expose counts directly rather than a nested inventory.
    for name in ("unmatched", "ambiguous"):
        if name in inv or name in result:
            n = inv.get(name, result.get(name))
            row(f"Trajectory {name}", after=n, flag=bool(n))
    if "corrections_written" in result:
        row("Corrections written", after=result["corrections_written"])
    if "points_outside_trajectory_unchanged" in result:
        n = result["points_outside_trajectory_unchanged"]
        row("Outside trajectory, unchanged", after=n, flag=bool(n))
    return rows


def cloud_layers(record):
    """Keep full paths and dataset roles; repeated LAS line IDs stay per-file."""
    layers, seen = [], set()
    for role, items in (("Original", record.get("inputs", [])), ("Corrected", record.get("outputs", []))):
        for item in items:
            path = Path(item.get("path", ""))
            if path.suffix.lower() not in {".las", ".laz"} or str(path) in seen:
                continue
            seen.add(str(path))
            state = "available"
            try:
                stat = path.stat()
                if stat.st_size != item.get("size_bytes") or stat.st_mtime_ns != item.get("mtime_ns"):
                    state = "changed since job"
            except OSError:
                state = "missing"
            layers.append(dict(path=str(path), role=role, state=state))
    return layers
