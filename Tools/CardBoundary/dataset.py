"""Publish an immutable observed-boundary dataset from a verified native run.

This packages existing observations; it never reruns segmentation or changes
vertices. Ring distances follow their stored vertex order, starting at vertex 0.
"""
import argparse
import hashlib
import io
import json
from json_contract import strict_json
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio import Affine
from rasterio.features import rasterize
from shapely.geometry import LinearRing, box, shape

from native_input import load_native, sha
from publication import publish_directory


def json_bytes(value):
    """Stable UTF-8 JSON: sorted keys, compact separators, finite numbers, LF."""
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_boundary(base, run):
    """Independently verify input lineage and exact native polygon/mask parity."""
    candidate_bytes = (run / 'candidate.json').read_bytes()
    candidate = strict_json(candidate_bytes)
    if candidate.get('schemaVersion') != 2 or candidate.get('status') != 'candidate':
        raise ValueError('Expected completed native candidate schema 2')
    parameters = candidate['parameters']
    if (candidate['method'] != 'opencv_grabcut_auto_seeds' or
            parameters.get('workingResolution') != 'native' or
            parameters.get('workingExtent') != 'full_frame' or
            parameters.get('resampling') != 'none'):
        raise ValueError('Method parameters contradict native full-frame contract')
    pixels, _, hashes = load_native(base)
    if candidate['sourceHashes'] != hashes:
        raise ValueError('Source lineage mismatch')
    h, w = pixels.shape[:2]
    f = candidate['fidelity']
    if (f['resampled'] is not False or f['cropped'] is not False or
            f['workingExtent'] != 'full_frame' or f['sourceSize'] != [w, h] or
            f['workingSize'] != [w, h] or f['sourcePixelsAdmitted'] != w * h or
            f['workingToSourceAffine'] != [1, 0, 0, 0, 1, 0] or
            f['bgrRoundTripEqual'] is not True):
        raise ValueError('Candidate violates native full-frame contract')
    pixel_hash = digest(pixels.tobytes())
    if f['sourceRGBSHA256'] != pixel_hash or f['workingRGBSHA256'] != pixel_hash:
        raise ValueError('Native sample hash mismatch')
    expected_coordinates = {'type': 'image_pixels', 'origin': 'top_left_edge',
                            'xDirection': 'right', 'yDirection': 'down',
                            'width': w, 'height': h}
    if candidate['coordinateSystem'] != expected_coordinates:
        raise ValueError('Candidate coordinate system mismatch')
    geometry = candidate['geometry']
    # Serialize before GEOS admission to reject nonfinite JSON coordinates.
    json_bytes(geometry)
    polygon = shape(geometry)
    if (geometry['type'] != 'Polygon' or polygon.is_empty or
            not polygon.is_valid or not box(0, 0, w, h).covers(polygon)):
        raise ValueError('Expected valid contained Polygon')
    for ring in geometry['coordinates']:
        if len(ring) < 4 or ring[0] != ring[-1] or any(len(p) != 2 for p in ring):
            raise ValueError('Expected closed two-dimensional rings')
    mask_bytes = (run / 'candidate-mask.png').read_bytes()
    with Image.open(io.BytesIO(mask_bytes)) as image:
        if image.mode != 'L':
            raise ValueError('Expected single-band uint8 mask')
        mask = np.array(image)
    reconstructed = rasterize([(geometry, 1)], out_shape=(h, w),
                              transform=Affine.identity(), dtype='uint8',
                              all_touched=False)
    if not np.array_equal(mask, reconstructed):
        raise ValueError('Candidate mask/geometry mismatch')
    # Catch mutation during admission without rewriting any source/evaluation.
    if any(sha(base / name) != value for name, value in hashes.items()):
        raise ValueError('Source changed during verification')
    if ((run / 'candidate.json').read_bytes() != candidate_bytes or
            (run / 'candidate-mask.png').read_bytes() != mask_bytes):
        raise ValueError('Candidate changed during verification')
    return candidate, candidate_bytes, mask_bytes


def package_boundary(base, run, out):
    """Verify, stage, then atomically publish a new dataset directory.

An exclusive sibling lock serializes publishers targeting the same destination.
Existing destinations are never edited or overwritten.
"""
    base, run, out = Path(base), Path(run), Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError(out)
    candidate, candidate_bytes, mask_bytes = verify_boundary(base, run)
    geometry_bytes = json_bytes(candidate['geometry'])
    boundary_id = digest(geometry_bytes)
    assessment_bytes = json_bytes({'schemaVersion': 1, 'boundaryId': boundary_id,
                                   'findings': []})
    rings = []
    for index, coordinates in enumerate(candidate['geometry']['coordinates']):
        rings.append({'ringId': 'exterior' if index == 0 else f'interior-{index}',
                      'ringIndex': index,
                      'role': 'exterior' if index == 0 else 'interior',
                      'lengthSourcePixels': LinearRing(coordinates).length})
    manifest = {'schemaVersion': 1, 'type': 'id_cadastral_boundary',
                'boundaryId': boundary_id,
                **{key: candidate[key] for key in
                   ('coordinateSystem', 'sourceHashes', 'fidelity', 'method',
                    'parameters', 'implementation', 'diagnostics')},
                'artifacts': {
                    'geometry': {'path': 'geometry.json', 'sha256': boundary_id},
                    'mask': {'path': 'mask.png', 'sha256': digest(mask_bytes)},
                    'assessments': {'path': 'assessments.json',
                                    'sha256': digest(assessment_bytes)}},
                'rings': rings,
                'provenance': {'candidateSHA256': digest(candidate_bytes)},
                'verification': {'polygonMaskRoundTrip': True,
                                 'geometryUnchanged': True}}
    files = {'geometry.json': geometry_bytes, 'mask.png': mask_bytes,
             'assessments.json': assessment_bytes, 'manifest.json': json_bytes(manifest)}
    publish_directory(out, files)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate_directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = package_boundary(args.baseline, args.candidate_directory, args.output)
    print(json.dumps({'boundaryId': result['boundaryId'], 'output': str(args.output)}))
