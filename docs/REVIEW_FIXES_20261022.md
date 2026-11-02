# Review fixes: backend reliability, October 22, 2026

Current status: Windows source and real-data reference validation completed.
The combined backend and Claude GUI suite had 783 passes, one Linux-only X11
skip and no failures (221.58 seconds); pip check passed with no environment
warnings. The raw source runner retains needs_skip_review, with that one skip
explicitly outside Windows scope. All 73 of 73 reference checks passed across
nine modules, completing October 22 at 19:26 UTC (3:26 p.m. EDT).

Both phases used unchanged canonical source fingerprint
c8c88e8ad88971b59b969d9ce35832dd546a98eb7540b27baf119ee9146e6104.
A separate October 22 Windows executable now includes these validated changes;
frozen/relocated GPU/native/multicore checks and the full payload audit passed.
Actual installer lifecycle testing remains pending; existing installations are
unchanged. See WINDOWS_REVIEW_BUILD_20261022.md and
build/release-review-20261022/. No new production cloud adjustment or accuracy
acceptance is claimed. Claude owns the GUI implementation.

## Completed backend work

- Shared LAS/LAZ writers preserve exact ExtraBytes descriptor bytes for unchanged
  extra dimensions, including validity flags and vendor statistics. Whole-cloud,
  streamed, classification, alignment and colorization paths use the helper.
  RGB point-format conversion preserves descriptors too; an added independent
  fixture caught laspy rebuilding that metadata during conversion before the
  write, which is now covered for LAS and LAZ.
- Dense grids refuse more than 25,000,000 cells before allocating edges or
  rasters. Nonfinite/empty coordinates and invalid cell sizes refuse explicitly.
  Tiled classification checks the global raster estimate against its budget
  in both serial and parallel modes. Tiling still has global raster costs;
  these admission checks do not guarantee an operating-system RSS limit.
- QA (array and disk-backed), project alignment and ground classification retry
  temporary publication locks and retain complete verified output on persistent
  final publication failure. The error and job record identify the recovery path.
  Destination collisions preserve both the existing file and FileExistsError
  compatibility. New results cannot replace another writer's destination.
- Streaming LAS writes use unique partial names; a repeated attempt cannot
  overwrite an earlier retained recovery copy. LAZ compression is selected from
  the intended destination, despite the temporary filename's suffix.
- LP360 surface, contour and final-cloud delivery stages publish complete folders
  from staging. Cancellation before commit leaves no partial final folder.
  Stop after commit leaves that stage completed and stops the next stage.
  Delivery receipts refer to published paths, not temporary directories.
- JSON records and workspace saves use unique temporary files and bounded atomic
  replacement retries. A final replacement failure retains a complete recovery
  record. Cleanup locks are logged separately from publication outcomes.
- Small text identities include content SHA-256 by default, with an 8 MiB limit
  for automatic hashing. Cloud/binary-trajectory identities remain size/mtime.
  Classification rechecks its input after readback verification. Colorization
  checks cloud, EO, imagery and calibration identities after coordinate reading,
  before copying and immediately before publishing the written cloud.
- The validation runner records malformed installed distributions and returns
  needs_environment_review after otherwise successful checks. It no longer
  crashes while sorting a nameless distribution or silently hides that entry.
- The stale pyargus-0.1.0.dist-info (licenses only, no METADATA) was quarantined
  under the evidence folder; current editable 0.2.0 metadata was retained.
  Current inventory has no warnings; pip check reports no broken requirements.
- Package discovery is restricted to pyargus and pyargus.*. A generated
  pyargus-job-records directory cannot become an installed namespace package.
- The tracked Windows stager requires a new output directory, excludes private
  top-level handoff notes from application source, and runs a release-content
  audit before creating its manifest. The audit checks required runtime/source
  files, verified Geoid18, native build recipes and corresponding-source paths
  and checksums, and private/unsafe source-archive members.

## Verification and evidence

Evidence directory: build/review-fixes-20261021 (created October 21 and retained
across the October 22 continuation).

- focused-validation.json: command, interpreter, 153 test outcomes, timing,
  installed package inventory and before/after working-source identity.
- focused.xml / focused.log: JUnit and complete output; no failures or skips.
- run_focused.py: exact serial focused-test driver.
- environment-inventory.json / environment-inventory-repaired.json: stale entry
  before repair and clean inventory after repair.
- environment-quarantine/: recoverable stale metadata, not deleted.
- prior-payload-audit.json: October 19 payload refused for missing
  Sources/native-packages.json. Historical releases were not modified.
- before/: exact pre-edit file backups, including prior uncommitted work.
- implementation-files.json / backend-changes.patch: this backend work's file
  inventory and comparison to the saved pre-edit contents.

The 18 focused test modules cover LAS/LAZ metadata and RGB conversion, unchanged
point attributes, grid refusal before allocation, serial/parallel admission,
input changes between reads, publication locks/races, recovery paths, cancellation
boundaries, classification, project QA/alignment, LP360 staging and release gates.
They do not replace the full source suite or reference.run_all.

The local Geoid18 file was verified against SHA-256
fa9a407ac7ee3f5a3694008e4bcd09ce9cc250452f0c3b11700a4960340abce2.
No reference expectations, fitting weights or production LAS were changed.

## Validation coordination and remaining release gates

The Finish pyArgus review validation follow-up coordinated this run behind
pyLynceus processing. Its validation work is complete; automatic polling has
been removed. Automation ID: finish-pyargus-review-validation.
Do not rely on old process IDs: the current Example_Project job has changed since the
original wait decision. Check its command line and any replacement jobs.

For a future revalidation, run serially in this checkout's own environment
when the machine is free and the source is stable:

```powershell
$env:PDAL_EXE = (Resolve-Path '.venv/native-pdal/Library/bin/pdal.exe').Path
$env:PYTHONDONTWRITEBYTECODE = '1'
& ./.venv/Scripts/python.exe -X utf8 -m devtools.validate --reference
```

Retain the runner's actual full-suite/JUnit/reference logs and source identities.
Source changes invalidate a combined run. Backend fixes may proceed within scope;
leave GUI implementation to Claude and report any integration failures precisely.
Do not weaken recorded numerical reference checks to obtain a pass.

Still pending: an actual corrected installer payload, source-to-binary provenance,
native/runtime acceptance on that payload, relocation and install/uninstall tests,
and fresh Linux acceptance for these backend changes. The new content audit is
an admission gate, not proof of legal compliance or installed-runtime behavior.
Historical installers must not be represented as containing these fixes.

Classification's existing non-noise reset policy has not been changed. ExtraBytes
preservation does not imply preserving every pre-existing semantic class. Review
that policy explicitly before changing it. New weighting, drift/tilt corrections
and Example_Project scientific experiments remain separate work. No new cloud adjustment,
release installation, commit or push was performed for this increment.


## Combined source validation and reference run, October 22

The source suite ran via devtools.validate with the private PDAL executable
set explicitly. Evidence: reference/reports/validation-20261022T161651Z-20460/.
There were 784 collected tests, 783 passes, one platform skip and no failures.
The skip is tests.test_gpu_renderer::test_linux_context_preserves_tk_x11_error_handler,
with reason X11 handler ownership is Linux-specific. Preserve the runner's
needs_skip_review status; do not relabel it as a zero-skip pass.

An initial reference-file probe encountered WinError 121 on Z:. The connection
subsequently recovered; a bounded probe confirmed the reference LAS exists.
The source suite was run while checking connectivity, then the exact
reference.run_all battery was launched serially under the same canonical source
fingerprint. No source tests or numerical expectations were changed.

Reference evidence is build/review-validation-20261022/reference-validation.json
and reference.log; run_reference.py records the source before/after, unit-run
link, command, child PID and final check count. The driver holds both the shared
Git and checkout validation locks to prevent duplicate validation. It must not
be restarted while the recorded processes are alive. Completion is not claimed
until that record has a terminal result and all expected checks are evaluated.
The thread follow-up now monitors this run instead of launching another suite.


## Reference interruption detected October 22

The reference driver and child processes (31868, 33528, 54096, 32104) had all
ended without a terminal result or traceback. The log contains completion
runtimes for seven modules through summerville_streaming, but no numerical
metrics or final check verdict. Those runtimes are not cached acceptance results.
The cause is unknown; available event records do not establish a relevant
python.exe crash or resource-exhaustion event. Do not infer a numerical failure
or acceptance from this interrupted attempt.

The original running record is preserved as reference-validation.original-running.json;
reference-validation.json now records interrupted and the unchanged source hash.
Both stale locks were removed only after checking every recorded process had
ended and verifying their owner PID, operation and checkout. Lock evidence is
stale-lock-recovery.json. Another Example_Project plan_control_v5 processing run is
active. Retry only after heavy processing finishes, retaining durable results
per reference module so another interruption cannot erase completed measurements.


## Prepared resumable retry

The follow-up is queued behind pyLynceus and will use
build/review-validation-20261022/run_reference_resumable.py. This is a validation
driver under the ignored evidence folder, not a change to application algorithms.
It runs each of the nine reference module.main functions in a separate child,
writes durable metrics immediately, and evaluates all unchanged
reference.run_all.CHECKS only after every module is available. It does not count
the seven old timing lines as reusable measurements.

Reuse requires the same canonical application source, Python/package versions,
driver hash, dataset-identity manifest and metrics checksum. Large LAS, trajectories
and images use size/mtime identities; small text inputs include content hashes.
The full manifest is rechecked before caching new results and before the final
verdict. This does not detect deliberately preserved size/mtime changes in large
inputs. Geoid18 is separately checked by its published SHA-256.

Each fresh retry has an immutable attempt directory under resumable/; valid
module records are copied into a source/input-specific module-cache directory.
The current attempt is recorded in reference-retry.json. Both validation locks
remain held until the attempt exits. Source changes require a new source-suite
run; incomplete, changed or mismatched checkpoints cannot produce a pass.
The driver was syntax/CLI checked only; no new heavy reference run was started
while Example_Project plan_control_v5 was active.


## Retry infrastructure check, October 22

The first resumable attempt (resumable/20261022T174320Z-14056/) collected the
Summerville module metrics, then hit a Windows temporary-file path limit while
copying its record into a cache path containing two full hashes. This is a
validation-driver storage failure, not a numerical application failure. Its
logs and result remain in that attempt directory; the top-level record is
archived as reference-retry.path-length-failure.json.

Cache directory keys are now short, with the full source/input/driver hashes
still verified inside each record. Actual temporary-file creation succeeded
under the shortened path. Application source and expectations are unchanged.
Both locks were released by the failed driver. The current reference-retry.json
is awaiting_machine and carries no numerical verdict. Another Example_Project
paint_block.py orthophoto job and Witness tests are active, so the corrected
retry is queued. Check all pyLynceus processing commands, not just
run_flight_shifts.py, before launching it. No reference acceptance is claimed.


Corrected retry started at 18:42 UTC on October 22, after confirming stable
source, clear locks and no competing heavy jobs. Its attempt directory is
resumable/20261022T184244Z-11200. The driver and children are tracked in
reference-retry.json. The first complete module record was successfully saved
to the short cache path and verified; all expected modules/checks must still
finish before acceptance. Do not launch a duplicate or treat partial checkpoints
as a completed battery.


## Final verification: complete October 22

- Full combined source suite: 783 passed, one Linux-only skip, zero failures.
  Raw record remains needs_skip_review; the skipped X11 handler test requires
  Linux and is excluded only from this Windows validation scope.
- Reference battery: all 73 expected checks passed across all nine modules.
  Every check was recomputed against unchanged reference.run_all.CHECKS using
  the saved module measurements. No partial or earlier interrupted run was used.
- Source: unit before/after, every reference checkpoint, reference before/after
  and the final inspected tree share canonical fingerprint c8c88e8a...6e6104.
  All checkpoint metrics hashes, full driver hash and dataset-manifest hash
  were verified. The manifest contains 1,139 file identities, with the large-input
  metadata limitations described above.
- Evidence: build/review-validation-20261022/final-verification.json,
  combined-validation.json, reference-retry.json, the immutable attempt at
  resumable/20261022T184244Z-11200/, its inputs.json and per-module logs/results.
  Unit logs/JUnit remain in reference/reports/validation-20261022T161651Z-20460/.
- The corrected reference run took about 44 minutes; colorization accounted for
  about 35 minutes. Both validation locks were released after completion.

The automatic validation follow-up was removed because its work is done.
The earlier interrupted and path-length-failed attempts remain preserved as
history. No new installer, installation change, commit, push or production
accuracy acceptance was performed. A corrected release payload and its actual
installed/runtime acceptance remain separate pending work.


## October 22 Windows package

The corrected Windows payload includes all native recipes and eight verified
upstream source archives, plus all 253 canonical source files. It passed full
manifest and release-content checks, frozen GPU/native/multicore acceptance and
relocation with an isolated environment. The source fingerprint is unchanged.
See WINDOWS_REVIEW_BUILD_20261022.md for exact paths and the pending installer
lifecycle scope. Earlier no-build statements above describe the source-validation
checkpoint, before this separately authorized packaging step.
