# Windows installation package — October 8, 2026

The current package is built from the isolated Codex checkout. It includes the
frozen application, its private native PDAL runtime, the narrated video and
captions, user and technical guides, two synthetic practice clouds and their
trajectories and DXF, application source, dependency recipes, and notices.
Production LAS, control, imagery, and workspaces are not installation assets.

## Operator installation

Run the dated windows-x64-setup.exe from dist-installer/2026-10-08.
Windows 10/11 on x64 is required; this build is not validated on ARM.
Installation is per user and defaults to:
%LOCALAPPDATA%/Programs/pyArgus-Codex

No separate Python, QGIS, Conda, network download, or administrator elevation is
required on the destination machine. Use the Start menu's pyArgus (Codex) group.
It includes pyArgus, the chapter-based tutorial, Getting started, and Uninstall.
A desktop shortcut is optional.

The installed pyArgus.exe sets PDAL_EXE only in its own process when the private
native-pdal/Library/bin/pdal.exe is present. An existing operator override takes
precedence. No machine PATH or file association changes are made.
The full application folder, including _internal and native-pdal, must stay
together if it is subsequently moved as a portable copy.

Create workspaces and outputs outside the installation directory. Copy Examples
to a working folder before practicing. No workspace containing the developer's
absolute example paths is supplied. The bundled example report is synthetic.

Uninstall through Windows Settings > Apps or the Start menu shortcut.
Application files are removed; project files kept in their own folders are not
installer-managed. The installer has a different AppId and default folder from
the former Mapworks installer and does not replace that installation.

This development build is unsigned. The video is an edited walkthrough of the
actual GUI and generated example data, not a continuous live mouse recording.
Its alignment chapter explains setup; it does not claim a production alignment.

## Repeatable build

Use the pinned environment described in WINDOWS_REBUILD.md. Build the frozen
application before staging. Keep retained releases in separate dated folders.

    .venv/Scripts/python.exe -m PyInstaller --noconfirm packaging/pyArgus.spec --distpath dist/2026-10-08-acceleration --workpath build/installer-20261008/pyinstaller

Prepare a payload in an empty, local directory. stage_installer.py accepts
--release 2026-10-08, --app-dir, --native-prefix, --tutorial-zip, --example-dir, and --output-dir.
The native prefix is .venv/native-pdal; the tutorial ZIP is the completed
dist/training-video-2026-10-05/pyArgus-Video-and-Guide.zip.
The example directory is the generated Videos/pyArgus-training/2026-10-05 folder.
It copies only the specifically named TRAINING_ LAS/TRJ/DXF files.
The script verifies upstream source archive SHA256 values from the exact cached
conda recipes before including them. On first build these source archives need
network access; destination installation itself is entirely offline.

The runtime contains the native DLLs, executables, shared CRS data, SSL data,
libexec helpers and activation metadata. Headers and static development libraries
are excluded. Corresponding recipes and patches are included for every package.
GPL/LGPL/MPL upstream sources, GDAL and libarchive sources are included alongside
the application source ZIP. Python dependency notices include embedded notices.
Sources/native-packages.json identifies exact native versions and source hashes.

Compile packaging/windows/pyArgus.iss using the verified Inno Setup compiler:

    ISCC.exe /DReleaseDate=2026-10-08 /DStageDir=<absolute prepared payload> /DInstallerOutputDir=<absolute release directory> packaging/windows/pyArgus.iss

Inno Setup 7.1.0 x64 was obtained from the official release. Its Authenticode
signature was validated as Pyrsys B.V. before execution. The compiler download
SHA256 is 0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f.
Compiler home: build/installer-20261005/tools/InnoSetup.
Official sources: https://jrsoftware.org/isdl.php and
https://jrsoftware.org/isdl-verify.php.

## Validation and provenance

The payload's build-info.json identifies source HEAD, modified packaging entry
point, package versions, exact executable and video SHA256, and source-content
fingerprint. payload-manifest.json identifies every staged file and hash.
Installer release notes and validation results accompany the setup executable.
The previous October 2 application evidence remains historical; its executable
hash must not be reported as the new installer build's hash.

Test the actual delivered installer in a unique local directory with spaces,
using the separate Codex installation identity, and with post-install launch suppressed.
Verify all manifest files, installed shortcuts, the frozen --self-test, private
PDAL and CRS tools without environment activation, relocation, and uninstall.
Only the exact test target's uninstaller may be run; verify its absolute path.
No test may change the production project directories or original Claude checkout.

The installed self-test adds a native COPC conversion with extra-dimension and
CRS checks when private PDAL is present, in addition to existing GUI, workspace,
classification, DXF, QA, sections, and review checks.
The acceleration source passed 586 checks with no skips and all 73 Summerville
reference checks. Frozen installed/relocated checks additionally require actual
GPU normal/stereo rendering on the RTX A4000, CPU compatibility rendering and a
written two-worker tiled classification. Use --self-test --require-gpu
--self-test-report <outside-app.json> for an explicit hardware acceptance report.
Ordinary --self-test permits a supported CPU fallback; normal application launch
never requires a GPU. The official NOAA Geoid18 grid is included in Python PROJ.

Exact installation results, payload counts/hashes, repair/uninstall and separate
project preservation are recorded in dist-installer/2026-10-08/installer-validation.json.
Windows 11 x64 is the tested OS; AMD/Intel GPUs and Windows 10 need separate hardware
acceptance. See ACCELERATION.md for measured gains and execution limits.
