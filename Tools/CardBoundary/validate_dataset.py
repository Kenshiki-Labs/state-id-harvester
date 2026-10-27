"""Strict admission of boundary dataset v1; no unsupported findings or fallback."""
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio import Affine
from rasterio.features import rasterize
from shapely.geometry import LinearRing, box, shape
from native_input import load_native
from json_contract import strict_json


def require(value, message):
    if not value:
        raise ValueError(message)



def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate_dataset(directory, baseline):
    """Read and validate all artifacts and source lineage, including raster parity.

    This interface returns the manifest only after all checks pass. Callers that
    retain bytes for serving must recheck those bytes against the returned hashes.
    """
    directory, baseline = Path(directory), Path(baseline)
    manifest_path = directory / 'manifest.json'
    require(not manifest_path.is_symlink(), 'Manifest symlink is not supported')
    original_manifest = manifest_path.read_bytes()
    m = strict_json(original_manifest)
    require(type(m) is dict and type(m.get('schemaVersion')) is int and
            m['schemaVersion'] == 1 and m.get('type') == 'id_cadastral_boundary', 'Unsupported dataset schema')
    artifacts = m.get('artifacts')
    require(type(artifacts) is dict and set(artifacts) == {'geometry', 'mask', 'assessments'}, 'Artifact set mismatch')
    data = {}
    for name, expected in [('geometry', 'geometry.json'), ('mask', 'mask.png'), ('assessments', 'assessments.json')]:
        entry = artifacts[name]
        require(type(entry) is dict and entry.get('path') == expected, 'Artifact path mismatch')
        path = directory / expected
        require(not path.is_symlink(), 'Artifact symlink is not supported')
        data[name] = path.read_bytes()
        require(sha(data[name]) == entry.get('sha256'), 'Artifact hash mismatch: ' + name)
    require(m.get('boundaryId') == sha(data['geometry']), 'Boundary identity mismatch')
    pixels, _, source_hashes = load_native(baseline)
    require(m.get('sourceHashes') == source_hashes, 'Dataset source lineage mismatch')
    h, w = pixels.shape[:2]
    require(m.get('coordinateSystem') == {'type':'image_pixels','origin':'top_left_edge',
            'xDirection':'right','yDirection':'down','width':w,'height':h}, 'Coordinate system mismatch')
    f = m.get('fidelity', {})
    require(type(f) is dict and f.get('workingExtent') == 'full_frame' and
            f.get('resampled') is False and f.get('cropped') is False and
            f.get('bgrRoundTripEqual') is True and f.get('sourceSize') == [w,h] and
            f.get('workingSize') == [w,h] and type(f.get('sourcePixelsAdmitted')) is int and
            f['sourcePixelsAdmitted'] == w*h and f.get('workingToSourceAffine') == [1,0,0,0,1,0], 'Native fidelity mismatch')
    pixel_hash = sha(pixels.tobytes())
    require(f.get('sourceRGBSHA256') == pixel_hash == f.get('workingRGBSHA256'), 'Native samples mismatch')
    p = m.get('parameters', {})
    require(type(p) is dict and m.get('method') == 'opencv_grabcut_auto_seeds' and
            p.get('workingResolution') == 'native' and p.get('workingExtent') == 'full_frame' and
            p.get('resampling') == 'none', 'Method mismatch')
    require(number(p.get('seedBandFractionOfShortEdge')) and 0 < p['seedBandFractionOfShortEdge'] < .5 and
            type(p.get('iterations')) is int and p['iterations'] == 5 and
            type(p.get('rngSeed')) is int and p['rngSeed'] == 0 and
            type(p.get('threads')) is int and p['threads'] == 1, 'Unsupported method parameters')
    implementation = m.get('implementation')
    require(type(implementation) is dict and all(type(implementation.get(k)) is str and implementation[k]
            for k in ['opencv','rasterio','gdal','shapely','geos','scriptSHA256','nativeInputSHA256']), 'Implementation provenance missing')
    provenance = m.get('provenance', {})
    candidate_hash = provenance.get('candidateSHA256') if type(provenance) is dict else None
    require(type(candidate_hash) is str and len(candidate_hash) == 64 and all(c in '0123456789abcdef' for c in candidate_hash), 'Candidate provenance missing')
    require(m.get('verification') == {'polygonMaskRoundTrip':True,'geometryUnchanged':True}, 'Verification missing')
    geometry = strict_json(data['geometry'])
    require(type(geometry) is dict and geometry.get('type') == 'Polygon', 'Expected Polygon')
    rings = geometry.get('coordinates')
    require(type(rings) is list and len(rings) > 0, 'Missing rings')
    metadata = m.get('rings')
    require(type(metadata) is list and len(metadata) == len(rings), 'Ring metadata count mismatch')
    for index, ring in enumerate(rings):
        require(type(ring) is list and len(ring) >= 4, 'Short ring')
        require(all(type(point) is list and len(point) == 2 and all(number(v) for v in point)
                    for point in ring), 'Invalid ring coordinates')
        require(ring[0] == ring[-1], 'Open ring')
        require(all(0 <= x <= w and 0 <= y <= h for x,y in ring), 'Ring outside image')
        r = metadata[index]
        require(type(r) is dict and r.get('ringId') == ('exterior' if index == 0 else f'interior-{index}') and
                type(r.get('ringIndex')) is int and r['ringIndex'] == index and
                r.get('role') == ('exterior' if index == 0 else 'interior') and
                number(r.get('lengthSourcePixels')) and
                math.isclose(r['lengthSourcePixels'], LinearRing(ring).length, rel_tol=1e-12, abs_tol=1e-9), 'Ring metadata mismatch')
    polygon = shape(geometry)
    require(polygon.is_valid and not polygon.is_empty and box(0,0,w,h).covers(polygon), 'Invalid polygon topology')
    with Image.open(io.BytesIO(data['mask'])) as image:
        require(image.mode == 'L' and image.size == (w,h), 'Mask format mismatch')
        mask = np.array(image)
    expected_mask = rasterize([(geometry,1)], out_shape=(h,w), transform=Affine.identity(), dtype='uint8')
    require(np.array_equal(mask, expected_mask), 'Mask geometry mismatch')
    assessments = strict_json(data['assessments'])
    require(type(assessments) is dict and type(assessments.get('schemaVersion')) is int and
            assessments['schemaVersion'] == 1 and assessments.get('boundaryId') == m['boundaryId'] and
            assessments.get('findings') == [], 'Unsupported assessments; v1 admission supports empty findings')
    require(manifest_path.read_bytes() == original_manifest, 'Manifest changed during admission')
    for name, entry in artifacts.items():
        require((directory / entry['path']).read_bytes() == data[name], 'Artifact changed during admission')
    return m
