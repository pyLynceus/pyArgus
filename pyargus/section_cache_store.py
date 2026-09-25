"""Owned local cache lifecycle and transparent full-scan fallback."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from pyargus import section_cache
from pyargus.job_manifest import identity


class CacheBusy(OSError):
    pass


class CacheStore:
    def __init__(self,root=None):
        base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.cache'))
        self.root=Path(root or base/'pyArgus-Codex'/'section-cache-v2').resolve()

    def path(self,source):
        payload=dict(version=2,source=identity(source),cell=50.,chunk_size=250000)
        key=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        return self.root/key

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with (self.root/'.lock').open('a+b') as stream:
            if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
            stream.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:raise CacheBusy('Section cache is busy in another operation') from exc
            try:yield
            finally:
                stream.seek(0)
                if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

    def remove_owned(self,path):
        path=Path(path)
        if not (re.fullmatch('[0-9a-f]{64}',path.name) or re.fullmatch(r'\.section-cache-[a-zA-Z0-9_-]+',path.name)):
            raise ValueError('Refusing to remove an unrecognized cache folder')
        if path.resolve().parent!=self.root:raise ValueError('Cache folder escapes owned root')
        for item in path.rglob('*'):
            if not item.resolve().is_relative_to(self.root):raise ValueError('Cache contains an external link')
        shutil.rmtree(path)

    def build(self,paths,*,cancel=None,progress=lambda text:None):
        import laspy
        built=reused=0
        with self.locked():
            for i,source in enumerate(paths,1):
                section_cache.check_cancel(cancel);target=self.path(source)
                if target.exists():
                    try:
                        m=section_cache.load(target)
                        if m['source']!=identity(source):raise ValueError('Cache source mismatch')
                        reused+=1;progress(f'Cache {i}/{len(paths)} already ready: {Path(source).name}');continue
                    except (OSError,ValueError,KeyError,TypeError):self.remove_owned(target)
                with laspy.open(source) as reader:required=int(reader.header.point_count)*128+256*1024**2
                if shutil.disk_usage(self.root).free<required:
                    raise OSError(f'Insufficient cache space: need about {required/1024**3:.2f} GiB including reserve. Clear caches or free local disk space.')
                section_cache.build(source,target,cancel=cancel,progress=lambda s:progress(f'Cache {i}/{len(paths)} — {s}'))
                built+=1
        return f'Cache ready: {built} built, {reused} reused. Local folder: {self.root}'

    def clear(self,*,cancel=None,progress=lambda text:None):
        count=0
        with self.locked():
            for path in self.root.iterdir():
                section_cache.check_cancel(cancel)
                if path.is_dir() and (re.fullmatch('[0-9a-f]{64}',path.name) or re.fullmatch(r'\.section-cache-[a-zA-Z0-9_-]+',path.name)):
                    self.remove_owned(path);count+=1;progress(f'Cleared {count} local section caches')
        return f'Cleared {count} local section caches. Source clouds unchanged.'

    def extract(self,paths,start,end,width,*,limit=100000,cancel=None,progress=lambda text:None):
        from pyargus.sections import extract_section
        section_cache.check_cancel(cancel)
        reason='cache unavailable'
        try:
            with self.locked():
                caches=[self.path(p) for p in paths];manifests=[section_cache.load(p) for p in caches]
                if any(m['source']!=identity(p) for m,p in zip(manifests,paths)):raise ValueError('Cache source mismatch')
                if any(m['chunk_size']!=250000 for m in manifests):raise ValueError('Cache sampling chunk size differs')
                fraction=section_cache.candidate_fraction(manifests,start,end,width,cancel=cancel)
                # Conservative heuristic from the baseline, not a universal crossover.
                if fraction>.35:reason=f'broad query ({fraction:.0%} candidate coverage)'
                else:
                    result=section_cache.extract(caches,start,end,width,limit=limit,cancel=cancel,progress=progress)
                    return result,'Spatial cache'
        except InterruptedError:raise
        except CacheBusy:reason='cache busy'
        except FileNotFoundError:reason='no complete cache for these inputs; use Build section cache'
        except (OSError,ValueError,KeyError,TypeError,IndexError):
            reason='cache unavailable or invalid; rebuild when convenient'
        section_cache.check_cancel(cancel)
        progress('Full scan — '+reason)
        result=extract_section(paths,start,end,width,limit=limit,cancel=cancel,progress=progress)
        return result,'Full scan — '+reason
