"""Hash-bound immutable EdgeDrawing candidate dataset admission."""
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
sys.path.append(str(Path(__file__).resolve().parents[1] / 'CardBoundary'))
from json_contract import strict_json
from publication import publish_directory

NAMES = ('points.npy', 'offsets.npy', 'chains.json')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()

def npy_bytes(array):
    stream = io.BytesIO()
    np.save(stream, array, allow_pickle=False)
    return stream.getvalue()

def chain_records(points, offsets):
    records = []
    for i, (start, end) in enumerate(zip(offsets[:-1], offsets[1:])):
        p = points[start:end]
        records.append({'chainId': 'edge-' + str(i), 'pointCount': len(p),
                        'bounds': dict(zip(('minX', 'minY', 'maxX', 'maxY'),
                                           map(int, (*p.min(axis=0), *p.max(axis=0))))),
                        'lengthSourcePixels': float(np.linalg.norm(np.diff(p.astype(float), axis=0), axis=1).sum())})
    return records

def validate_files(files, source_hashes=None):
    manifest = strict_json(files['manifest.json'])
    if type(manifest.get('schemaVersion')) is not int or manifest.get('schemaVersion') != 1 or manifest.get('type') != 'id_cadastral_edge_candidates':
        raise ValueError('Unsupported edge dataset')
    if source_hashes is not None and manifest.get('sourceHashes') != source_hashes:
        raise ValueError('Edge source identity mismatch')
    hashes = manifest.get('sourceHashes')
    if not isinstance(hashes, dict) or not hashes or any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v) for v in hashes.values()):
        raise ValueError('Invalid source hashes')
    coords = manifest['coordinateSystem']
    w, h = coords['width'], coords['height']
    if type(w) is not int or type(h) is not int or min(w, h) < 1:
        raise ValueError('Invalid raster dimensions')
    if coords != {'type': 'image_pixel_indices', 'origin': 'top_left', 'xDirection': 'right', 'yDirection': 'down', 'width': w, 'height': h, 'pixelCenterOffset': [0.5, 0.5]}:
        raise ValueError('Unsupported edge coordinates')
    if set(manifest['artifacts']) != set(NAMES):
        raise ValueError('Unexpected artifacts')
    for name in NAMES:
        if manifest['artifacts'][name] != {'sha256': digest(files[name]), 'bytes': len(files[name])}:
            raise ValueError('Edge artifact mismatch: ' + name)
    expected_parameters = strict_json(Path(__file__).with_name('config.json').read_bytes())['parameters']
    if manifest.get('method') != 'opencv_ximgproc_EdgeDrawing' or manifest.get('parameters') != expected_parameters:
        raise ValueError('Unsupported edge method or parameters')
    expected_processing = {'width': w, 'height': h, 'resize': False, 'crop': False, 'anchorScanInterval': 1, 'anchorBorderExcludedPixels': 2, 'grayscale': 'OpenCV COLOR_RGB2GRAY', 'gaussianKernel': [5, 5], 'chainSimplification': False, 'threads': 1}
    if manifest.get('processing') != expected_processing:
        raise ValueError('Unsupported processing fidelity')
    for name in ('points.npy', 'offsets.npy'):
        stream = io.BytesIO(files[name])
        if np.lib.format.read_magic(stream) != (1, 0):
            raise ValueError('Expected NPY v1')
        _, fortran, _ = np.lib.format.read_array_header_1_0(stream)
        if fortran:
            raise ValueError('Expected C-order array')
    points = np.load(io.BytesIO(files['points.npy']), allow_pickle=False)
    offsets = np.load(io.BytesIO(files['offsets.npy']), allow_pickle=False)
    if points.dtype != np.dtype('<i4') or points.ndim != 2 or points.shape[1] != 2:
        raise ValueError('Invalid edge points')
    if offsets.dtype != np.dtype('<i8') or offsets.ndim != 1 or len(offsets) < 1 or offsets[0] != 0 or offsets[-1] != len(points) or np.any(offsets < 0) or np.any(offsets > len(points)) or np.any(offsets[1:] <= offsets[:-1]):
        raise ValueError('Invalid chain offsets')
    if len(points) and (np.any(points < 0) or np.any(points[:, 0] >= w) or np.any(points[:, 1] >= h)):
        raise ValueError('Point outside source raster')
    records = strict_json(files['chains.json'])
    if records != chain_records(points, offsets):
        raise ValueError('Chain metadata mismatch')
    for start, end in zip(offsets[:-1], offsets[1:]):
        if np.any(np.abs(np.diff(points[start:end], axis=0)) > 1):
            raise ValueError('Disconnected chain')
    if manifest.get('chainCount') != len(records) or manifest.get('pointCount') != len(points):
        raise ValueError('Incorrect edge counts')
    points.setflags(write=False)
    offsets.setflags(write=False)
    return manifest, points, offsets, records, files

def load_dataset(path, source_hashes=None):
    path = Path(path)
    if path.is_symlink() or any((path / name).is_symlink() for name in ('manifest.json', *NAMES)):
        raise ValueError('Symlink edge artifacts not admitted')
    files = {name: (path / name).read_bytes() for name in ('manifest.json', *NAMES)}
    return validate_files(files, source_hashes)

def package(out, manifest, points, offsets):
    files = {'points.npy': npy_bytes(points), 'offsets.npy': npy_bytes(offsets),
             'chains.json': json_bytes(chain_records(points, offsets))}
    manifest = dict(manifest, chainCount=len(offsets)-1, pointCount=len(points),
                    artifacts={name: {'sha256': digest(data), 'bytes': len(data)} for name, data in files.items()})
    files['manifest.json'] = json_bytes(manifest)
    validate_files(files, manifest['sourceHashes'])
    publish_directory(out, files)
    return manifest
