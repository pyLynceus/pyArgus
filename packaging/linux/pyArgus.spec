# Native Linux build; Windows has its separate packaging/pyArgus.spec.
from pathlib import Path
ROOT = Path(SPECPATH).resolve().parents[1]
a = Analysis([str(ROOT / "packaging/linux/launch.py")],
    pathex=[str(ROOT), str(ROOT / "packaging")], binaries=[],
    datas=[(str(ROOT / "pyargus/assets"), "pyargus/assets")],
    hiddenimports=["glcontext", "glcontext.x11", "glcontext.egl", "pyargus.cli", "PIL._tkinter_finder", "PIL._imagingtk"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["matplotlib", "contourpy", "kiwisolver", "cycler"], noarchive=False)
# Use Arch's graphics/driver ABI and C++ runtime instead of shadowing WSLg drivers.
system_runtime = ("libstdc++.so", "libgcc_s.so", "libGL.so", "libGLX.so",
                  "libEGL.so", "libGLdispatch.so", "libdrm.so")
a.binaries = [entry for entry in a.binaries if not Path(entry[0]).name.startswith(system_runtime)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="pyArgus",
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="pyArgus")
