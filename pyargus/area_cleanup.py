"""Full-resolution polygon selection; classification export reuses EditSession."""
from dataclasses import dataclass
from pathlib import Path
import operator
import numpy as np
from pyargus.editing import EditSession, polygon_mask
from pyargus.job_manifest import identity


@dataclass
class Area:
    points: np.ndarray  # X,Y,Z; complete, unsampled editable selection
    classes: np.ndarray
    lines: np.ndarray
    point_indices: np.ndarray  # zero-based source records
    inputs: list
    crs: str
    polygon: list
    class_filter: list | None
    line_id: int | None
    z_min: float | None
    z_max: float | None
    in_polygon: int
    limit: int

    @property
    def matched(self):
        return len(self.points)

    def definition(self):
        return dict(polygon=self.polygon, class_filter=self.class_filter, las_line_id=self.line_id,
                    z_min=self.z_min, z_max=self.z_max, crs=self.crs, in_polygon=self.in_polygon,
                    selected=self.matched, full_resolution=True, limit=self.limit)


def extract_area(path, polygon, *, classes=None, line_id=None, z_min=None, z_max=None,
                 limit=1_000_000, chunk_size=250_000, cancel=None, progress=lambda s: None):
    """Stream one source, retain every matching record, or refuse an oversized area.

    Selection is inclusive in XY and height. No viewer sampling, visibility,
    class filters or trajectory matching are implicitly applied.
    """
    import laspy
    polygon = np.asarray(polygon, float)
    polygon_mask(np.empty((0, 2)), polygon)  # validate even for empty clouds
    limit, chunk_size = operator.index(limit), operator.index(chunk_size)
    if not 0 < limit <= 5_000_000 or chunk_size < 1:
        raise ValueError('Selection limit must be 1 to 5,000,000; chunk size must be positive.')
    if classes is not None:
        classes = sorted(set(operator.index(c) for c in classes))
        if not classes or min(classes) < 0 or max(classes) > 255:
            raise ValueError('Choose class numbers from 0 to 255, or All.')
    if line_id is not None:
        line_id = operator.index(line_id)
        if not 0 <= line_id <= 65535:
            raise ValueError('LAS line ID must be 0 to 65535, or All.')
    for value in (z_min, z_max):
        if value is not None and not np.isfinite(value):
            raise ValueError('Height limits must be finite, or blank for all heights.')
    if z_min is not None and z_max is not None and z_min > z_max:
        raise ValueError('Minimum height exceeds maximum height.')
    path = Path(path).resolve(); before = identity(path)
    lower, upper = polygon.min(axis=0), polygon.max(axis=0)
    rows, labels, lines, indices = [], [], [], []
    count = in_polygon = offset = 0
    def check():
        if cancel is not None and cancel.is_set():
            raise InterruptedError('Area selection cancelled')
    check()
    with laspy.open(path) as reader:
        crs = reader.header.parse_crs()
        if crs is None or not crs.is_projected:
            raise ValueError('Area cleanup requires a declared projected LAS CRS.')
        factors = [axis.unit_conversion_factor for axis in crs.axis_info]
        if not factors or not np.allclose(factors, factors[0], rtol=1e-12, atol=0):
            raise ValueError('Area cleanup requires matching XYZ units.')
        for chunk in reader.chunk_iterator(chunk_size):
            check()
            xyz = np.column_stack([chunk.x, chunk.y, chunk.z])
            ids = np.flatnonzero(np.isfinite(xyz).all(axis=1) &
                (xyz[:,0] >= lower[0]-1e-9) & (xyz[:,0] <= upper[0]+1e-9) &
                (xyz[:,1] >= lower[1]-1e-9) & (xyz[:,1] <= upper[1]+1e-9))
            ids = ids[polygon_mask(xyz[ids,:2], polygon)]
            in_polygon += len(ids)
            labels_chunk = np.asarray(chunk.classification)
            lines_chunk = np.asarray(chunk.point_source_id)
            keep = np.ones(len(ids), dtype=bool)
            if classes is not None: keep &= np.isin(labels_chunk[ids], classes)
            if line_id is not None: keep &= lines_chunk[ids] == line_id
            # LAS scaling/offset arithmetic can put an inclusive boundary a few
            # floating-point ULPs beyond its typed decimal; this is not a data-unit buffer.
            if z_min is not None: keep &= xyz[ids,2] >= z_min-4*np.finfo(float).eps*max(1.,abs(z_min))
            if z_max is not None: keep &= xyz[ids,2] <= z_max+4*np.finfo(float).eps*max(1.,abs(z_max))
            ids = ids[keep]; count += len(ids)
            if count > limit:
                raise ValueError(f'Area exceeds the {limit:,}-point editing limit. Narrow the polygon or use explicit class/height limits; no sampled edits were created.')
            if len(ids):
                rows.append(xyz[ids]); labels.append(labels_chunk[ids].copy())
                lines.append(lines_chunk[ids].copy()); indices.append(ids.astype(np.int64)+offset)
            offset += len(chunk)
            progress(f'Read {offset:,} source records; {count:,} editable returns / {in_polygon:,} inside polygon')
    check()
    if identity(path) != before:
        raise ValueError('Cloud changed during area extraction; read the area again.')
    if not count:
        raise ValueError('No points match the polygon and explicit class/line/height limits.')
    return Area(np.concatenate(rows), np.concatenate(labels), np.concatenate(lines),
                np.concatenate(indices), [before], crs.to_wkt(), polygon.tolist(), classes,
                line_id, None if z_min is None else float(z_min), None if z_max is None else float(z_max),
                in_polygon, limit)


class AreaEditSession(EditSession):
    def __init__(self, area):
        super().__init__(area, geometry=dict(area=area.definition(),
            selection_scope='Full-resolution XY polygon; all heights unless explicit height limits; only recorded class/line filters; one source cloud'),
            selection_axes=(0,1))
        self.area = area


def screen_to_map(viewer, x, y):
    """Invert an orthographic Top view, including yaw, cursor zoom and pan."""
    width, height = max(2, viewer.canvas.winfo_width()), max(2, viewer.canvas.winfo_height())
    scale = min(width, height)*.85/viewer.span*viewer.zoom
    q = (np.array([x,y])-[width/2,height/2]-viewer.pan)/[scale,-scale]
    angle = np.deg2rad(viewer.yaw)
    return viewer.center[:2] + q[0]*np.array([np.cos(angle),np.sin(angle)]) + q[1]*np.array([-np.sin(angle),np.cos(angle)])
