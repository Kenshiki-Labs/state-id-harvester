"""Immutable native raster admission; hashes bind the exact admitted bytes.

Lineage checks establish consistency with retained manifests, not authenticity of
an image or credential. No resize, crop or interpolation path is provided.
"""
import hashlib
import io
import json
from json_contract import strict_json
from pathlib import Path

import numpy as np
from PIL import Image


SOURCE_NAMES = (
    'front-original.heic', 'front-geometry.json', 'front-rectified.png',
    'geotiff/front-card.tif', 'geotiff/manifest.json',
    'browser-viewer/original.png', 'browser-viewer/manifest.json',
    'browser-viewer/objects-mask.png', 'browser-viewer/objects.json',
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_unchanged(base, hashes):
    if any(sha(base / name) != value for name, value in hashes.items()):
        raise ValueError('Source changed during verification')


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def load_native(base):
    base = Path(base)
    # Parse and decode these snapshots, never a second read of an unhashed file.
    admitted = {name: (base / name).read_bytes() for name in SOURCE_NAMES}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in admitted.items()}
    try:
        meta = strict_json(admitted['front-geometry.json'])
        display = strict_json(admitted['browser-viewer/manifest.json'])
        tiff = strict_json(admitted['geotiff/manifest.json'])
        objects = strict_json(admitted['browser-viewer/objects.json'])
        derivation = meta['derivation']
        g = derivation['id1Geometry']
        _require(hashes['front-original.heic'] == derivation['sourceSHA256'],
                 'Original lineage mismatch')
        _require(hashes['front-rectified.png'] == derivation['outputSHA256'],
                 'Rectified lineage mismatch')
        _require(hashes['browser-viewer/original.png'] == display['viewerDerivation']['outputSHA256'],
                 'Decode hash mismatch')
        _require(hashes['front-original.heic'] == display['viewerDerivation']['sourceSHA256'],
                 'Decode lineage mismatch')
        for name in ('front-original.heic', 'front-rectified.png', 'front-geometry.json'):
            record = tiff['inputFiles'][name]
            _require(record['sha256'] == hashes[name] and record['bytes'] == len(admitted[name]),
                     'GeoTIFF input lineage mismatch')
        output = tiff['output']
        _require(output['file'] == 'front-card.tif' and
                 output['sha256'] == hashes['geotiff/front-card.tif'] and
                 output['bytes'] == len(admitted['geotiff/front-card.tif']),
                 'GeoTIFF output lineage mismatch')
        _require(output['width'] == derivation['outputPixelWidth'] and
                 output['height'] == derivation['outputPixelHeight'],
                 'GeoTIFF dimensions contradict retained geometry')
        _require(objects['sourceSHA256'] == hashes['front-original.heic'] and
                 objects['sourceCorners'] == g['sourceCorners'], 'Object lineage mismatch')
        _require(objects['mask']['file'] == 'objects-mask.png' and
                 objects['mask']['sha256'] == hashes['browser-viewer/objects-mask.png'],
                 'Object mask lineage mismatch')
        expected_coordinates = {'type': 'image_pixels', 'origin': 'top_left_edge',
                                'xDirection': 'right', 'yDirection': 'down',
                                'width': g['sourcePixelWidth'], 'height': g['sourcePixelHeight']}
        _require(objects['coordinateSystem'] == expected_coordinates,
                 'Object coordinate system mismatch')
        with Image.open(io.BytesIO(admitted['browser-viewer/original.png'])) as image:
            _require(image.mode == 'RGB', 'Expected RGB decode; conversion not permitted')
            pixels = np.array(image)
        _require(pixels.shape == (g['sourcePixelHeight'], g['sourcePixelWidth'], 3) and
                 pixels.dtype == np.uint8, 'Native raster dimensions/type mismatch')
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('Invalid retained source metadata') from error
    verify_unchanged(base, hashes)
    pixels.setflags(write=False)
    return pixels, meta, hashes
