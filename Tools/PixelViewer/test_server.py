"""Admission and HTTP tests. Dataset semantic validation has its own test suite."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import serve


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Request:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, mode, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


class QuietHandler(serve.Handler):
    def log_message(self, *args):
        pass


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.baseline = Path(self.temp.name) / 'baseline'
        self.boundary = Path(self.temp.name) / 'boundary'
        self.out = self.baseline / 'browser-viewer'
        self.out.mkdir(parents=True)
        self.boundary.mkdir()
        (self.baseline / 'geotiff').mkdir()
        self.write(self.out / 'original.png', b'original')
        self.write(self.baseline / 'front-original.heic', b'heic')
        self.write(self.out / 'geotiff.png', b'geotiff display')
        self.write(self.out / 'objects-mask.png', b'objects mask')
        self.write(self.baseline / 'geotiff/front-card.tif', b'tiff')
        self.write(self.out / 'objects.json', {'mask': {'sha256': sha(b'objects mask')}})
        self.write(self.baseline / 'geotiff/manifest.json', {'output': {'sha256': sha(b'tiff')}})
        self.write(self.out / 'manifest.json', {
            'derivation': {'sourceSHA256': sha(b'heic')},
            'viewerDerivation': {'outputSHA256': sha(b'original')},
            'geoTIFFDisplay': {'sourceSHA256': sha(b'tiff'), 'displaySHA256': sha(b'geotiff display')}})
        artifacts = {}
        for name in ['geometry', 'mask', 'assessments']:
            filename = name + ('.png' if name == 'mask' else '.json')
            self.write(self.boundary / filename, name.encode())
            artifacts[name] = {'path': filename, 'sha256': sha(name.encode())}
        source_hashes = {'front-original.heic': sha(b'heic')}
        for path in self.baseline.rglob('*'):
            if path.is_file():
                source_hashes[str(path.relative_to(self.baseline))] = sha(path.read_bytes())
        self.manifest = {'sourceHashes': source_hashes, 'artifacts': artifacts}
        self.write(self.boundary / 'manifest.json', self.manifest)
        self.validator = patch.object(serve, 'validate_dataset', return_value=self.manifest).start()
        self.addCleanup(patch.stopall)

    def write(self, path, value):
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())


    def rectification_fixture(self):
        from PIL import Image
        self.rectification = Path(self.temp.name) / 'rectification'
        self.rectification.mkdir()
        polygon = {'type': 'Polygon', 'coordinates': [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
        self.manifest['boundaryId'] = 'd' * 64
        matrix = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        manifest = {'schemaVersion': 1, 'type': 'id_cadastral_rectification', 'boundaryId': self.manifest['boundaryId'], 'sourceHashes': self.manifest['sourceHashes'], 'output': {'width': 3, 'height': 3, 'pixelsPerMillimeter': 1, 'originCardMillimeters': [0, 0]}, 'transforms': {key: matrix[:] for key in ['sourceToRectified', 'rectifiedToSource', 'sourceToCardMillimeters', 'cardMillimetersToSource']}, 'artifacts': {}}
        Image.new('RGB', (3, 3)).save(self.rectification / 'rectified.png')
        self.write(self.rectification / 'contour.json', polygon)
        self.write(self.rectification / 'residuals.npz', b'residuals')
        for key, name in [('image', 'rectified.png'), ('contour', 'contour.json'), ('residuals', 'residuals.npz')]:
            manifest['artifacts'][key] = {'path': name, 'sha256': sha((self.rectification / name).read_bytes())}
        self.write(self.rectification / 'manifest.json', manifest)
        return manifest, polygon

    def test_rectification_snapshot_retains_verified_bytes(self):
        manifest, polygon = self.rectification_fixture()
        snapshot = serve.rectification_snapshot(self.rectification, self.manifest, polygon)
        retained = snapshot['/rectification-rectified.png'][0]
        self.write(self.rectification / 'rectified.png', b'changed')
        self.assertEqual(snapshot['/rectification-rectified.png'][0], retained)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            serve.rectification_snapshot(self.rectification, self.manifest, polygon)

    def test_rectification_rejects_semantic_mismatches(self):
        import copy
        manifest, polygon = self.rectification_fixture()
        for mutation in [lambda m: m.update(boundaryId='wrong'), lambda m: m['output'].update(width=4), lambda m: m['transforms']['rectifiedToSource'].__setitem__(2, 1), lambda m: m['artifacts']['image'].update(path='../image.png'), lambda m: m['output'].update(originCardMillimeters=[1, 0])]:
            value = copy.deepcopy(manifest)
            mutation(value)
            self.write(self.rectification / 'manifest.json', value)
            with self.assertRaises(ValueError):
                serve.rectification_snapshot(self.rectification, self.manifest, polygon)
        self.write(self.rectification / 'manifest.json', manifest)
        polygon['coordinates'][0][1][0] = 1
        with self.assertRaisesRegex(ValueError, 'contour mismatch'):
            serve.rectification_snapshot(self.rectification, self.manifest, polygon)

    def test_edge_snapshot_hash_lineage_and_immutability(self):
        import numpy as np
        import sys
        sys.path.insert(0, str(serve.WEB.parent))
        from CardEdges import dataset
        directory = Path(self.temp.name) / 'edges'
        directory.mkdir()
        points = np.array([[0, 0], [1, 0], [1, 1]], dtype='<i4')
        offsets = np.array([0, 3], dtype='<i8')
        manifest = {'schemaVersion': 1, 'type': 'id_cadastral_edge_candidates',
                    'sourceHashes': self.manifest['sourceHashes'], 'chainCount': 1, 'pointCount': 3,
                    'coordinateSystem': {'type': 'image_pixel_indices', 'origin': 'top_left',
                        'xDirection': 'right', 'yDirection': 'down', 'width': 2, 'height': 2,
                        'pixelCenterOffset': [0.5, 0.5]}}
        manifest['method'] = 'opencv_ximgproc_EdgeDrawing'
        manifest['parameters'] = json.loads(Path(dataset.__file__).with_name('config.json').read_text())['parameters']
        manifest['processing'] = {'width': 2, 'height': 2, 'resize': False, 'crop': False,
            'anchorScanInterval': 1, 'anchorBorderExcludedPixels': 2,
            'grayscale': 'OpenCV COLOR_RGB2GRAY', 'gaussianKernel': [5, 5],
            'chainSimplification': False, 'threads': 1}
        files = {'points.npy': dataset.npy_bytes(points), 'offsets.npy': dataset.npy_bytes(offsets),
                 'chains.json': dataset.json_bytes(dataset.chain_records(points, offsets))}
        manifest['artifacts'] = {name: {'sha256': sha(value), 'bytes': len(value)} for name, value in files.items()}
        files['manifest.json'] = dataset.json_bytes(manifest)
        for name, value in files.items():
            self.write(directory / name, value)
        snapshot = serve.snapshot_files(self.baseline, self.boundary, edges=directory)
        self.assertTrue(json.loads(snapshot['/viewer-config.json'][0])['edgesAvailable'])
        self.assertEqual(snapshot['/edges-points.npy'][0], files['points.npy'])
        with self.assertRaisesRegex(ValueError, 'source identity'):
            serve.edge_snapshot(directory, {'front-original.heic': '0' * 64})
        self.write(directory / 'points.npy', b'corrupt')
        self.assertEqual(snapshot['/edges-points.npy'][0], files['points.npy'])
        with self.assertRaisesRegex(ValueError, 'artifact mismatch'):
            serve.edge_snapshot(directory, self.manifest['sourceHashes'])

    def test_topology_snapshot_lineage_hash_routes_and_immutability(self):
        import sys
        import numpy as np
        import shapely
        sys.path.insert(0, str(serve.WEB.parent))
        from CardTopology.audit import audit
        from CardEdges.dataset import npy_bytes, json_bytes
        directory = Path(self.temp.name) / 'topology'
        directory.mkdir()
        arrays, regions, summary, extras = audit(np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], dtype=np.int32), np.array([0, 5]))
        files = {key + '.npy': npy_bytes(value) for key, value in arrays.items()}
        files.update({'regions.geojson': json_bytes(regions), 'topology.json': json_bytes(summary)})
        files.update({key + '.wkb': shapely.to_wkb(value) for key, value in extras.items()})
        manifest = {'schemaVersion': 1, 'type': 'id_cadastral_edge_topology',
                    'sourceHashes': self.manifest['sourceHashes'], 'edgeManifestSHA256': 'e' * 64,
                    'method': {'noding':'shapely.node','components':'scipy.sparse.csgraph.connected_components','faces':'shapely.polygonize_full','intersectionPolicy':'exact_geometric','gapBridging':False,'snapping':False,'simplification':False,'downsampling':False},
                    'coordinateSystem': {'type': 'image_pixel_indices', 'origin': 'top_left',
                        'xDirection': 'right', 'yDirection': 'down', 'width': 2, 'height': 2,
                        'pixelCenterOffset': [.5, .5]}, 'summary': summary,
                    'artifacts': {name: {'sha256': sha(value), 'bytes': len(value)} for name, value in files.items()}}
        files['manifest.json'] = json_bytes(manifest)
        for name, value in files.items():
            self.write(directory / name, value)
        snapshot = serve.snapshot_files(self.baseline, self.boundary, topology=directory)
        self.assertTrue(json.loads(snapshot['/viewer-config.json'][0])['topologyAvailable'])
        self.assertEqual(snapshot['/topology-nodes.npy'][0], files['nodes.npy'])
        with self.assertRaisesRegex(ValueError, 'Source mismatch'):
            serve.topology_snapshot(directory, {})
        with self.assertRaisesRegex(ValueError, 'Edge lineage mismatch'):
            serve.topology_snapshot(directory, self.manifest['sourceHashes'], 'f' * 64)
        server = SimpleNamespace(server_address=('127.0.0.1', 9911), snapshot=snapshot)
        for path, code in [('/topology-nodes.npy', 200), ('/topology-regions.geojson', 200), ('/topology-../manifest.json', 404)]:
            request = Request(f'GET {path} HTTP/1.1\r\nHost: localhost:9911\r\n\r\n'.encode())
            QuietHandler(request, ('127.0.0.1', 1234), server)
            self.assertIn(f' {code} '.encode(), request.output.split(b'\r\n')[0])
        self.write(directory / 'nodes.npy', b'corrupt')
        self.assertEqual(snapshot['/topology-nodes.npy'][0], files['nodes.npy'])
        with self.assertRaisesRegex(ValueError, 'Topology artifact mismatch'):
            serve.topology_snapshot(directory, self.manifest['sourceHashes'])

    def test_required_configuration(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for argv in [[], ['--baseline', 'b'], ['--baseline', 'b', '--boundary', 'd', '--port', '0'], ['--baseline', 'b', '--boundary', 'd', '--port', '65536'], ['--baseline', 'b', '--boundary', 'd', '--prepare']]:
                with self.assertRaises(SystemExit):
                    serve.parse_args(argv)
        args = serve.parse_args(['--baseline', 'b', '--boundary', 'd', '--port', '9911'])
        self.assertEqual(args.port, 9911)

    def test_snapshot_immutable_after_disk_mutation(self):
        snapshot = serve.snapshot_files(self.baseline, self.boundary)
        self.write(self.boundary / 'geometry.json', b'changed')
        self.assertEqual(snapshot['/boundary-geometry.json'][0], b'geometry')
        with self.assertRaises(TypeError):
            snapshot['/boundary-geometry.json'] = (b'changed', 'application/json')
        self.assertEqual(self.validator.call_count, 2)

    def test_corrupt_artifact_rejected(self):
        self.write(self.boundary / 'mask.png', b'changed')
        with self.assertRaisesRegex(ValueError, 'Snapshot hash mismatch'):
            serve.snapshot_files(self.baseline, self.boundary)

    def test_corrupt_browser_decode_rejected(self):
        self.write(self.out / 'original.png', b'changed')
        with self.assertRaisesRegex(ValueError, 'Snapshot hash mismatch'):
            serve.snapshot_files(self.baseline, self.boundary)

    def test_validator_rejection_stops_admission(self):
        self.validator.side_effect = ValueError('invalid dataset')
        with self.assertRaisesRegex(ValueError, 'invalid dataset'):
            serve.snapshot_files(self.baseline, self.boundary)

    def test_manifest_changed_during_admission_rejected(self):
        self.validator.side_effect = [self.manifest, {'changed': True}]
        with self.assertRaisesRegex(ValueError, 'changed during admission'):
            serve.snapshot_files(self.baseline, self.boundary)

    def test_loopback_binding(self):
        with patch.object(serve, 'ThreadingHTTPServer') as server:
            result = serve.create_server(self.baseline, self.boundary, 9911)
            server.assert_called_once_with(('127.0.0.1', 9911), serve.Handler)
            self.assertIn('/boundary-mask.png', result.snapshot)

    def test_routes_and_host(self):
        snapshot = serve.snapshot_files(self.baseline, self.boundary)
        server = SimpleNamespace(server_address=('127.0.0.1', 9911), snapshot=snapshot)
        for path, host, status in [('/boundary-geometry.json', 'localhost:9911', 200),
                                   ('/boundary-mask.png', '127.0.0.1:9911', 200),
                                   ('/boundary-mask.png', 'localhost:8765', 403),
                                   ('/boundary-mask.png', 'evil.example:9911', 403),
                                   ('/candidate.json', 'localhost:9911', 404),
                                   ('/../manifest.json', 'localhost:9911', 404),
                                   ('/original.png?path=secret', 'localhost:9911', 404),
                                   ('/favicon.ico', 'localhost:9911', 204)]:
            with self.subTest(path=path, host=host):
                request = Request(f'GET {path} HTTP/1.1\r\nHost: {host}\r\n\r\n'.encode())
                QuietHandler(request, ('127.0.0.1', 1234), server)
                self.assertIn(f' {status} '.encode(), request.output.split(b'\r\n')[0])
        request = Request(b'GET / HTTP/1.1\r\nHost: localhost:9911\r\nHost: localhost:9911\r\n\r\n')
        QuietHandler(request, ('127.0.0.1', 1234), server)
        self.assertIn(b' 403 ', request.output.split(b'\r\n')[0])


if __name__ == '__main__':
    unittest.main()
