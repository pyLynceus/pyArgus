"""Native TerraScan TSCANTRJ, version 20010715 (little endian).

Layout: https://terrasolid.com/guides/tscanuav/terrascan-trajectory-binary-fi.html
Coordinates, time base and attitude convention are NOT declared by this format.
Keep source values; never infer CRS, units, GPS week or angle signs from a name.
"""
from dataclasses import dataclass
from pathlib import Path
import struct
import numpy as np

RECORD_DTYPE = np.dtype([
    ("time", "<f8"), ("x", "<f8"), ("y", "<f8"), ("z", "<f8"),
    ("heading", "<f8"), ("roll", "<f8"), ("pitch", "<f8"),
    ("quality_xy", "u1"), ("quality_z", "u1"),
    ("quality_heading", "u1"), ("quality_rp", "u1"),
    ("mark", "<i2"), ("flag", "<i2")])

@dataclass
class Trajectory:
    records: np.ndarray
    description: str
    system_id: int
    quality: int
    original_number: int
    line_number: int
    group: str

    def summary(self):
        d = self.records
        t = d["time"]
        span = float(t[-1] - t[0])
        lines = ["TerraScan TRJ (20010715)",
                 f"Line: {self.line_number}; system: {self.system_id}",
                 f"Positions: {len(d):,}; duration: {span:.3f} s",
                 f"Rate: {(len(d)-1)/span if span else 0:.2f} Hz",
                 f"Stored time: {t[0]:.6f} .. {t[-1]:.6f}"]
        for name in ("x", "y", "z", "heading", "roll", "pitch"):
            lines.append(f"{name}: {d[name].min():.4f} .. {d[name].max():.4f}")
        lines += ["Angles above are degrees. XYZ units/CRS and time base are not embedded.",
                  "Import does not establish alignment accuracy or attitude conventions."]
        return "\n".join(lines)

def read_trj(path):
    path = Path(path)
    with path.open("rb") as f:
        header = f.read(1376)
        if len(header) < 1376:
            raise ValueError("truncated TRJ header (expected 1376 bytes)")
        magic, version, size, count, stride = struct.unpack_from("<8s4i", header)
        if magic != b"TSCANTRJ":
            raise ValueError("not a TerraScan TSCANTRJ file")
        if (version, size, stride) != (20010715, 1376, 64):
            raise ValueError(f"unsupported TRJ layout: version={version}, header={size}, record={stride}")
        if count < 1 or path.stat().st_size != size + count * stride:
            raise ValueError("TRJ record count/size mismatch or empty trajectory")
        data = np.fromfile(f, dtype=RECORD_DTYPE, count=count)
    for name in ("time", "x", "y", "z", "heading", "roll", "pitch"):
        if not np.isfinite(data[name]).all():
            raise ValueError(f"TRJ {name} contains nonfinite values")
    if np.any(np.diff(data["time"]) <= 0):
        raise ValueError("TRJ time is not strictly increasing")
    begin, end, original, number = struct.unpack_from("<2d2i", header, 104)
    if not np.isfinite([begin, end]).all() or not np.allclose(
            [begin, end], data["time"][[0, -1]], rtol=0, atol=1e-6):
        raise ValueError("TRJ header time bounds disagree with position records")
    def text(raw):
        return raw.split(b"\0", 1)[0].decode("cp1252", errors="replace")
    return Trajectory(data, text(header[24:102]), header[102], header[103],
                      original, number, text(header[1360:1376]))
