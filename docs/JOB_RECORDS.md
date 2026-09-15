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

This first integration covers colorization only. QA, alignment, classification,
and surface jobs still need adapters; exact build identity and source mutation
detection are follow-up work. Completed means execution finished, not that
survey accuracy or calibration authority has been independently established.
