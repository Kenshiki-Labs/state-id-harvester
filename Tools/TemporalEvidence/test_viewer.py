import hashlib
from http.client import HTTPConnection
from http.server import HTTPServer
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
import zlib

from serve import ReportSnapshot, handler_for, strict_json


def png(red=180):
    def chunk(kind, raw):
        return struct.pack('!I', len(raw)) + kind + raw + struct.pack('!I', zlib.crc32(kind + raw))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + bytes([red, 80, 120]) * 2) * 2)) + chunk(b'IEND', b''))


def fixture(root):
    (root / 'frames').mkdir()
    images = [png(), png(200), png(220)]
    frames = []
    artifacts = {}
    for i, image in enumerate(images):
        name = f'frames/f{i}.png'
        (root / name).write_bytes(image)
        artifacts[name] = hashlib.sha256(image).hexdigest()
        frames.append(dict(recordID=f'f{i}', recordingID='segment-b' if i == 2 else 'segment-a',
                           sequenceNumber=i, hostTimeSeconds=10 + i, relativeTimeSeconds=i if i < 2 else 0,
                           width=2, height=2, image=name, imagePresentation='native_rgb',
                           sourceSHA256='a' * 64, metrics={'meanLuma': 0.5},
                           phoneMotion={'status': 'aligned', 'gyroDegreesPerSecond': 20 * i,
                                        'sampleHostTimeSeconds': 10 + i, 'alignmentDeltaSeconds': 0},
                           camera=None, geometry=None))
    report = dict(schema='id_cadastral_temporal_evidence_v1', frames=frames, artifacts=artifacts,
                  method={'id': 'native_temporal_observation_v1'}, source={'indexSHA256': 'a' * 64},
                  assessment={'status': 'unreviewed', 'method': 'not_reviewed', 'observations': []},
                  recordings=[dict(recordingID=s, status='partial', frameCount=n)
                              for s, n in [('segment-a', 2), ('segment-b', 1)]],
                  coverage=dict(status='partial', frameCount=3, motionSampleCount=3, recordingCount=2,
                                gaps=[dict(beforeFrameID='f0', afterFrameID='f1', reason='retained_gap', hostTimeDeltaSeconds=1)]))
    publish(root, report)
    return report


def publish(root, report):
    raw = json.dumps(report).encode()
    (root / 'report.json').write_bytes(raw)
    (root / 'manifest.json').write_text(json.dumps(dict(schema='id_cadastral_temporal_package_v1',
                                                     reportSHA256=hashlib.sha256(raw).hexdigest())))


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.report = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_immutable_report_and_selected_image_bytes(self):
        snapshot = ReportSnapshot(self.root)
        try:
            original = snapshot.report_bytes
            (self.root / 'report.json').write_text('{}')
            self.assertEqual(snapshot.report_bytes, original)
            served = snapshot.frame(0)
            (self.root / 'frames/f0.png').write_bytes(png(0))
            self.assertEqual(served, png())
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                snapshot.frame(0)
        finally:
            snapshot.close()

    def test_tampered_report_and_artifact_rejected(self):
        for path in ('report.json', 'frames/f0.png'):
            with self.subTest(path=path):
                prior = (self.root / path).read_bytes()
                (self.root / path).write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    ReportSnapshot(self.root)
                (self.root / path).write_bytes(prior)

    def test_symlink_and_parent_symlink_rejected(self):
        path = self.root / 'frames/f0.png'
        path.unlink()
        path.symlink_to(self.root / 'frames/f1.png')
        with self.assertRaises(OSError):
            ReportSnapshot(self.root)
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            ReportSnapshot(alias)

    def test_nested_directory_swap_rejected_after_admission(self):
        snapshot = ReportSnapshot(self.root)
        try:
            (self.root / 'frames').rename(self.root / 'old')
            (self.root / 'frames').symlink_to(self.root / 'old', target_is_directory=True)
            with self.assertRaises(OSError):
                snapshot.frame(0)
        finally:
            snapshot.close()

    def test_traversal_duplicate_keys_and_nonfinite_rejected(self):
        for value in ('../secret', '/etc/passwd', 'frames/../secret', 'frames//f0.png', 'frames\\f0.png'):
            with self.subTest(value=value):
                report = dict(self.report, artifacts={value: 'a' * 64})
                publish(self.root, report)
                with self.assertRaises(ValueError):
                    ReportSnapshot(self.root)
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}'):
            with self.assertRaises(ValueError):
                strict_json(raw)

    def test_missing_inventory_and_duplicate_frame_rejected(self):
        for report in (dict(self.report, artifacts={}),
                       dict(self.report, frames=[self.report['frames'][0]] * 2)):
            publish(self.root, report)
            with self.assertRaises(ValueError):
                ReportSnapshot(self.root)

    def test_allowlisted_routes_host_and_mutation_fail_closed(self):
        snapshot = ReportSnapshot(self.root)
        server = HTTPServer(('127.0.0.1', 0), handler_for(snapshot))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def get(path, host=None):
                connection = HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', path, headers={'Host': host} if host else {})
                response = connection.getresponse()
                result = response.status, response.read()
                connection.close()
                return result
            for path in ('/', '/viewer.js', '/viewer.css', '/api/report', '/frame/0'):
                self.assertEqual(get(path)[0], 200, path)
            for path in ('/frame/-1', '/frame/999', '/frame/00', '/frames/f0.png', '/report.json',
                         '/../manifest.json', '/%2e%2e/secret', '/frame/0?other=1'):
                self.assertEqual(get(path)[0], 404, path)
            self.assertEqual(get('/api/report', 'attacker.example')[0], 403)
            (self.root / 'frames/f0.png').write_bytes(b'changed')
            self.assertEqual(get('/frame/0')[0], 409)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
            snapshot.close()


if __name__ == '__main__':
    unittest.main()
