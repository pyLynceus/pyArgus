# pyArgus 0.2.0 for Arch Linux x86_64

This package contains a native Linux executable and its private Python runtime.
It is an Arch package, not a Windows executable, Wine wrapper or a universal
Linux binary. It targets the tested Arch glibc baseline (2.44 or newer).

## Install and launch

Install the delivered package with `sudo pacman -U pyargus-0.2.0-2-x86_64.pkg.tar.zst`.
Run `pyargus-gui`, choose pyArgus from the desktop application menu, or use
`pyargus --help` and `pyargus --version` for the command-line interface.
The program is installed under `/usr/lib/pyargus`; commands are in `/usr/bin`.
Keep workspaces and output files outside the application installation.

The package includes Python, numerical libraries, LAS/LAZ readers, classification,
CAD support, viewing and reporting. System desktop/graphics libraries are declared
pacman dependencies. PDAL is an optional system dependency for COPC export:
`sudo pacman -S pdal`. The release verification records whether it was exercised.

On WSL use the installed `archlinux` distribution and WSLg. The launcher scopes
D3D12 and WSL driver-library discovery to pyArgus when those drivers are present.
Native Linux retains its existing graphics configuration. Unsupported OpenGL
continues to use the application's CPU renderer. GPU tests identify the actual
renderer; software OpenGL is never reported as GPU acceleration.

Windows paths in saved workspaces are not automatically rewritten. From Linux,
use `/mnt/c/...` for Windows local files. Network drives require a separately
accessible Linux mount. Save a separate Linux workspace with paths that exist
in that environment. WSL folder actions use Windows Explorer when available;
native Linux uses its registered desktop folder opener. With no explicit BROWSER
setting, WSL report links open in the Windows default browser with translated
file paths. The same verified Geoid18 grid as the Windows build is included.

## Verification and provenance

The delivered verification JSON records source tests, Python/package versions,
actual installation, frozen-runtime and CLI checks, GPU/stereo, multicore,
PDAL/COPC, LP360 and report checks, file hashes and remaining limitations.
The build uses a separate non-root Linux workspace and environment. The October
19 package was built with Python 3.14.7 and current, unpinned dependency
versions, newer than the Windows 3.11 pins in
`requirements-validation-win-py311.txt` and outside the CI matrix (3.10 to 3.12);
its verification JSON records the exact versions, and its 694 passing source
tests ran under that interpreter, not the pinned one. Older Windows
releases and other application environments are retained. This is a local
unsigned development package; it has not been submitted to Arch repositories.
No project accuracy certification or new field-reference acceptance is implied.

## Rebuild

Build the Linux executable from `packaging/linux/pyArgus.spec` on Linux with the
project dependencies plus PyInstaller. Stage its full onedir payload with guides,
licenses, desktop icon, source archive and build information. Archive that folder
as `pyargus-0.2.0-linux-x86_64.tar.gz`, record its SHA256 in the supplied PKGBUILD,
and run `makepkg` as a non-root user. Check the package with namcap before actual
installation and installed-runtime verification. Exact release commands and logs
are retained with this build's validation evidence.
