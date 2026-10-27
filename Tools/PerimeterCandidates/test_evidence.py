import unittest
import numpy as np

from Tools.PerimeterCandidates.evidence import assess_surroundings, compare_pair, competing_pairs, statistics


def transition(start, stop=None, name="candidate"):
    return {"candidateId": name, "range": [start, start if stop is None else stop]}


class EvidenceTests(unittest.TestCase):
    def test_all_pixels_contribute_and_unsigned_differences_do_not_wrap(self):
        values = np.array([[255, 0, 0], [0, 0, 0], [0, 255, 0]], np.uint8)
        result = statistics(values)
        self.assertEqual(result["meanRGB"], [85, 85, 0])
        self.assertEqual(result["meanAbsoluteAdjacentRGBDifference"], [127.5, 127.5, 0])
        self.assertEqual(result["chromaticityPixelCount"], 2)

    def test_black_chromaticity_is_undefined(self):
        result = statistics(np.zeros((2, 3), np.uint8))
        self.assertIsNone(result["meanChromaticity"])
        self.assertEqual(result["chromaticityPixelCount"], 0)

    def test_candidate_separation_defines_support(self):
        rgb = np.arange(60, dtype=np.uint8).reshape(1, 20, 3)
        result = compare_pair(rgb, "x", 0, transition(6), transition(10))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["bands"]["before"]["availableRange"], [3, 6])
        self.assertEqual(result["bands"]["between"]["availableRange"], [7, 10])
        self.assertEqual(result["bands"]["after"]["availableRange"], [11, 14])
        self.assertEqual(result["bands"]["between"]["statistics"]["meanRGB"], rgb[0, 7:10].mean(axis=0).tolist())
        wider = compare_pair(rgb, "x", 0, transition(6), transition(12))
        self.assertEqual(wider["bands"]["before"]["availableRange"], [1, 6])

    def test_clipping_never_becomes_complete(self):
        result = compare_pair(np.ones((1, 12, 3), np.uint8), "x", 0, transition(1), transition(5))
        self.assertEqual(result["status"], "clipped_support")
        self.assertEqual(result["bands"]["before"]["requestedRange"], [-2, 1])
        self.assertNotIn("betweenDistances", result)

    def test_overlap_and_adjacency_explicit(self):
        rgb = np.ones((1, 12, 3), np.uint8)
        self.assertEqual(compare_pair(rgb, "x", 0, transition(2, 5), transition(4, 6))["status"], "overlapping_transitions")
        self.assertEqual(compare_pair(rgb, "x", 0, transition(2, 5), transition(6))["status"], "no_between_pixels")

    def test_transpose_preserves_evidence(self):
        rgb = np.arange(60, dtype=np.uint8).reshape(1, 20, 3)
        x = compare_pair(rgb, "x", 0, transition(6), transition(10))
        y = compare_pair(rgb.transpose(1, 0, 2), "y", 0, transition(6), transition(10))
        self.assertEqual(x["bands"], y["bands"])

    def test_every_scan_and_disjoint_same_chain_ranges_retained(self):
        rgb = np.ones((12, 5, 3), np.uint8)
        points = np.array([[2, 2], [2, 3], [2, 6], [2, 7]], np.int32)
        candidates = [{"candidateId": "observed", "side": "top", "sourcePointStart": 0, "sourcePointStopExclusive": 4}]
        result = assess_surroundings(rgb, points, candidates)
        self.assertEqual(result["summary"]["scans"], 2 * (12 + 5))
        scan = result["sides"]["top"]["scans"][2]
        self.assertEqual([p["range"] for p in scan["transitions"]], [[2, 3], [6, 7]])
        self.assertEqual(scan["pairs"][0]["betweenPixelCount"], 2)
        self.assertEqual(result["sides"]["top"]["scans"][0]["status"], "no_transition")

    def test_missing_candidates_and_singleton_have_no_fabricated_pair(self):
        rgb = np.ones((4, 4, 3), np.uint8)
        empty = assess_surroundings(rgb, np.empty((0, 2), np.int32), [])
        self.assertEqual(empty["summary"]["pairs"], 0)
        one = assess_surroundings(rgb, np.array([[1, 1]], np.int32), [{"candidateId": "a", "side": "left", "sourcePointStart": 0, "sourcePointStopExclusive": 1}])
        self.assertEqual(one["sides"]["left"]["scans"][1]["status"], "single_transition")

    def test_invalid_coordinates_rejected(self):
        with self.assertRaises(ValueError):
            assess_surroundings(np.ones((4, 4, 3), np.uint8), np.array([[4, 0]], np.int32), [])
        with self.assertRaises(ValueError):
            compare_pair(np.ones((4, 4, 3), np.uint8), "x", -1, transition(0), transition(2))

    def test_nested_and_identical_transitions_preserve_alternatives(self):
        a, b, c = transition(2, 10, "a"), transition(4, 5, "b"), transition(12, name="c")
        pairs = list(competing_pairs([a, b, c]))
        self.assertEqual([(x["candidateId"], y["candidateId"]) for x, y in pairs], [("a", "b"), ("a", "c"), ("b", "c")])
        duplicate = transition(2, 10, "duplicate")
        self.assertEqual(len(list(competing_pairs([a, duplicate, c]))), 3)

    def test_branch_contamination_is_explicit(self):
        runs = [np.array([[x, 0] for x in range(2, 11)]), np.array([[4, 0], [5, 0]]), np.array([[12, 0]])]
        points = np.concatenate(runs).astype(np.int32)
        candidates, offset = [], 0
        for index, run in enumerate(runs):
            candidates.append({"candidateId": index, "side": "left", "sourcePointStart": offset, "sourcePointStopExclusive": offset + len(run)})
            offset += len(run)
        result = assess_surroundings(np.ones((1, 30, 3), np.uint8), points, candidates)
        pairs = result["sides"]["left"]["scans"][0]["pairs"]
        nested = next(p for p in pairs if p["first"]["candidateId"] == 1 and p["second"]["candidateId"] == 2)
        self.assertEqual(nested["otherTransitionsInBands"]["between"][0]["candidateId"], 0)


if __name__ == "__main__":
    unittest.main()
