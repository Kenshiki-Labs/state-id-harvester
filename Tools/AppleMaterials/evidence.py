"""Shared host evidence admission and publication, reusing boundary primitives."""
from contextlib import contextmanager
import hashlib
import io
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'CardBoundary'))
from json_contract import require, strict_json
from publication import rename_no_replace, PublicationDurabilityError


@contextmanager
def open_regular(path):
    path=Path(path)
    require(not path.is_symlink(), 'Artifact symlink is not permitted')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'Expected regular artifact: '+path.name)
        yield stream


def read_regular(path):
    with open_regular(path) as stream:return stream.read()


def digest(path):
    with open_regular(path) as stream:
        value=hashlib.sha256()
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
        return value.hexdigest()


def plain_name(name):
    require(isinstance(name, str) and name not in ('', '.', '..') and
            Path(name).name == name and '/' not in name and '\\' not in name,
            'Artifact name must be a plain filename')
    return name


def read_manifest(root, name='manifest.json'):
    path=Path(root)/plain_name(name)
    require(not path.is_symlink(), 'Manifest symlink is not permitted')
    return strict_json(read_regular(path))


def verify_file(path, expected):
    path=Path(path)
    require(not path.is_symlink() and path.is_file(), f'Expected regular artifact: {path.name}')
    require(isinstance(expected,str) and len(expected)==64, 'Invalid SHA256')
    require(digest(path)==expected, f'Artifact hash mismatch: {path.name}')


@contextmanager
def snapshot(root, manifest, names, manifest_name='manifest.json'):
    """Copy admitted files once; downstream reads private verified snapshots."""
    root=Path(root)
    plain_name(manifest_name)
    require(not root.is_symlink() and not (root/manifest_name).is_symlink(), 'Snapshot symlinks are not permitted')
    with tempfile.TemporaryDirectory(prefix='cadastral-admitted-') as tmp:
        target=Path(tmp)
        raw=read_regular(root/manifest_name)
        require(strict_json(raw)==manifest, 'Manifest changed before admission')
        (target/manifest_name).write_bytes(raw)
        for name in names:
            plain_name(name)
            expected=manifest['artifacts'][name]
            if isinstance(expected,dict): expected=expected['sha256']
            original=root/name
            require(not original.is_symlink(), 'Artifact symlink is not permitted')
            with open_regular(original) as src, (target/name).open('xb') as dst:
                shutil.copyfileobj(src,dst,1024*1024)
            verify_file(target/name,expected)
        require(read_regular(root/manifest_name)==raw, 'Manifest changed during admission')
        yield target


def read_rgb(path, expected):
    from PIL import Image
    import numpy as np
    require(not Path(path).is_symlink(), 'Source symlink is not permitted')
    raw=read_regular(path)
    require(hashlib.sha256(raw).hexdigest()==expected, 'Source hash mismatch')
    with Image.open(io.BytesIO(raw)) as image:
        require(image.mode=='RGB' and image.getexif().get(274,1)==1, 'Expected upright native RGB')
        return np.asarray(image).copy()


def publish_staged(staging, output):
    """Publish files already produced on disk using the existing no-replace primitive."""
    staging,output=Path(staging),Path(output)
    require(staging.is_dir(), 'Missing staging directory')
    for path in staging.iterdir():
        require(path.is_file() and not path.is_symlink(), 'Invalid staged artifact')
        with path.open('rb') as f: os.fsync(f.fileno())
    stage_fd=os.open(staging,os.O_RDONLY|os.O_DIRECTORY)
    destination_fd=os.open(output.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(stage_fd)
        # Staging is deliberately nested in a private temporary directory;
        # rename_no_replace uses one parent fd, so address it relative to output parent.
        relative=os.path.relpath(staging,output.parent)
        rename_no_replace(destination_fd,relative,output.name)
        try:
            os.fsync(destination_fd)
        except OSError as error:
            raise PublicationDurabilityError(f'Complete dataset published at {output}; directory durability unconfirmed') from error
    finally:
        os.close(stage_fd);os.close(destination_fd)
