import unittest
import numpy as np
from evaluate import profile, render_window, longest_true_run


class EvaluationTests(unittest.TestCase):
    def test_parallel_chains_are_not_merged(self):
        points = np.array([[1, 0], [1, 1], [1, 2], [3, 0], [3, 1], [3, 2]], np.int32)
        result, count, chains = profile(points, np.array([0, 3, 6]), (0, 0, 5, 4), 1)
        np.testing.assert_array_equal(count, [2, 2, 2, 0])
        np.testing.assert_array_equal(chains, [2, 2, 2, 0])
        self.assertEqual(result['longestEmptyRun'], 1)
        self.assertEqual(result['positionsWithMultipleChains'], 3)

    def test_window_does_not_join_reentry(self):
        points = np.array([[1, 0], [1, 1], [1, 2], [2, 1]], np.int32)
        result, _, _ = profile(points, np.array([0, 4]), (0, 0, 3, 2), 1)
        self.assertEqual(result['chains'][0]['storedRunsInWindow'], 2)

    def test_render_keeps_gap_and_source_pixels(self):
        rgb = np.full((3, 5, 3), 110, np.uint8)
        before = rgb.copy()
        points = np.array([[1, 1], [3, 1]], np.int32)
        source, edges, _ = render_window(rgb, points, np.array([0, 1, 2]), [], (0, 0, 5, 3))
        np.testing.assert_array_equal(np.array(source), before)
        np.testing.assert_array_equal(np.array(edges)[1, 2], [110, 110, 110])
        np.testing.assert_array_equal(rgb, before)

    def test_empty_and_complete_profiles(self):
        result, _, _ = profile(np.empty((0, 2), np.int32), np.array([0]), (0, 0, 4, 3), 0)
        self.assertEqual(result['longestEmptyRun'], 4)
        self.assertEqual(longest_true_run([False, False]), 0)


if __name__ == '__main__':
    unittest.main()
