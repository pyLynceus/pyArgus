# Reproducible validation baseline

Use this checkout's Python and run heavy checks serially. The runner is a
source-validation tool, not a desktop builder or a production-accuracy claim.

## Record a validation

```powershell
& ./.venv/Scripts/python.exe -m devtools.validate
```

This runs `pip check` followed by pytest with `-ra` and JUnit XML. Each run
creates a unique ignored folder under `reference/reports/validation-*`:

- `validation.json`: exact Git commit, working-file fingerprint and dirty
  status before/after, interpreter/platform, installed versions, commands,
  exit codes, all nonpassing test names and reasons;
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
it merely to start a competing run.

## Real-data and executable checks

```powershell
& ./.venv/Scripts/python.exe -m devtools.validate --reference
& ./.venv/Scripts/python.exe -m devtools.validate --reference --exe ./dist/pyArgus/pyArgus.exe
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

```powershell
# Use an installed Python 3.11 to create a NEW environment, not Claude's venv.
python -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements-validation-win-py311.txt
& ./.venv/Scripts/python.exe -m pip install --no-deps --no-build-isolation -e .
& ./.venv/Scripts/python.exe -m devtools.validate
```

These are version pins, not a hash-locked wheel archive. Recreating the
environment on a clean machine is still an acceptance task; do not claim it
has happened merely because the current environment passes. Native PDAL,
Tk availability, PROJ grids, Windows/Python versions and reference datasets
are additional dependencies. Package versions alone do not reproduce them.

## Progress against inventory I01

- Implemented: exact installed-version snapshot, serial command, working-source
  fingerprint, structured logs and explicit skipped-check review.
- Pending: clean-machine reproduction, pinned native dependency provenance,
  source-to-frozen-binary build manifest and identified desktop release.

The root license decision remains separate and requires Bryon's choice.
