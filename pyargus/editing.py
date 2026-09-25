"""Source-indexed, single-section classification edits and verified exports."""
from pathlib import Path
import hashlib
import json
import os
import uuid
import numpy as np
from pyargus.job_manifest import identity, utc_now


def polygon_mask(points, vertices):
    """Inclusive even-odd selection in station/elevation coordinates."""
    p, v = np.asarray(points, float), np.asarray(vertices, float)
    if v.ndim != 2 or v.shape[1] != 2 or len(v) < 3 or not np.isfinite(v).all():
        raise ValueError('Draw a polygon with at least three finite vertices.')
    v = v - v[0]  # Preserve precision with large elevations.
    p = p - np.asarray(vertices, float)[0]
    if np.linalg.matrix_rank(v) < 2:
        raise ValueError('Selection must have nonzero area.')
    x, y = p.T
    inside = np.zeros(len(p), bool); boundary = inside.copy()
    for a, b in zip(v, np.roll(v, -1, axis=0)):
        dx, dy = b-a
        tol = 1e-9 * max(1., np.hypot(dx, dy))
        cross = (x-a[0])*dy-(y-a[1])*dx
        boundary |= (np.abs(cross) <= tol) & (x >= min(a[0],b[0])-1e-9) & (x <= max(a[0],b[0])+1e-9) & (y >= min(a[1],b[1])-1e-9) & (y <= max(a[1],b[1])+1e-9)
        if dy:
            inside ^= ((a[1]>y) != (b[1]>y)) & (x < dx*(y-a[1])/dy+a[0])
    return inside | boundary


class EditSession:
    def __init__(self, section):
        import laspy
        if len(section.inputs) != 1:
            raise ValueError('Editing requires a section from exactly one cloud.')
        if section.matched != len(section.points):
            raise ValueError('This section is sampled. Narrow the corridor until all returns are displayed, then extract again.')
        if not len(section.points):
            raise ValueError('The section is empty.')
        self.source = Path(section.inputs[0]['path'])
        self.identity = dict(section.inputs[0])
        self.check_source()
        self.indices = np.asarray(section.point_indices, np.int64).copy()
        if len(np.unique(self.indices)) != len(self.indices) or np.any(self.indices < 0):
            raise ValueError('Invalid source point indices.')
        with laspy.open(self.source) as reader:
            self.max_class = 31 if reader.header.point_format.id < 6 else 255
            if reader.header.point_format.id in (4,5,9,10):
                raise ValueError('Waveform files require a separate preservation workflow.')
            if any(v.user_id == 'copc' for v in reader.header.vlrs):
                raise ValueError('Convert COPC to ordinary LAS/LAZ before editing.')
            if self.indices.max() >= reader.header.point_count:
                raise ValueError('Invalid source point indices.')
        self.points = section.points.copy()
        self.original = section.classes.copy(); self.classes = self.original.copy()
        self.start, self.end, self.width = section.start, section.end, section.width
        self.undo_stack, self.redo_stack, self.events = [], [], []

    def check_source(self):
        if identity(self.source) != self.identity:
            raise ValueError('Source changed since section extraction. Reopen and extract again.')

    def select(self, vertices):
        return np.flatnonzero(polygon_mask(self.points[:, [3,2]], vertices))

    def assign(self, selected, classification):
        if not isinstance(classification, (int, np.integer)) or not 0 <= classification <= self.max_class:
            raise ValueError(f'Class must be an integer from 0 to {self.max_class} for this LAS format.')
        ids = np.unique(np.asarray(selected, np.int64))
        if np.any(ids < 0) or np.any(ids >= len(self.classes)):
            raise ValueError('Invalid selection indices.')
        ids = ids[self.classes[ids] != classification]
        if not len(ids): return 0
        # Bound retained undo data instead of growing indefinitely.
        if sum(len(x[0]) for x in self.undo_stack) + len(ids) > 5_000_000:
            raise ValueError('Undo history is full. Export and start a new editing session.')
        edit = (ids, self.classes[ids].copy(), int(classification))
        self.undo_stack.append(edit); self.redo_stack.clear()
        self.classes[ids] = classification
        self.events.append(dict(action='assign', classification=int(classification), count=len(ids), at=utc_now()))
        return len(ids)

    def undo(self):
        if not self.undo_stack: return
        edit = self.undo_stack.pop(); self.classes[edit[0]] = edit[1]
        self.redo_stack.append(edit); self.events.append(dict(action='undo', at=utc_now()))

    def redo(self):
        if not self.redo_stack: return
        edit = self.redo_stack.pop(); self.classes[edit[0]] = edit[2]
        self.undo_stack.append(edit); self.events.append(dict(action='redo', at=utc_now()))

    @property
    def changed(self):
        return int(np.count_nonzero(self.classes != self.original))

    def export(self, destination, *, cancel=None, progress=lambda s: None, chunk_size=250000):
        """Verify all records before publishing; never overwrite input or output."""
        import laspy
        dst = Path(destination).resolve(); sidecar = dst.with_suffix(dst.suffix+'.edits.json')
        if dst.suffix.lower() not in ('.las', '.laz'):
            raise ValueError('Output must be LAS or LAZ.')
        if dst.exists() or sidecar.exists() or dst == self.source.resolve():
            raise ValueError('Choose a new output filename; source and existing outputs are protected.')
        if chunk_size < 1: raise ValueError('Chunk size must be positive.')
        self.check_source()
        mask = self.classes != self.original
        order = np.argsort(self.indices[mask]); ids = self.indices[mask][order]
        before, after = self.original[mask][order], self.classes[mask][order]
        if not len(ids): raise ValueError('There are no pending classification changes.')
        token = uuid.uuid4().hex
        tmp = dst.with_name('.'+dst.stem+'.'+token+dst.suffix)
        meta = dst.with_name('.'+token+'.json')
        published = []
        def check():
            if cancel is not None and cancel.is_set(): raise InterruptedError('Editing export cancelled')
        def vlrs(header):
            return [(v.user_id,v.record_id,v.description,bytes(v.record_data_bytes())) for v in header.vlrs if v.user_id != 'laszip encoded']
        def evlrs(header):
            return [(v.user_id,v.record_id,v.description,bytes(v.record_data_bytes())) for v in (header.evlrs or [])]
        expected = hashlib.sha256(); original = hashlib.sha256(); count = 0
        try:
            check()
            with laspy.open(self.source) as reader:
                header = reader.header.copy()
                with laspy.open(tmp, mode='w', header=header) as writer:
                    for chunk in reader.chunk_iterator(chunk_size):
                        check(); original.update(chunk.array.tobytes())
                        lo, hi = np.searchsorted(ids, [count, count+len(chunk)])
                        local = ids[lo:hi]-count
                        if not np.array_equal(np.asarray(chunk.classification)[local], before[lo:hi]):
                            raise ValueError('Source classifications no longer match the extracted section.')
                        values = np.asarray(chunk.classification).copy(); values[local] = after[lo:hi]
                        chunk.classification = values
                        expected.update(chunk.array.tobytes()); writer.write_points(chunk)
                        count += len(chunk); progress(f'Writing {count:,}/{header.point_count:,} points')
                    # laspy recomputes extra-dimension extrema while writing.
                    # Classification-only edits must retain their original metadata.
                    from copy import deepcopy
                    for i, vlr in enumerate(writer.header.vlrs):
                        if vlr.user_id == 'LASF_Spec' and vlr.record_id == 4:
                            original_vlr = next(v for v in header.vlrs if v.user_id == 'LASF_Spec' and v.record_id == 4)
                            writer.header.vlrs[i] = deepcopy(original_vlr)
                    if header.evlrs: writer.write_evlrs(header.evlrs)
            check(); self.check_source(); progress('Verifying every output point record')
            actual = hashlib.sha256(); verified = 0
            with laspy.open(tmp) as reader:
                h = reader.header
                if (h.point_format != header.point_format or h.version != header.version or
                    not np.array_equal(h.scales,header.scales) or not np.array_equal(h.offsets,header.offsets) or
                    h.parse_crs() != header.parse_crs() or vlrs(h) != vlrs(header) or evlrs(h) != evlrs(header)):
                    raise ValueError('Output schema or metadata verification failed.')
                for chunk in reader.chunk_iterator(chunk_size):
                    check(); actual.update(chunk.array.tobytes()); verified += len(chunk)
            if verified != count or count != header.point_count or actual.digest() != expected.digest():
                raise ValueError('Output point record verification failed.')
            self.check_source(); check()
            report = dict(schema_version=1, operation='manual-classification', status='verified', source=self.identity,
                output=str(dst), created_utc=utc_now(), points=count, changed=len(ids),
                section=dict(start=self.start,end=self.end,full_width=self.width),
                selection_scope='Full corridor depth; station/elevation selection; no hidden class or line filters',
                source_record_sha256=original.hexdigest(), output_record_sha256=actual.hexdigest(),
                edits=[dict(point_index=int(i), before=int(b), after=int(a)) for i,b,a in zip(ids,before,after)],
                history=list(self.events))
            meta.write_text(json.dumps(report,indent=2),encoding='utf8')
            # Windows rename is exclusive and works on OneDrive/network folders
            # where hard links may be unavailable. POSIX rename can overwrite.
            def publish(source, target):
                if os.name == 'nt': os.rename(source, target)
                else: os.link(source, target)
            publish(tmp,dst); published.append(dst)
            publish(meta,sidecar); published.append(sidecar)
            return report
        except BaseException:
            for path in published: path.unlink(missing_ok=True)
            raise
        finally:
            tmp.unlink(missing_ok=True); meta.unlink(missing_ok=True)
