#!/usr/bin/env python3
"""Explicit browser-derivative preparation; never run by the serving entrypoint."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image
from objects import build_objects


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(data):
    out = data / 'browser-viewer'
    metadata = json.loads((data / 'front-geometry.json').read_text())
    derivation = metadata['derivation']
    for name, expected in [('front-original.heic', derivation['sourceSHA256']),
                           ('front-rectified.png', derivation['outputSHA256'])]:
        if digest(data / name) != expected:
            raise ValueError(f'Baseline hash mismatch: {name}')
    geo = json.loads((data / 'geotiff/manifest.json').read_text())
    tiff = data / 'geotiff/front-card.tif'
    if digest(tiff) != geo['output']['sha256']:
        raise ValueError('GeoTIFF hash mismatch')
    if geo['inputFiles']['front-rectified.png']['sha256'] != derivation['outputSHA256']:
        raise ValueError('GeoTIFF belongs to a different baseline')
    out.mkdir(exist_ok=True)
    with Image.open(tiff) as image:
        if image.mode != 'RGBA' or image.size != (derivation['outputPixelWidth'], derivation['outputPixelHeight']):
            raise ValueError('GeoTIFF raster mismatch')
        image.save(out / 'geotiff.png', icc_profile=image.info.get('icc_profile'))
        with Image.open(out / 'geotiff.png') as check:
            if not np.array_equal(np.array(image), np.array(check)):
                raise ValueError('GeoTIFF browser decode changed pixels')
    metadata['geoTIFFDisplay'] = {'sourceSHA256': digest(tiff),
                                  'displaySHA256': digest(out / 'geotiff.png'),
                                  'operation': 'Lossless RGBA decode to browser PNG; no resampling'}
    target = out / 'original.png'
    # Regenerate explicitly; no stale derivative reuse or alternate decoder.
    subprocess.run(['magick', str(data / 'front-original.heic'), '-auto-orient',
                    '-colorspace', 'sRGB', '-depth', '8', str(target)], check=True)
    size = subprocess.check_output(['magick', 'identify', '-format', '%w %h', str(target)], text=True)
    g = derivation['id1Geometry']
    if list(map(int, size.split())) != [g['sourcePixelWidth'], g['sourcePixelHeight']]:
        raise ValueError('Decoded orientation does not match geometry')
    metadata['viewerDerivation'] = {
        'sourceSHA256': derivation['sourceSHA256'], 'outputSHA256': digest(target),
        'decoder': subprocess.check_output(['magick', '-version'], text=True).splitlines()[0],
        'operation': 'Full-frame auto-orient; sRGB RGB8 display derivative; no resize',
        'pixelMeaning': 'Decoded display RGB; not raw sensor samples or HDR auxiliary data'}
    build_objects(metadata, out)
    (out / 'manifest.json').write_text(json.dumps(metadata, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True, type=Path)
    args = parser.parse_args()
    prepare(args.baseline.resolve(strict=True))
