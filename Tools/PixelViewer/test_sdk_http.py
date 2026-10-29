"""SDK packaging smoke: real admission and HTTP, using synthetic source fixtures."""
import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request

import serve
from dataset import json_bytes, package_boundary
from native_input import load_native
import test_validation


class SDKHTTPTests(unittest.TestCase):
    def workspace_fixture(self):
        fixture = test_validation.DatasetValidationTests('test_dataset_round_trip')
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        baseline = fixture.base
        browser = baseline / 'browser-viewer'
        original = (browser / 'original.png').read_bytes()
        (browser / 'geotiff.png').write_bytes(original)
        viewer = json.loads((browser / 'manifest.json').read_bytes())
        viewer['derivation'] = json.loads((baseline / 'front-geometry.json').read_bytes())['derivation']
        tiff = json.loads((baseline / 'geotiff/manifest.json').read_bytes())
        viewer['geoTIFFDisplay'] = {
            'sourceSHA256': tiff['output']['sha256'],
            'displaySHA256': hashlib.sha256(original).hexdigest(),
        }
        (browser / 'manifest.json').write_bytes(json_bytes(viewer))
        _, _, hashes = load_native(baseline)
        fixture.candidate['sourceHashes'] = hashes
        fixture.save_candidate()
        boundary = fixture.root / 'http-boundary'
        package_boundary(baseline, fixture.run, boundary)
        return baseline,boundary,original

    def test_admitted_workspace_serves_assets_and_keeps_immutable_bytes(self):
        baseline,boundary,original=self.workspace_fixture()
        browser=baseline/'browser-viewer'
        server = serve.create_server(baseline, boundary, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f'http://127.0.0.1:{server.server_port}'
            for route in ('/', '/app.js', '/working.js', '/workspace.js', '/workspace.css',
                          '/viewer-config.json', '/boundary-manifest.json', '/original.png'):
                with self.subTest(route=route), urllib.request.urlopen(origin + route, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertTrue(response.read())
            (browser / 'original.png').write_bytes(b'changed after admission')
            with urllib.request.urlopen(origin + '/original.png', timeout=5) as response:
                self.assertEqual(response.read(), original)
            for route in ('/../Package.swift', '/original.png?path=secret'):
                with self.assertRaises(urllib.error.HTTPError) as result:
                    urllib.request.urlopen(origin + route, timeout=5)
                self.assertEqual(result.exception.code, 404)
            request = urllib.request.Request(origin, headers={'Host': 'outside.example'})
            with self.assertRaises(urllib.error.HTTPError) as result:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(result.exception.code, 403)
            with self.assertRaises(ValueError):
                serve.snapshot_files(baseline, boundary)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_integrated_material_routes_share_source_and_reject_wrong_dimensions(self):
        import numpy as np
        from PIL import Image
        baseline,boundary,original=self.workspace_fixture()
        root=baseline/'scores';root.mkdir()
        with Image.open(baseline/'browser-viewer/original.png') as image:w,h=image.size
        np.save(root/'scores.npy',np.broadcast_to(np.arange(46,dtype=np.float32)[:,None,None],(46,h,w)).copy())
        np.save(root/'margin.npy',np.ones((h,w),dtype=np.float32))
        manifest=dict(schema='apple_dms_scores_v1',width=w,height=h,
            source_sha256=hashlib.sha256(original).hexdigest(),
            bands=[dict(index=i,name=f'Material {i}') for i in range(46)],
            artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()})
        (root/'manifest.json').write_text(json.dumps(manifest))
        server=serve.create_server(baseline,boundary,port=0,scores=root)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            origin=f'http://127.0.0.1:{server.server_port}'
            with urllib.request.urlopen(origin+'/materials/') as response:
                page=response.read().decode()
            self.assertIn("fetch('/materials/manifest.json')",page)
            self.assertIn('fetch(`/materials/pixel?',page)
            self.assertIn("?'/materials/margin.png'",page)
            with urllib.request.urlopen(origin+'/materials/pixel?x=0&y=0') as response:
                self.assertEqual(json.load(response)['scores'][0]['score'],45)
            np.save(root/'scores.npy',np.zeros((46,h,w),dtype=np.float32))
            with urllib.request.urlopen(origin+'/materials/pixel?x=0&y=0') as response:
                self.assertEqual(json.load(response)['scores'][0]['score'],45)
            request=urllib.request.Request(origin+'/materials/',headers={'Host':'outside.example'})
            with self.assertRaises(urllib.error.HTTPError) as result:urllib.request.urlopen(request)
            self.assertEqual(result.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)
        with self.assertRaises(ValueError):serve.create_server(baseline,boundary,port=0,scores=root)
        # A self-consistent score package from a different-sized image must also fail.
        np.save(root/'scores.npy',np.zeros((46,h,w+1),dtype=np.float32))
        np.save(root/'margin.npy',np.zeros((h,w+1),dtype=np.float32))
        manifest['width']=w+1
        manifest['artifacts']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in manifest['artifacts']}
        (root/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'dimensions'):
            serve.create_server(baseline,boundary,port=0,scores=root)


if __name__ == '__main__':
    unittest.main()
