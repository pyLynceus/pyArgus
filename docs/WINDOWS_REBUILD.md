Current operator installation: see [WINDOWS_INSTALLER.md](WINDOWS_INSTALLER.md) for the verified October 5 offline installer, which includes native PDAL and training materials. The October 2 rebuild below is retained history.

# Windows environment and executable rebuild - October 2, 2026

The current isolated checkout is `C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex`. The copied virtual environment
could not start because its uv-managed Python installation was absent. It was
preserved in `build/migration-20261002/old-venv`; the replacement `.venv` uses
Python 3.11.15 and every pin in `requirements-validation-win-py311.txt`.

## Current release

`C:/Users/bjordan/OneDrive - Platinum Geomatics/pyArgus-Codex/dist/2026-10-02-54986d5/pyArgus/pyArgus.exe`

Run `pyArgus.exe` for the GUI. Keep its containing folder and `_internal`.
`build-info.json` records exact source, working-content fingerprint, package
versions, build command, executable hash and self-test results.
`Launch pyArgus.cmd` starts the same GUI and sets `PDAL_EXE` for the private
native runtime. It locates `.venv/native-pdal` three parents above the application
folder. This helper assumes the dated release remains under this checkout's
`dist` folder. Moving a release does not move that native runtime automatically.
The frozen GUI carries its Python libraries and Tk; native COPC writing remains
an external PDAL dependency. No application/numerical modules were changed.

## Fresh environment

Create a new environment; preserve any environment you still need before using
an existing destination. Do not rebuild the original/Claude or pyLynceus venv.
Use copy mode for installation into OneDrive.

```powershell
uv python install 3.11.15
uv venv --python 3.11.15 .venv
uv pip install --python .venv/Scripts/python.exe --link-mode copy -r requirements-validation-win-py311.txt
uv pip install --python .venv/Scripts/python.exe --link-mode copy --no-deps --no-build-isolation -e .
uv pip install --python .venv/Scripts/python.exe --link-mode copy 'PyInstaller==6.22.3' 'pyinstaller-hooks-contrib==2026.7'
& ./.venv/Scripts/python.exe -m pip check
```

## Native COPC support

Private runtime: `.venv/native-pdal/Library/bin/pdal.exe`, PDAL 2.10.2.
Its 53 native package identities are recorded in the adjacent build-info.json.
The installer is under `build/migration-20261002/tools/Library/bin/micromamba.exe`.
Use the shorter cache root `C:/Users/bjordan/.cache/pyargus-mamba`; the original
long OneDrive cache path failed while unpacking a Xerces documentation filename.
Installation was completed using `--always-copy` and the shorter cache.

```powershell
$env:PDAL_EXE = Join-Path (Get-Location) '.venv/native-pdal/Library/bin/pdal.exe'
& $env:PDAL_EXE --version
& ./.venv/Scripts/python.exe -m pytest tests/test_copc.py -q -ra
```

PDAL is available from [conda-forge](https://pdal.org/en/latest/download.html).
The private installer follows the [official micromamba Windows instructions](https://mamba.readthedocs.io/en/stable/installation/micromamba-installation.html).
It does not initialize a global shell or change other project environments.

## Build and verify

Choose new output folders to preserve retained releases. The command used was:

```powershell
& ./.venv/Scripts/python.exe -m PyInstaller --noconfirm packaging/pyArgus.spec --distpath dist/2026-10-02-54986d5 --workpath build/migration-20261002/pyinstaller
```

Full regression: 562 passed, six skipped for missing PDAL. After installing the
private runtime, all nine COPC checks passed. The combined JUnit case identities
cover all 568 distinct source checks, with every previous skip resolved.
This is two serial runs, not a second all-tests run. The original validator's
`needs_skip_review` result is retained; the explicit retest resolves its cause.
The packaged executable then passed `--self-test`, exit 0 in 10.01 seconds.
It was tested from `build/migration-20261002/frozen-smoke`, with Python path/home
and virtual-environment variables removed from its child environment.

Application source: `54986d5aa614a1a68d4da0a5cccdda4a3df9c2a3` (clean at build).
SHA256: `7159178b0577d682613248e59b44fc925ff702c7b814be912746585b52240fab`.
The handoff/status edits recording this rebuild occur after that application
build; they do not change the source identity embedded in its build-info.json.
No new real-data reference battery or production accuracy acceptance is claimed.

Evidence:

- `reference/reports/validation-20261002T223454Z-27136/validation.json`
- `build/migration-20261002/copc-tests.xml`
- `build/migration-20261002/environment-validation.json`
- `build/migration-20261002/build-start.json` and `build.log`
- `build/migration-20261002/frozen-self-test.log`

All builds and tests were serial. The missing former staging folder and October 1
inventory PDF are separate migration items; they were not recovered by rebuilding.
