"""Disk-backed journal verification and durable package publication regressions."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import numpy as np
from PIL import Image
import analyze
from contract import digest, json_bytes
from reader import Export


def uid():
    return str(uuid.uuid4()).upper()


def timestamp(value):
    return dict(clock='captureSessionSynchronizationClock', epoch=0, flags=1,
                value=value, timescale=100)


class JournalFixture:
    def __init__(self, root, sealed=True):
        self.root = root
        root.mkdir()
        self.run, self.workflow, self.session, self.still = [uid() for _ in range(4)]
        self.records, self.chain, self.frames = {}, [], []
        self.add('Start', dict(schemaVersion=1, startedAt=1, maximumDuration=120,
                              maximumDiskBytes=100000, maximumPendingBytes=10000))
        self.add('Event', dict(kind='session_started', clockCorrelation=dict(
            method='CMClockGetHostTimeClock_brackets_ProcessInfo_systemUptime',
            hostBeforeSeconds=1, hostAfterSeconds=1, bootTimeSeconds=1)))
        for i in range(3):
            raw = bytes([40*i]*4 + [128, 128])
            frame = dict(width=2, height=2, sequenceNumber=i, timestamp=timestamp(100+i),
                hostTimeSeconds=1+i/100, sha256=digest(raw), pixelFormat=875704422,
                planes=[dict(width=2, height=2, offset=0, byteCount=4,
                             sourceBytesPerRow=8, packedBytesPerRow=2),
                        dict(width=1, height=1, offset=4, byteCount=2,
                             sourceBytesPerRow=8, packedBytesPerRow=2)])
            self.frames.append(self.add('Frame', raw, frame=frame))
        samples = [dict(bootTimeSeconds=1+i/100,
            referenceFrame='xArbitraryZVertical_rotation_radians_per_second_acceleration_g',
            rotationRate=dict(x=0, y=0, z=0), gravity=dict(x=0, y=0, z=-1),
            userAcceleration=dict(x=0, y=0, z=0), attitude=dict(x=0, y=0, z=0, w=1))
            for i in range(3)]
        self.add('Motion', samples)
        still_raw = b'synthetic retained original'
        start_hash = self.records[self.run][0]['payloadSHA256']
        binding = dict(attemptID=self.still, side='front', sessionID=self.session,
                       stillSHA256=digest(still_raw), stillTimestamp=timestamp(101))
        manifest = dict(captureID=self.still, workflowID=self.workflow, profile='License front',
            sessionID=dict(rawValue=self.session), captureTimestamp=timestamp(101),
            fidelity=dict(sha256=digest(still_raw)), journeyRecording=dict(recordingID=self.run,
                workflowID=self.workflow, startSHA256=start_hash))
        self.records[self.still] = [manifest, still_raw]
        self.add('Event', dict(kind='still_retained', binding=binding))
        if sealed:
            self.add('Seal', dict(status='complete', reason='completed', frameCount=3,
                motionSampleCount=3, issueCount=0, retainedStillCount=1,
                refusedFrames=0, refusedMotionSamples=0))
        self.status = 'complete' if sealed else 'interrupted'
        self.write()

    def add(self, kind, payload, **fields):
        rid = self.run if not self.chain else uid()
        raw = payload if isinstance(payload, bytes) else json_bytes(payload)
        metadata = dict(schemaVersion=1, ordinal=len(self.chain), recordingID=self.run,
                        workflowID=self.workflow, recordKind='journeyRecording'+kind,
                        payloadSHA256=digest(raw), **fields)
        if self.chain:
            prev = self.chain[-1]
            metadata.update(previousID=prev, previousSHA256=self.records[prev][0]['payloadSHA256'])
        self.records[rid] = [metadata, raw]
        self.chain.append(rid)
        return rid

    def write(self):
        entries = []
        for rid, (metadata, raw) in self.records.items():
            directory = self.root/rid
            directory.mkdir(exist_ok=True)
            manifest = json_bytes(metadata)
            (directory/'manifest.json').write_bytes(manifest)
            (directory/'original.bin').write_bytes(raw)
            entries.append(dict(recordID=rid, manifestSHA256=digest(manifest), originalSHA256=digest(raw)))
        (self.root/'index.json').write_bytes(json_bytes(dict(schemaVersion=1, records=entries,
            journeyRecordings={self.run: self.status})))


class ExportPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = JournalFixture(self.root/'export')
        self.target = self.root/'package'

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_roundtrip_keeps_every_native_frame_and_statistic(self):
        report = analyze.publish(self.fixture.root, self.target)
        self.assertEqual(report['coverage']['frameCount'], 3)
        self.assertEqual(report['assessment']['status'], 'unreviewed')
        self.assertEqual(report['recordings'][0]['status'], 'complete')
        self.assertEqual(report['coverage']['status'], 'partial')
        for i, value in enumerate(report['frames']):
            self.assertEqual(value['recordID'], self.fixture.frames[i])
            self.assertEqual(value['metrics']['pixelCount'], 4)
            self.assertEqual(value['metrics']['meanLuma'], i*40)
            with Image.open(self.target/value['image']) as image:
                self.assertEqual(image.size, (2, 2))
                np.testing.assert_array_equal(np.asarray(image), np.full((2, 2), i*40))
        manifest = json.loads((self.target/'manifest.json').read_bytes())
        self.assertEqual(manifest['reportSHA256'], digest((self.target/'report.json').read_bytes()))
        for name, expected in report['artifacts'].items():
            self.assertEqual(expected, digest((self.target/name).read_bytes()))

    def test_payload_and_manifest_tampering_are_rejected(self):
        for filename in ('original.bin', 'manifest.json'):
            with self.subTest(filename=filename):
                self.fixture.write()
                path = self.fixture.root/self.fixture.frames[0]/filename
                path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaises(ValueError):
                    Export(self.fixture.root)

    def test_missing_and_duplicate_ordinals_are_rejected(self):
        saved = copy.deepcopy(self.fixture.records)
        del self.fixture.records[self.fixture.frames[1]]
        self.fixture.write()
        with self.assertRaises(ValueError):
            Export(self.fixture.root)
        self.fixture.records = saved
        self.fixture.records[self.fixture.frames[1]][0]['ordinal'] -= 1
        self.fixture.write()
        with self.assertRaises(ValueError):
            Export(self.fixture.root)

    def test_cross_workflow_and_still_linkage_are_rejected(self):
        for record, key in ((self.fixture.frames[0], 'workflowID'), (self.fixture.still, 'workflowID')):
            with self.subTest(record=record):
                saved = copy.deepcopy(self.fixture.records)
                self.fixture.records[record][0][key] = uid()
                self.fixture.write()
                with self.assertRaises(ValueError):
                    Export(self.fixture.root)
                self.fixture.records = saved

    def test_false_complete_seal_rejected_even_with_updated_hashes(self):
        row = self.fixture.records[self.fixture.chain[-1]]
        seal = json.loads(row[1]); seal['refusedFrames'] = 1
        row[1] = json_bytes(seal); row[0]['payloadSHA256'] = digest(row[1])
        self.fixture.write()
        with self.assertRaises(ValueError):
            Export(self.fixture.root)

    def test_first_loss_summary_survives_publication_and_refuses_false_complete(self):
        row = self.fixture.records[self.fixture.chain[-1]]
        seal = json.loads(row[1])
        seal.update(firstLossTimestamp=timestamp(102), firstLossHostTimeSeconds=1.02,
                    firstLossReason='frame_admission_failed:sink_capacity',
                    coalescedGapEvents=3, platformDropCallbacks=0)
        row[1] = json_bytes(seal); row[0]['payloadSHA256'] = digest(row[1])
        self.fixture.write()
        with self.assertRaisesRegex(ValueError, 'False complete seal'):
            Export(self.fixture.root)
        seal['status'] = 'partial'
        self.fixture.status = 'partial'
        row[1] = json_bytes(seal); row[0]['payloadSHA256'] = digest(row[1])
        self.fixture.write()
        report = analyze.publish(self.fixture.root, self.target)
        run = report['recordings'][0]
        self.assertEqual(run['firstLossTimestamp'], timestamp(102))
        self.assertEqual(run['coalescedGapEvents'], 3)
        self.assertEqual(run['status'], 'partial')

    def test_unsealed_verified_prefix_remains_interrupted(self):
        del self.fixture.records[self.fixture.chain[-1]]
        self.fixture.status = 'interrupted'
        self.fixture.write()
        report = analyze.publish(self.fixture.root, self.target)
        self.assertEqual(report['recordings'][0]['status'], 'interrupted')
        self.assertEqual(report['coverage']['frameCount'], 3)

    def test_export_version_requires_integer_not_boolean_or_float(self):
        path = self.fixture.root/'index.json'
        index = json.loads(path.read_bytes())
        for version in (True, 1.0, '1', 3):
            with self.subTest(version=version):
                index['schemaVersion'] = version
                path.write_bytes(json_bytes(index))
                with self.assertRaisesRegex(ValueError, 'Unsupported export version'):
                    Export(self.fixture.root)

    def test_empty_export_is_unavailable(self):
        (self.fixture.root/'index.json').write_bytes(json_bytes(dict(records=[], journeyRecordings={})))
        report = analyze.publish(self.fixture.root, self.target)
        self.assertEqual(report['coverage']['status'], 'unavailable')
        self.assertEqual(report['assessment']['status'], 'unreviewed')

    def test_existing_package_cannot_be_overwritten(self):
        analyze.publish(self.fixture.root, self.target)
        before = (self.target/'manifest.json').read_bytes()
        with self.assertRaises(ValueError):
            analyze.publish(self.fixture.root, self.target)
        self.assertEqual(before, (self.target/'manifest.json').read_bytes())

    def test_concurrent_publication_has_exactly_one_winner(self):
        barrier = threading.Barrier(2)
        original = analyze.build
        def synchronized(*args):
            result = original(*args)
            barrier.wait(timeout=10)
            return result
        def attempt():
            try:
                analyze.publish(self.fixture.root, self.target)
                return True
            except OSError:
                return False
        with patch.object(analyze, 'build', synchronized):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: attempt(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        manifest = json.loads((self.target/'manifest.json').read_bytes())
        self.assertEqual(manifest['reportSHA256'], digest((self.target/'report.json').read_bytes()))

    def test_interrupted_build_never_publishes_and_retry_succeeds(self):
        with patch.object(analyze, 'raster', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                analyze.publish(self.fixture.root, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob('.package-*')), [])
        self.assertEqual(analyze.publish(self.fixture.root, self.target)['coverage']['frameCount'], 3)

    def test_payload_mutation_after_verification_is_rejected_before_consumption(self):
        original = analyze.build
        def changed(export, *args):
            path = self.fixture.root/self.fixture.frames[1]/'original.bin'
            path.write_bytes(bytes(6))
            return original(export, *args)
        with patch.object(analyze, 'build', changed):
            with self.assertRaises(ValueError):
                analyze.publish(self.fixture.root, self.target)
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
