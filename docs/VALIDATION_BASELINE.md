# Reproducible validation baseline

Use this checkout's Python and run heavy checks serially. The runner is a
source-validation tool, not a desktop builder or a production-accuracy claim.

## Record a validation

```powershell
& ./.venv/Scripts/python.exe -m devtools.validate
```

This runs `pip check` followed by pytest with `-ra` and JUnit XML. Each run
creates a unique ignored folder under `reference/reports/validation-*`:

- `validation.json`: exact Git commit and dirty status (or "git unavailable"
  when git is not on PATH), the source fingerprint before/after in the scheme
  review packets share (`devtools.fingerprint`, below), interpreter/platform,
  installed versions, commands, exit codes, all nonpassing test names and reasons;
- `pytest.xml`: machine-readable test cases;
- per-step logs, including the dependency check and complete pytest output.

The runner returns nonzero on failure, missing results, source changes or any
skipped tests. `needs_skip_review` is distinct from a test failure: review the
specific reason before deciding whether the defined release scope permits it.
Xfailed tests are also visible as nonpassing JUnit cases. There is no blanket
allow-skips switch and no automatic waiver.

The shared Git directory holds `pyargus-validation.lock` during a run. Sibling
worktrees using this runner cannot overlap heavy checks. Other agents running
pytest directly do not honor this lock, so coordinate known active jobs. A
stale lock may be removed only after checking its PID has ended. Do not delete
it merely to start a competing run. Without `git` on PATH the lock is created
in the checkout root instead and does not coordinate sibling worktrees.

## Real-data and executable checks

```powershell
& ./.venv/Scripts/python.exe -m devtools.validate --reference
& ./.venv/Scripts/python.exe -m devtools.validate --reference --exe ./dist/<build>/pyArgus/pyArgus.exe
```

The reference gate needs the read-only Z: datasets and required geoid/native
dependencies. It is run only when requested; a source-only pass is not a
reference pass. CLAUDE.md still requires the gate for relevant algorithm changes.
An executable option hashes and self-tests the supplied binary. Hashing does
NOT establish which source built that binary. A future build manifest must
record source identity, build environment and output hashes during the build.
Do not describe this runner as having completed that release-provenance work.

## Recreate this Windows/Python 3.11 dependency baseline

`requirements-validation-win-py311.txt` pins the distributions installed in
the Codex environment. It excludes the editable pyArgus package itself.
The one recipe that installs them is the **Fresh environment** block in
[WINDOWS_REBUILD.md](WINDOWS_REBUILD.md): uv with that pinned file in copy mode,
then `--no-deps --no-build-isolation -e .`, into a NEW environment made from an
installed Python 3.11, never Claude's or pyLynceus's venv. Then run
`devtools.validate` as above. An unpinned `uv pip install -e ".[dev]"` produces a
different environment and is not the validated one.

These are version pins, not a hash-locked wheel archive. Recreating the
environment on a clean machine is still an acceptance task; do not claim it
has happened merely because the current environment passes. Native PDAL,
Tk availability, PROJ grids, Windows/Python versions and reference datasets
are additional dependencies. Package versions alone do not reproduce them.

## Test hygiene and declarations

Every `test_cli*` module runs in its own scratch directory (root `conftest.py`),
because CLI commands record solve-only or refused invocations in the current
directory; a run that still writes into the checkout's `pyargus-job-records/`
ends with a red warning naming the files. `tests/test_crs.py` asserts that the
published Geoid18 grid is where PROJ will find it and that a NAVD88 transform
goes through it; an environment without the grid must declare so with
`PYARGUS_NO_GEOID=1` (CI does), which skips that one test. Set
`PYARGUS_PAYLOAD_FULL_HASH=1` to hash every payload file in
`tests/test_payload_contract.py` instead of the fixed sample.

## Source fingerprint

`devtools.fingerprint` (scheme `pyargus-source-fingerprint-v1`) is the one
source fingerprint: SHA-256 over the covered files in sorted path order, each as
path, NUL and the file's own SHA-256. It covers `pyargus/`, `tests/`,
`packaging/`, `devtools/`, `reference/` (without `reports/`), `.github/`,
`pyproject.toml`, `conftest.py`, `requirements-validation-win-py311.txt` and
`LICENSE`; documents, handoff notes, run outputs, logs and bytecode are
excluded, so the value changes only when something that runs changes. It needs
no git. `devtools.validate` records it as `source_before`/`source_after`
(`sha256` with `scheme`), and `review_handoff_20261021/prepare_packet.py`
records it as `source_fingerprint_sha256` with `fingerprint_scheme`; print it
with `.venv/Scripts/python.exe -m devtools.fingerprint` (`--list` names the files).

Records written before October 22, 2026 used two different schemes and cannot be
tied to each other or to this one: the October 19 reference battery
(`build/control-coverage-20261019/final-verification.json`, 73/73) recorded
`89b63adc…` over every git-known file of that day's tree, and the October 21
review packet (`review_handoff_20261021/source_identity.json`) recorded
`78ee9d49…` over its own root list. The next `devtools.validate --reference`
run and the next packet will share one value. The first run with the shared
scheme, `reference/reports/validation-20261022T153631Z-53660` (October 22,
15:36 UTC, source suite only, 777 passed and 7 explained skips), recorded
`c8c88e8ad88971b59b969d9ce35832dd546a98eb7540b27baf119ee9146e6104` (253 files)
for the tree with the October 21-22 review fixes.

## Progress against inventory I01

- Implemented: exact installed-version snapshot, serial command, working-source
  fingerprint, structured logs and explicit skipped-check review.
- Pending: clean-machine reproduction, pinned native dependency provenance,
  source-to-frozen-binary build manifest and identified desktop release.

The root application license is Apache-2.0; dependency licenses remain separate.


## Malformed environment metadata

The validation runner records unreadable or nameless installed distributions in
`environment_warnings` and continues collecting evidence. Such a run returns
`needs_environment_review` (nonzero) after otherwise successful requested checks;
test failures, changed source and skipped tests retain their own stricter status.
It never silently treats the malformed entry as a healthy dependency.

On October 21 the stale `pyargus-0.1.0.dist-info` contained only a licenses
subdirectory and no METADATA. It was moved, without deletion, into
`build/review-fixes-20261021/environment-quarantine/`. Current editable 0.2.0
metadata was retained. The subsequent inventory had no warnings and `pip check`
passed. This is an environment repair, not a new application installation.
