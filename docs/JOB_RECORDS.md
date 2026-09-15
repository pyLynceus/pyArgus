# Job records (schema 1)

Colorization through the shared CLI/GUI job writes a unique
`output.las.job-<run-id>.json` beside the requested output. The log prints
its location. Each attempt retains its own record; reruns do not erase history.

Records contain operation, settings, pyArgus/Python versions, UTC start/end,
elapsed seconds, source paths, calibration parameters and hashes, matched image
metadata, result counts, and output metadata after a successful write.
States are running, completed, cancelled, or failed. An interrupted process
may leave running; that state is not proof that a process is still alive.

EO/calibration use SHA-256. LAS/images use size and modification time to avoid
an extra full read of large datasets; this is not immutable content identity.
The package version is not an exact Git/build identity. CRS and units are not
certified by these records. Inputs should remain unchanged during processing.

JSON replacement is atomic, but the cloud and JSON are not one transaction.
A write failure can leave an output or partial output. Failed/running records
must not be taken as accepted deliverables. If final record persistence fails,
the job raises even when its cloud has been written. Cancellation before the
cloud write leaves only the record (and any pre-existing output untouched).

The shared front-end integrations cover colorization, single-cloud QA and
alignment (CLI and GUI), and project QA/alignment (including automatic
disk-backed QA). Classification and surface jobs still need adapters; exact build identity and source mutation
detection are follow-up work. Completed means execution finished, not that
survey accuracy or calibration authority has been independently established.


## QA and alignment records

For report folders, the record sits beside the folder as
`folder.job-<run-id>.json`. Corrected LAS outputs use the same naming rule as
colorization. Solve-only alignment stores records under
`pyargus-job-records/` in the process working directory, never beside an input
on a source drive. The log prints the full path. That working directory must
be writable. Each attempt is independent, including refused and cancelled runs.
Validation done by GUI preparation or argument parsing before a job starts
does not create a record.

QA records carry the returned density, overlap and available control summaries.
Project records also retain the project configuration, trajectory time modes,
bindings and control values passed to the API. File-based single-cloud control
inputs get SHA-256 hashes. Project API control arrays have no source filename;
their actual values are retained instead. LAS and trajectory identities use
size/time metadata. Numerical defaults are recorded alongside explicit settings;
explicit arguments take precedence over the listed defaults. Missing/nonfinite
metrics become JSON null, never a zero residual.

Alignment records distinguish solved corrections from written corrections.
Single-cloud records include boresight in radians, offsets by strip, drift
nodes when used, solver residuals, and counts left unchanged outside the track.
CLI overlap comparisons use unquantized solved ground coordinates; the GUI
records solver metrics only. These are not exported-cloud acceptance checks.
Project alignment includes the before/after QA from actual exported coordinates,
the source-to-output mapping, and output identities. Project report folders now
also include a machine-readable summary.json.

Control used to constrain a solve is not an independent checkpoint test.
None of these completion states changes that distinction or grants an accuracy
acceptance. Direct low-level calls to report.generate, solve_alignment or
large_qa.qa are numerical/report primitives and do not start job records;
use the project or CLI/GUI entry points for tracked runs.
