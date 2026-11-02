# October 22, 2026 Windows review-fix build

This is a new dated Windows build of pyArgus 0.2.0. The application version and
base release date remain 0.2.0 / October 16; the adjacent build record identifies
the October 22 review-fix source. It includes the combined backend repairs and
Claude's task-input, result-promotion, window-fit and camera-continuity changes.

Installer: dist-installer/0.2.0-review-2026-10-22/
pyArgus-0.2.0-2026-10-22-review-fixes-windows-x64-setup.exe.
Portable application: dist/0.2.0-review-2026-10-22/pyArgus/pyArgus.exe.
Keep the whole application folder together. This package supersedes the older
October 16/19 Windows payloads, which fail the current release-content gate.
The October 19 Arch package is unchanged by this Windows build.

## Software acceptance

- Combined source suite: 783 passed, one Linux-only X11 ownership skip, zero
  failures. pip check passed. Raw verdict needs_skip_review is preserved;
  only that Linux-specific test is outside the Windows acceptance scope.
- All 73 reference checks passed across nine modules against unchanged expected
  values. Canonical source fingerprint for tests and the published source ZIP:
  c8c88e8ad88971b59b969d9ce35832dd546a98eb7540b27baf119ee9146e6104.
- Frozen and relocated executable self-tests passed with a clean child
  environment and isolated workspace state. Required RTX A4000 mono/stereo GPU
  rendering, two-worker tiled classification, bundled PDAL COPC conversion with
  ExtraBytes/CRS preservation, and the checksum-verified Geoid18 NAVD88 transform
  all passed. Synthetic LP360 processing and role-separated report export passed.
- Payload audit passed: 53 native package records and their recipes; all eight
  required upstream archives verified against exact recipe SHA-256 values.
  The source ZIP includes all 253 canonical source files, including CI/conftest;
  private HANDOFF/CLAUDE working notes are excluded. Full payload hashes verified
  with no missing, changed or unlisted files before installer compilation.

## Installation scope

This build has not been installed over the registered Codex copy. Install,
upgrade, shortcut creation and uninstall acceptance remain pending on a clean
Windows account/VM or after explicit coordination of the existing registered
installation. The dated installers share one Codex AppId; a silent lifecycle
trial here would repoint and then remove the existing installation. Portable
runtime and relocation checks do not establish installer lifecycle acceptance.
No project datasets, production LAS or existing installations were modified.

This is an unsigned development build for Windows x64; no production survey
accuracy certification or new cloud adjustment is implied. AMD/Intel graphics,
Windows 10 and Linux need their own platform/hardware acceptance.

## Reproduction and evidence

Build with the tracked packaging/pyArgus.spec, stage into a new directory using
packaging/windows/stage_installer.py, then run the included
Sources/build-support/finalize_release.py to include all canonical source files
and verify source, content and full manifest hashes. Native upstream cache reuse
requires matching the exact conda recipe SHA-256; no dependency source omission
is permitted. Compile packaging/windows/pyArgus.iss with ReleaseDate=
2026-10-22-review-fixes and explicit StageDir / InstallerOutputDir.

Build evidence: build/release-review-20261022/; installer-side verification.json,
payload-manifest.json, build-info.json and SHA256SUMS.txt record the final result.
Source/reference evidence: build/review-validation-20261022/final-verification.json
and reference/reports/validation-20261022T161651Z-20460/validation.json.
No commit or push is included in this release operation.
