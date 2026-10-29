"""Artifact-level tests: real source admission and polygon/mask comparison."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from rasterio.features import rasterize

from dataset import digest, json_bytes, package_boundary
from native_input import load_native


class BoundaryDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'baseline'
        self.run = self.root / 'run'
        self.out = self.root / 'dataset'
        (self.base / 'browser-viewer').mkdir(parents=True)
        (self.base / 'geotiff').mkdir()
        self.run.mkdir()
        for name in ['front-original.heic', 'front-rectified.png',
                     'geotiff/front-card.tif', 'geotiff/manifest.json',
                     'browser-viewer/objects-mask.png', 'browser-viewer/objects.json']:
            (self.base / name).write_bytes(b'retained-' + name.encode())
        rgb = np.arange(12 * 14 * 3, dtype=np.uint8).reshape(12, 14, 3)
        Image.fromarray(rgb).save(self.base / 'browser-viewer/original.png')
        source_hash = digest((self.base / 'front-original.heic').read_bytes())
        (self.base / 'front-geometry.json').write_bytes(json_bytes({
            'derivation': {'sourceSHA256': source_hash,
                           'outputSHA256': digest((self.base / 'front-rectified.png').read_bytes()),
                           'outputPixelWidth': 14, 'outputPixelHeight': 12,
                           'id1Geometry': {'sourcePixelWidth': 14, 'sourcePixelHeight': 12,
                                           'sourceCorners': [[2, 2], [11, 2], [11, 9], [2, 9]]}}}))
        (self.base / 'browser-viewer/manifest.json').write_bytes(json_bytes({
            'viewerDerivation': {'sourceSHA256': source_hash,
                                'outputSHA256': digest((self.base / 'browser-viewer/original.png').read_bytes())}}))
        (self.base / 'geotiff/manifest.json').write_bytes(json_bytes({
            'inputFiles': {name: {'sha256': digest((self.base / name).read_bytes()),
                                  'bytes': (self.base / name).stat().st_size}
                           for name in ('front-original.heic', 'front-rectified.png', 'front-geometry.json')},
            'output': {'file': 'front-card.tif',
                       'sha256': digest((self.base / 'geotiff/front-card.tif').read_bytes()),
                       'bytes': (self.base / 'geotiff/front-card.tif').stat().st_size,
                       'width': 14, 'height': 12}}))
        (self.base / 'browser-viewer/objects.json').write_bytes(json_bytes({
            'sourceSHA256': source_hash,
            'sourceCorners': [[2, 2], [11, 2], [11, 9], [2, 9]],
            'coordinateSystem': {'type': 'image_pixels', 'origin': 'top_left_edge',
                                 'xDirection': 'right', 'yDirection': 'down', 'width': 14, 'height': 12},
            'mask': {'file': 'objects-mask.png',
                     'sha256': digest((self.base / 'browser-viewer/objects-mask.png').read_bytes())}}))
        _, _, hashes = load_native(self.base)
        # Retain this deliberately non-minimal start vertex and hole order.
        geometry = {'type': 'Polygon', 'coordinates': [
            [[11., 9.], [2., 9.], [2., 2.], [11., 2.], [11., 9.]],
            [[5., 4.], [5., 6.], [8., 6.], [8., 4.], [5., 4.]]]}
        mask = rasterize([(geometry, 1)], out_shape=(12, 14), dtype='uint8')
        Image.fromarray(mask).save(self.run / 'candidate-mask.png')
        self.candidate = {
            'schemaVersion': 2, 'status': 'candidate', 'sourceHashes': hashes,
            'geometry': geometry, 'method': 'opencv_grabcut_auto_seeds',
            'parameters': {'workingResolution': 'native', 'workingExtent': 'full_frame', 'resampling': 'none'},
            'implementation': {'opencv': '4.12.0'}, 'diagnostics': {'holes': 1},
            'coordinateSystem': {'type': 'image_pixels', 'origin': 'top_left_edge',
                                 'xDirection': 'right', 'yDirection': 'down', 'width': 14, 'height': 12},
            'fidelity': {'workingExtent': 'full_frame', 'sourceSize': [14, 12],
                         'workingSize': [14, 12], 'sourcePixelsAdmitted': 168,
                         'workingToSourceAffine': [1, 0, 0, 0, 1, 0],
                         'sourceRGBSHA256': digest(rgb.tobytes()),
                         'workingRGBSHA256': digest(rgb.tobytes()),
                         'resampled': False, 'cropped': False, 'bgrRoundTripEqual': True}}
        self.save_candidate()
        (self.run / 'evaluation.json').write_bytes(b'untouched evaluation')

    def save_candidate(self):
        (self.run / 'candidate.json').write_bytes(json_bytes(self.candidate))

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for parent in [self.base, self.run] for p in parent.rglob('*') if p.is_file()}

    def test_preserves_geometry_holes_mask_and_sources(self):
        before = self.snapshot()
        manifest = package_boundary(self.base, self.run, self.out)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(json.loads((self.out / 'geometry.json').read_bytes()), self.candidate['geometry'])
        self.assertEqual((self.out / 'mask.png').read_bytes(), (self.run / 'candidate-mask.png').read_bytes())
        self.assertEqual(manifest['boundaryId'], digest((self.out / 'geometry.json').read_bytes()))
        self.assertEqual(manifest['rings'], [
            {'ringId': 'exterior', 'ringIndex': 0, 'role': 'exterior', 'lengthSourcePixels': 32.},
            {'ringId': 'interior-1', 'ringIndex': 1, 'role': 'interior', 'lengthSourcePixels': 10.}])
        self.assertEqual(json.loads((self.out / 'assessments.json').read_bytes()), {
            'schemaVersion': 1, 'boundaryId': manifest['boundaryId'], 'findings': []})
        for artifact in manifest['artifacts'].values():
            self.assertEqual(artifact['sha256'], digest((self.out / artifact['path']).read_bytes()))
        second = self.root / 'second'
        package_boundary(self.base, self.run, second)
        self.assertEqual({p.name: p.read_bytes() for p in self.out.iterdir()},
                         {p.name: p.read_bytes() for p in second.iterdir()})

    def test_rejects_source_tampering(self):
        (self.base / 'front-original.heic').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'lineage'):
            package_boundary(self.base, self.run, self.out)
        self.assertFalse(self.out.exists())

    def test_rejects_mask_tampering(self):
        with Image.open(self.run / 'candidate-mask.png') as im:
            mask = np.array(im)
        mask[0, 0] = 1
        Image.fromarray(mask).save(self.run / 'candidate-mask.png')
        with self.assertRaisesRegex(ValueError, 'mask/geometry mismatch'):
            package_boundary(self.base, self.run, self.out)
        self.assertFalse(self.out.exists())

    def test_rejects_geometry_tampering(self):
        self.candidate['geometry']['coordinates'][1][1][1] = 7.
        self.save_candidate()
        with self.assertRaisesRegex(ValueError, 'mask/geometry mismatch'):
            package_boundary(self.base, self.run, self.out)

    def test_rejects_false_native_provenance(self):
        for key, value in [('resampled', True), ('sourceSize', [7, 6]),
                           ('sourcePixelsAdmitted', 42), ('workingToSourceAffine', [2, 0, 0, 0, 2, 0]),
                           ('workingRGBSHA256', 'incorrect')]:
            with self.subTest(key=key):
                original = self.candidate['fidelity'][key]
                self.candidate['fidelity'][key] = value
                self.save_candidate()
                with self.assertRaises(ValueError):
                    package_boundary(self.base, self.run, self.out)
                self.assertFalse(self.out.exists())
                self.candidate['fidelity'][key] = original

    def test_rejects_contradictory_method_parameters(self):
        self.candidate['parameters']['resampling'] = 'linear'
        self.save_candidate()
        with self.assertRaisesRegex(ValueError, 'Method parameters'):
            package_boundary(self.base, self.run, self.out)
        self.assertFalse(self.out.exists())

    def test_existing_directory_is_not_overwritten(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):
            package_boundary(self.base, self.run, self.out)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_publication_failure_leaves_no_partial_dataset(self):
        with patch('publication.rename_no_replace', side_effect=OSError('publish failed')):
            with self.assertRaisesRegex(OSError, 'publish failed'):
                package_boundary(self.base, self.run, self.out)
        self.assertFalse(self.out.exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['.dataset.publish.lock', 'baseline', 'run'])


if __name__ == '__main__':
    unittest.main()
