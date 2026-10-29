import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from detect import detect_native, CONFIG
from dataset import package, load_dataset, validate_files, json_bytes, digest, npy_bytes

class EdgeTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text())
        self.rgb = np.full((128, 160, 3), 220, np.uint8)
        self.rgb[:, 40:80] = 90
        self.rgb[:, 100:] = 140
        self.manifest = {'schemaVersion': 1, 'type': 'id_cadastral_edge_candidates',
                         'sourceHashes': {'original': 'a'*64},
                         'coordinateSystem': {'type': 'image_pixel_indices', 'origin': 'top_left', 'xDirection': 'right', 'yDirection': 'down', 'width': 160, 'height': 128, 'pixelCenterOffset': [0.5, 0.5]}}
        self.manifest['method'] = 'opencv_ximgproc_EdgeDrawing'
        self.manifest['parameters'] = self.config['parameters']
        self.manifest['processing'] = {'width': 160, 'height': 128, 'resize': False, 'crop': False, 'anchorScanInterval': 1, 'anchorBorderExcludedPixels': 2, 'grayscale': 'OpenCV COLOR_RGB2GRAY', 'gaussianKernel': [5, 5], 'chainSimplification': False, 'threads': 1}
    def packaged(self, out):
        p, o = detect_native(self.rgb, self.config)
        package(out, self.manifest, p, o)
        return load_dataset(out, self.manifest['sourceHashes'])
    def test_adjacent_transitions_deterministic_native(self):
        original = self.rgb.copy()
        p, o = detect_native(self.rgb, self.config)
        q, z = detect_native(self.rgb, self.config)
        np.testing.assert_array_equal(p, q)
        np.testing.assert_array_equal(o, z)
        np.testing.assert_array_equal(self.rgb, original)
        xs = p[p[:, 1] == 64, 0]
        for expected in (40, 80, 100):
            self.assertTrue(np.any(abs(xs - expected) <= 1))
    def test_empty_scene(self):
        p, o = detect_native(np.zeros_like(self.rgb), self.config)
        self.assertEqual(p.shape, (0, 2))
        self.assertEqual(o.tolist(), [0])
    def test_snapshot_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'edges'
            m, p, o, records, files = self.packaged(out)
            self.assertFalse(p.flags.writeable)
            self.assertFalse(o.flags.writeable)
            self.assertEqual(len(records), len(o)-1)
            (out/'points.npy').write_bytes(b'tampered')
            validate_files(files)
            with self.assertRaises(ValueError): load_dataset(out)
            with self.assertRaises(FileExistsError): package(out, self.manifest, p, o)
    def test_identity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'edges'
            self.packaged(out)
            with self.assertRaises(ValueError): load_dataset(out, {'wrong': 'b'*64})
    def test_rehashed_bounds_and_offsets_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, points, offsets, _, original = self.packaged(Path(tmp)/'edges')
            for name, array in [('points.npy', points.copy()), ('offsets.npy', offsets.copy())]:
                files = dict(original)
                if name == 'points.npy': array[0, 0] = -1
                else: array[1] = -2
                files[name] = npy_bytes(array)
                m = json.loads(files['manifest.json'])
                m['artifacts'][name] = {'sha256': digest(files[name]), 'bytes': len(files[name])}
                files['manifest.json'] = json_bytes(m)
                with self.assertRaises(ValueError): validate_files(files)
    def test_rehashed_method_and_fidelity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            *_, files = self.packaged(Path(tmp)/'edges')
            for key, value in [('method', 'other'), ('schemaVersion', True), ('processing', {})]:
                changed = dict(files)
                manifest = json.loads(files['manifest.json'])
                manifest[key] = value
                changed['manifest.json'] = json_bytes(manifest)
                with self.assertRaises(ValueError): validate_files(changed)
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'edges'
            self.packaged(out)
            alias = Path(tmp)/'alias'
            alias.symlink_to(out, target_is_directory=True)
            with self.assertRaises(ValueError): load_dataset(alias)
    def test_short_and_empty_chain_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, (points, offsets) in enumerate([
                (np.array([[4, 5]], dtype='<i4'), np.array([0, 1], dtype='<i8')),
                (np.empty((0, 2), dtype='<i4'), np.array([0], dtype='<i8'))]):
                out = Path(tmp)/str(i)
                package(out, self.manifest, points, offsets)
                _, p, o, _, _ = load_dataset(out)
                np.testing.assert_array_equal(points, p)
                np.testing.assert_array_equal(offsets, o)
    def test_config_skip_rejected(self):
        self.config['parameters']['ScanInterval'] = 2
        with self.assertRaises(ValueError): detect_native(self.rgb, self.config)

if __name__ == '__main__': unittest.main()
