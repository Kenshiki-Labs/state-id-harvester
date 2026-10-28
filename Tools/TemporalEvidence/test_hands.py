import copy
from pathlib import Path
import tempfile
import unittest
from PIL import Image
import analyze
from contract import digest, json_bytes
from hands import read_hands
from reader import Export
from serve import ReportSnapshot
from test_export import JournalFixture, uid


class HandReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.fixture = JournalFixture(self.root/'export')
        self.source = self.fixture.frames[0]

    def tearDown(self):
        self.temp.cleanup()

    def add_result(self, status='completed'):
        source = self.fixture.records[self.source][0]['frame']
        point = dict(x=.4, y=.6, z=0)
        hand = dict(normalizedLandmarks=[point.copy() for _ in range(21)],
                    worldLandmarks=[point.copy() for _ in range(21)],
                    handedness=[dict(index=0, score=.9, categoryName='Left')])
        value = dict(schemaVersion=1, workflowID=self.fixture.workflow, recordingID=self.fixture.run,
            sourceFrameID=self.source, sourceSHA256=source['sha256'], sourceMetadata=copy.deepcopy(source),
            configuration='synthetic-media-pipe-v1', status=status,
            sourceToAnalysis=dict(kind='identity_full_scene', width=2, height=2, orientation=1))
        if status == 'error':
            value['failure'] = 'injected_provider_error'
        else:
            value['observation'] = dict(timestampMilliseconds=int(source['timestamp']['value'] / 100 * 1000), sourceWidth=2, sourceHeight=2,
                orientation=1, coordinateSpace='upright_normalized_top_left',
                hands=[hand] if status == 'completed' else [])
        rid = uid()
        link = {k: value[k] for k in ('schemaVersion', 'workflowID', 'sourceFrameID', 'sourceSHA256', 'configuration')}
        link.update(recordKind='handLandmarkFrame', payloadSHA256=digest(json_bytes(value)))
        self.fixture.records[rid] = [link, json_bytes(value)]
        self.fixture.write()
        return rid, value

    def update(self, rid, value):
        raw = json_bytes(value)
        self.fixture.records[rid][0]['payloadSHA256'] = digest(raw)
        self.fixture.records[rid][1] = raw
        self.fixture.write()

    def test_exact_source_overlay_roundtrip_preserves_original_and_unreviewed_status(self):
        rid, value = self.add_result()
        target = self.root/'package'
        report = analyze.publish(self.fixture.root, target)
        frame = report['frames'][0]
        self.assertEqual(frame['handLandmarks'], dict(status='completed', resultIDs=[rid]))
        self.assertEqual(report['assessment']['status'], 'unreviewed')
        self.assertEqual(report['handLandmarks']['coverage']['analyzedFrameCount'], 1)
        self.assertEqual(len(report['handLandmarks']['coverage']['gaps']), 2)
        with Image.open(target/frame['image']) as native, Image.open(target/frame['handOverlayImage']) as overlay:
            self.assertEqual(native.size, overlay.size)
            self.assertEqual(native.getpixel((0, 0)), 0)
        admitted = ReportSnapshot(target)
        try:
            self.assertNotEqual(admitted.frame(0), admitted.frame(0, hands=True))
            (target/frame['handOverlayImage']).write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                admitted.frame(0, hands=True)
        finally:
            admitted.close()

    def test_no_hands_error_and_absence_remain_distinct(self):
        self.add_result('noHands')
        report = analyze.publish(self.fixture.root, self.root/'no-hands')
        self.assertEqual(report['frames'][0]['handLandmarks']['status'], 'noHands')
        self.assertNotIn('handOverlayImage', report['frames'][0])
        self.assertEqual(report['frames'][1]['handLandmarks']['status'], 'unavailable')
        self.source = self.fixture.frames[1]
        self.add_result('error')
        report = analyze.publish(self.fixture.root, self.root/'error')
        self.assertEqual(report['frames'][1]['handLandmarks']['status'], 'error')
        self.assertEqual(report['assessment']['status'], 'unreviewed')

    def test_duplicate_results_do_not_silently_choose_an_overlay(self):
        self.add_result()
        self.add_result()
        report = analyze.publish(self.fixture.root, self.root/'ambiguous')
        self.assertEqual(report['frames'][0]['handLandmarks']['status'], 'ambiguous')
        self.assertNotIn('handOverlayImage', report['frames'][0])

    def test_wrong_source_or_transform_rejected_even_when_export_hashes_rebuilt(self):
        rid, original = self.add_result()
        mutations = [
            lambda v: v.update(sourceSHA256='0'*64),
            lambda v: v.update(sourceFrameID=uid()),
            lambda v: v.update(workflowID=uid()),
            lambda v: v['sourceMetadata'].update(width=4),
            lambda v: v['sourceToAnalysis'].update(width=1),
            lambda v: v['observation'].update(sourceWidth=1),
            lambda v: v['observation'].update(orientation=6),
            lambda v: v['observation']['hands'][0]['normalizedLandmarks'].pop(),
            lambda v: v['observation']['hands'][0]['handedness'][0].update(score=1.1),
            lambda v: v.update(status='noHands'),
        ]
        for mutate in mutations:
            value = copy.deepcopy(original)
            mutate(value)
            self.update(rid, value)
            with self.subTest(value=value), self.assertRaises((ValueError, KeyError)):
                read_hands(Export(self.fixture.root))


    def add_summary(self, ids):
        rid = uid()
        entries = [self.fixture.records[r][0] for r in self.fixture.chain]
        lines = [f"{self.fixture.run}|{r}|{m['ordinal']}|{m['payloadSHA256']}"
                 for r, m in zip(self.fixture.chain, entries)]
        value = dict(schemaVersion=1, workflowID=self.fixture.workflow, captureIDs=[self.fixture.still],
            configuration='synthetic-media-pipe-v1', summaryID=rid, frameResultIDs=ids,
            sourceInventorySHA256=digest('\n'.join(lines).encode()), analyzedFrameCount=len(ids),
            detectedFrameCount=len(ids), failedFrameCount=0,
            segments=[dict(recordingID=self.fixture.run, status='complete', frameCount=3)],
            gaps=[dict(recordingID=self.fixture.run, ordinal=0, reason='segment_boundary')], recordedAt=1)
        link = dict(schemaVersion=1, recordKind='handLandmarkSummary', workflowID=self.fixture.workflow,
                    configuration=value['configuration'], payloadSHA256=digest(json_bytes(value)))
        self.fixture.records[rid] = [link, json_bytes(value)]
        self.fixture.write()
        return rid, value

    def test_summary_inventory_counts_and_stale_state(self):
        ids = []
        for source in self.fixture.frames:
            self.source = source
            ids.append(self.add_result()[0])
        rid, value = self.add_summary(ids)
        report = read_hands(Export(self.fixture.root))
        self.assertEqual(report['summaries'][0]['sourceInventoryStatus'], 'current')
        invalid = copy.deepcopy(value)
        invalid['analyzedFrameCount'] = 0
        self.update(rid, invalid)
        with self.assertRaisesRegex(ValueError, 'analyzed count'):
            read_hands(Export(self.fixture.root))
        stale = copy.deepcopy(value)
        stale['sourceInventorySHA256'] = '0'*64
        self.update(rid, stale)
        self.assertEqual(read_hands(Export(self.fixture.root))['summaries'][0]['sourceInventoryStatus'], 'stale')
        missing = copy.deepcopy(value)
        missing['frameResultIDs'] = ids[:-1]
        missing['analyzedFrameCount'] = missing['detectedFrameCount'] = 2
        self.update(rid, missing)
        with self.assertRaisesRegex(ValueError, 'omits source frames'):
            read_hands(Export(self.fixture.root))

    def test_provider_timestamp_must_match_exact_bound_frame(self):
        rid, value = self.add_result()
        value['observation']['timestampMilliseconds'] += 1
        self.update(rid, value)
        with self.assertRaisesRegex(ValueError, 'timestamp mismatch'):
            read_hands(Export(self.fixture.root))

    def test_retry_selects_one_published_run_without_splicing_history(self):
        first, second = [], []
        for source in self.fixture.frames:
            self.source = source
            first.append(self.add_result()[0])
        self.add_summary(first)
        for source in self.fixture.frames:
            self.source = source
            second.append(self.add_result()[0])
        rid, summary = self.add_summary(second)
        summary['recordedAt'] = 2
        self.update(rid, summary)
        report = analyze.publish(self.fixture.root, self.root/'retry')
        self.assertEqual(report['handLandmarks']['coverage']['analyzedFrameCount'], 3)
        self.assertEqual(len(report['handLandmarks']['results']), 6)
        self.assertEqual([f['handLandmarks']['resultIDs'][0] for f in report['frames']], second)
        # A later stale inventory must not displace the current published run.
        summary['sourceInventorySHA256'] = '0'*64
        self.update(rid, summary)
        report = analyze.publish(self.fixture.root, self.root/'stale-retry')
        self.assertEqual([f['handLandmarks']['resultIDs'][0] for f in report['frames']], first)
