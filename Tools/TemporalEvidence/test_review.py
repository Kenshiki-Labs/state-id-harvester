import copy
from pathlib import Path
import tempfile
import unittest
from contract import json_bytes
from review import assess


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'review.json'
        self.report = {'source': {'indexSHA256': 'source'}, 'frames': [
            {'recordID': 'a', 'recordingID': 'r', 'sourceSHA256': 'ha'},
            {'recordID': 'b', 'recordingID': 'r', 'sourceSHA256': 'hb'},
            {'recordID': 'c', 'recordingID': 's', 'sourceSHA256': 'hc'}]}
        self.review = dict(schema='id_cadastral_temporal_review_v1', sourceIndexSHA256='source',
                           method='visual_review', reviewerType='human', reviewer='Test reviewer',
                           reviewedAt='2026-09-14T17:00:00-07:00', status='observed',
                           observations=[dict(kind='turnover', outcome='observed', recordingID='r',
                           startFrameID='a', endFrameID='b', startFrameSHA256='ha', endFrameSHA256='hb',
                           note='Object changes face while held.')])

    def tearDown(self):
        self.temp.cleanup()

    def run_review(self):
        self.path.write_bytes(json_bytes(self.review))
        return assess(self.path, self.report)

    def test_unreviewed_never_positive(self):
        self.assertEqual(assess(None, self.report)['status'], 'unreviewed')

    def test_bound_review_and_assistant_attribution(self):
        self.review['reviewerType'] = 'assistant'
        result = self.run_review()
        self.assertEqual(result['status'], 'observed')
        self.assertEqual(result['reviewerType'], 'assistant')
        self.assertEqual(len(result['reviewInputSHA256']), 64)

    def test_review_source_and_frame_hashes(self):
        for field in ('sourceIndexSHA256',):
            saved = self.review[field]; self.review[field] = 'wrong'
            with self.assertRaises(ValueError): self.run_review()
            self.review[field] = saved
        self.review['observations'][0]['endFrameSHA256'] = 'wrong'
        with self.assertRaises(ValueError): self.run_review()

    def test_cross_segment_and_reversed_ranges(self):
        item = self.review['observations'][0]
        item.update(endFrameID='c', endFrameSHA256='hc')
        with self.assertRaises(ValueError): self.run_review()
        item.update(startFrameID='b', endFrameID='a', startFrameSHA256='hb', endFrameSHA256='ha')
        with self.assertRaises(ValueError): self.run_review()

    def test_no_positive_from_single_frame_or_hand_contact(self):
        item = self.review['observations'][0]
        item.update(endFrameID='a', endFrameSHA256='ha')
        with self.assertRaises(ValueError): self.run_review()
        item.update(kind='hand_contact')
        with self.assertRaises(ValueError): self.run_review()

    def test_empty_findings_and_unattributed_review_rejected(self):
        original = copy.deepcopy(self.review)
        for field, value in [('observations', []), ('reviewer', ''), ('reviewedAt', '2026-09-14'),
                             ('method', 'automatic'), ('reviewerType', 'unknown')]:
            self.review = copy.deepcopy(original); self.review[field] = value
            with self.assertRaises(ValueError): self.run_review()

    def test_not_observed_is_preserved(self):
        self.review['status'] = 'not_observed'
        self.review['observations'][0]['outcome'] = 'not_observed'
        self.assertEqual(self.run_review()['status'], 'not_observed')

    def test_positive_review_cannot_bridge_retained_gap(self):
        self.report['coverage'] = {'gaps': [{'beforeFrameID': 'a', 'afterFrameID': 'b',
                                            'reason': 'frame_interval_or_clock_gap'}]}
        with self.assertRaisesRegex(ValueError, 'coverage gap'):
            self.run_review()
