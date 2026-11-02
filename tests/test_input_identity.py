import os
import pytest
from pyargus.job_manifest import identity


def test_small_control_edit_with_preserved_size_and_mtime_changes_identity(tmp_path):
    path = tmp_path/'control.csv';path.write_bytes(b'PID1,100,200,300')
    before = identity(path);stamp = path.stat()
    path.write_bytes(b'PID1,100,200,301')
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    after = identity(path)
    assert after['size_bytes'] == before['size_bytes']
    assert after['mtime_ns'] == before['mtime_ns']
    assert after['sha256'] != before['sha256']
    assert identity(path, hash_content=False)['identity_method'] == 'size_and_mtime'


def test_cloud_identity_remains_metadata_only(tmp_path):
    path = tmp_path/'flight.las';path.write_bytes(b'not a real cloud')
    assert identity(path)['identity_method'] == 'size_and_mtime'


def test_file_changed_while_hashed_refuses_identity(tmp_path, monkeypatch):
    from pathlib import Path
    path = tmp_path/'control.csv';path.write_text('a')
    real_open = Path.open
    def changed_open(file, *args, **kwargs):
        stream = real_open(file, *args, **kwargs)
        if file == path and args == ('rb',):
            with real_open(file, 'ab') as writer:writer.write(b'b')
        return stream
    monkeypatch.setattr(Path, 'open', changed_open)
    with pytest.raises(ValueError, match='changed while hashing'):identity(path)



def test_source_change_during_classification_readback_refuses_publication(tmp_path,monkeypatch):
    import laspy
    from pathlib import Path
    from pyargus.classify.recording import recorded_classification
    from tests.test_classification_recording import source
    src=source(tmp_path);out=tmp_path/'out.las'
    real_open=laspy.open
    def observed_open(path,*args,**kwargs):
        reader=real_open(path,*args,**kwargs)
        if '.pyargus-classify-' in str(path) and kwargs.get('mode','r')=='r':
            original=reader.chunk_iterator
            def chunks(size):
                yield from original(size)
                with Path(src).open('ab')as stream:stream.write(b'changed during verification')
            reader.chunk_iterator=chunks
        return reader
    monkeypatch.setattr(laspy,'open',observed_open)
    @recorded_classification
    def process(path,staged):
        data=laspy.read(path);data.write(staged)
        return dict(total=len(data.points))
    with pytest.raises(ValueError,match='changed during classification verification'):
        process(src,out)
    assert not out.exists()
