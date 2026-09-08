# -*- mode: python ; coding: utf-8 -*-
# Build (from the repo root; PyInstaller lives in the project venv,
# installed ad hoc, not a pyproject dependency):
#
#   .venv/Scripts/python.exe -m PyInstaller --noconfirm packaging/pyArgus.spec --distpath dist --workpath build
#
# Only the dist copy runs: the build leaves a second pyArgus.exe in
# build/ scratch whose _internal is never assembled. Delete build/
# after building; it is cache and regenerates (the pyLynceus lesson).


a = Analysis(
    ['launch_gui.py'],
    pathex=[],
    binaries=[],
    # The brand assets ride along so the window can wear its icon at
    # runtime; the path is relative to this spec file. pyproj's grid
    # data comes in through its contrib hook.
    datas=[('../pyargus/assets', 'pyargus/assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # matplotlib is imported nowhere in this project; keep the
    # exclusion so a future incidental install cannot sweep ~14 MB of
    # dead weight into the bundle (learned on pyLynceus).
    excludes=['matplotlib', 'contourpy', 'kiwisolver', 'cycler'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='pyArgus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../pyargus/assets/pyArgus.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='pyArgus',
)
