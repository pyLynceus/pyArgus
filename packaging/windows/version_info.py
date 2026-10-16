"""Windows executable metadata derived from the application release identity."""
from pathlib import Path
import runpy
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

release = runpy.run_path(str(Path(__file__).resolve().parents[2] / "pyargus/__init__.py"))
version = release["__version__"]
numeric_version = tuple(int(part) for part in version.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numeric_version, prodvers=numeric_version,
                     mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("CompanyName", "pyArgus contributors"),
        StringStruct("FileDescription", "pyArgus lidar review and processing"),
        StringStruct("FileVersion", version),
        StringStruct("InternalName", "pyArgus"),
        StringStruct("OriginalFilename", "pyArgus.exe"),
        StringStruct("ProductName", "pyArgus"),
        StringStruct("ProductVersion", version),
        StringStruct("Comments", "Release " + release["__release_date__"]),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)
