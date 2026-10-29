"""Source snapshot and evaluation publication regressions."""
import json
import unittest
from unittest.mock import patch

import evaluate
import native_input
import test_dataset as dataset_tests


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = dataset_tests.BoundaryDatasetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base, self.run = self.fixture.base, self.fixture.run

    def test_native_is_read_only(self):
        pixels, _, _ = native_input.load_native(self.base)
        self.assertFalse(pixels.flags.writeable)
        with self.assertRaises(ValueError):
            pixels[0, 0, 0] = 1

    def test_each_included_raster_is_bound_to_manifest(self):
        for relative in ('front-rectified.png', 'geotiff/front-card.tif',
                         'browser-viewer/objects-mask.png'):
            with self.subTest(relative=relative):
                path = self.base / relative
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                try:
                    with self.assertRaisesRegex(ValueError, 'lineage mismatch'):
                        native_input.load_native(self.base)
                finally:
                    path.write_bytes(original)

    def test_snapshot_decode_rejects_changed_source(self):
        original_open = native_input.Image.open
        path = self.base / 'front-original.heic'
        def mutate_after_snapshot(stream, *args, **kwargs):
            # Image admission reads the already-hashed snapshot, not this path.
            path.write_bytes(b'replaced while decoding')
            return original_open(stream, *args, **kwargs)
        with patch('native_input.Image.open', side_effect=mutate_after_snapshot):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                native_input.load_native(self.base)

    def test_object_coordinate_mismatch_rejected(self):
        path = self.base / 'browser-viewer/objects.json'
        objects = json.loads(path.read_bytes())
        objects['coordinateSystem']['width'] += 1
        path.write_text(json.dumps(objects))
        with self.assertRaisesRegex(ValueError, 'Object coordinate'):
            native_input.load_native(self.base)

    def test_evaluation_repeat_is_explicit_and_complete(self):
        first = evaluate.evaluate(self.base, self.run)
        second = evaluate.evaluate(self.base, self.run)
        self.assertEqual(first, second)
        self.assertEqual(json.loads((self.run / 'evaluation.json').read_bytes()), second)
        self.assertEqual(first['candidateSHA256'], evaluate.digest((self.run / 'candidate.json').read_bytes()))
        self.assertEqual(list(self.run.glob('.evaluation-*.tmp')), [])

    def assert_rejected_publication(self, mutation, expected):
        previous = (self.run / 'evaluation.json').read_bytes()
        original_verify = evaluate.verify_unchanged
        def mutate(base, hashes):
            mutation()
            return original_verify(base, hashes)
        with patch('evaluate.verify_unchanged', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, expected):
                evaluate.evaluate(self.base, self.run)
        self.assertEqual((self.run / 'evaluation.json').read_bytes(), previous)
        self.assertEqual(list(self.run.glob('.evaluation-*.tmp')), [])

    def test_candidate_mutation_does_not_publish_misattributed_hash(self):
        path = self.run / 'candidate.json'
        self.assert_rejected_publication(lambda: path.write_bytes(path.read_bytes() + b' '),
                                         'Candidate changed')

    def test_mask_mutation_does_not_publish(self):
        path = self.run / 'candidate-mask.png'
        self.assert_rejected_publication(lambda: path.write_bytes(path.read_bytes() + b' '),
                                         'Candidate changed')

    def test_source_mutation_does_not_publish(self):
        self.assert_rejected_publication(
            lambda: (self.base / 'front-original.heic').write_bytes(b'changed'), 'Source changed')

    def test_review_mutation_does_not_publish(self):
        review = self.run / 'review.json'
        review.write_text(json.dumps({'candidateSHA256': evaluate.digest((self.run / 'candidate.json').read_bytes()),
                                      'disposition': 'not_promoted'}))
        previous = (self.run / 'evaluation.json').read_bytes()
        original_verify = evaluate.verify_unchanged
        def mutate(base, hashes):
            review.write_bytes(review.read_bytes() + b' ')
            return original_verify(base, hashes)
        with patch('evaluate.verify_unchanged', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'Visual review changed'):
                evaluate.evaluate(self.base, self.run, review)
        self.assertEqual((self.run / 'evaluation.json').read_bytes(), previous)

    def test_replace_failure_keeps_previous_evaluation(self):
        previous = (self.run / 'evaluation.json').read_bytes()
        with patch('evaluate.os.replace', side_effect=OSError('replace failed')):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                evaluate.evaluate(self.base, self.run)
        self.assertEqual((self.run / 'evaluation.json').read_bytes(), previous)
        self.assertEqual(list(self.run.glob('.evaluation-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
