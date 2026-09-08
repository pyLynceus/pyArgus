"""Minimal DXF writing: contour polylines into CAD.

R12-style 3D POLYLINE/VERTEX entities with a proper layer table --
the oldest, most universally read dialect, so Civil 3D, MicroStation
and QGIS all open it without an import wizard. Group code and value
each get their own line per the spec. This module only WRITES; pyArgus
never round-trips CAD files.
"""

CONTOUR_LAYERS = {
    True: ("CONTOUR_INDEX", 1),          # color 1 = red
    False: ("CONTOUR_INTERMEDIATE", 8),  # color 8 = dark grey
}


def _rows(*pairs):
    return "".join(f"{code}\n{value}\n" for code, value in pairs)


def write_contours_dxf(path, lines):
    """Write ContourLines as 3D polylines at their level elevation."""
    if not lines:
        raise ValueError("no contour lines to write")
    out = [_rows((0, "SECTION"), (2, "HEADER"), (0, "ENDSEC"))]
    out.append(_rows((0, "SECTION"), (2, "TABLES"),
                     (0, "TABLE"), (2, "LAYER"), (70, 2)))
    for name, color in CONTOUR_LAYERS.values():
        out.append(_rows((0, "LAYER"), (2, name), (70, 0),
                         (62, color), (6, "CONTINUOUS")))
    out.append(_rows((0, "ENDTAB"), (0, "ENDSEC")))
    out.append(_rows((0, "SECTION"), (2, "ENTITIES")))
    for line in lines:
        layer, _ = CONTOUR_LAYERS[bool(line.is_index)]
        flags = 8 | (1 if line.closed else 0)   # 8 = 3D polyline
        out.append(_rows((0, "POLYLINE"), (8, layer), (66, 1),
                         (70, flags), (10, 0.0), (20, 0.0), (30, 0.0)))
        vertices = line.xy[:-1] if line.closed else line.xy
        for x, y in vertices:
            out.append(_rows((0, "VERTEX"), (8, layer),
                             (10, f"{x:.4f}"), (20, f"{y:.4f}"),
                             (30, f"{line.level:.4f}"), (70, 32)))
        out.append(_rows((0, "SEQEND")))
    out.append(_rows((0, "ENDSEC"), (0, "EOF")))
    with open(path, "w", newline="\n") as fh:
        fh.write("".join(out))
