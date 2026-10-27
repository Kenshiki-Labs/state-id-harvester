import copy
import unittest
import numpy as np
from Tools.PerimeterCandidates.assess_paths import appearance_hypothesis, assess_paths, _membership
from Tools.PerimeterCandidates.evidence import statistics


def pair(interior=(30, 120, 120), between=(80, 70, 60), exterior=(160, 140, 120)):
    return {"first": {"candidateId": 0, "range": [4, 4]},
            "second": {"candidateId": 1, "range": [8, 8]}, "status": "complete", "comparisonEligible": True,
            "bands": {name: {"availableRange": bounds, "statistics": statistics(np.tile(rgb, (3, 1)))}
                      for name, bounds, rgb in (("before", [1, 4], interior), ("between", [5, 8], between), ("after", [9, 12], exterior))}}


def fixture():
    points = np.array([[0, 4], [1, 4], [0, 8], [1, 8]])
    candidates = [{"candidateId": 0, "side": "bottom", "sourcePointStart": 0, "sourcePointStopExclusive": 2},
                  {"candidateId": 1, "side": "bottom", "sourcePointStart": 2, "sourcePointStopExclusive": 4}]
    assembly = {"paths": [{"pathId": 0, "sourceSegmentStartIndices": [0], "points": points[:2].tolist()}, {"pathId": 1, "sourceSegmentStartIndices": [2], "points": points[2:].tolist()}]}
    prior = {"sideNames": ["bottom"], "inwardNormals": [[0, -1]]}
    evidence = {"sides": {"bottom": {"axis": "y", "scans": [{"scanIndex": 0, "pairs": [pair()]}, {"scanIndex": 1, "pairs": [pair()]}]}}}
    return points, candidates, assembly, evidence, prior


class AssessmentTests(unittest.TestCase):
    def test_darkened_exterior_supports_inward_hypothesis(self):
        result = appearance_hypothesis(pair(), -1)
        self.assertEqual(result["status"], "supports_inward_transition")
        self.assertEqual(result["supportedTransition"], "first")
        self.assertTrue(result["betweenDarkerThanBoth"])
        self.assertEqual(result["features"]["relativeDirectionalVariation"]["preference"], "equal")

    def test_interior_colored_band_supports_outward_hypothesis(self):
        result = appearance_hypothesis(pair(between=(15, 60, 60)), -1)
        self.assertEqual(result["status"], "supports_outward_transition")

    def test_darkness_alone_and_colored_shadow_not_proof(self):
        gray = appearance_hypothesis(pair(interior=(100, 100, 100), between=(30, 30, 30), exterior=(180, 180, 180)), -1)
        self.assertEqual(gray["status"], "insufficient")
        # A colored shadow can resemble the interior; the returned hypothesis
        # is appearance continuation, not a true material or shadow label.
        colored_shadow = appearance_hypothesis(pair(between=(15, 60, 60)), -1)
        self.assertEqual(colored_shadow["reason"], "interior_appearance_continuation")
        self.assertNotIn("shadow", colored_shadow)

    def test_inward_orientation_reverses_roles(self):
        result = appearance_hypothesis(pair(), 1)
        self.assertEqual(result["status"], "supports_outward_transition")
        self.assertEqual(result["supportedTransition"], "first")

    def test_clipped_or_contaminated_does_not_vote(self):
        p = pair(); p["comparisonEligible"] = False
        self.assertEqual(appearance_hypothesis(p, -1)["status"], "insufficient")

    def test_disagreeing_texture_conflicts(self):
        p = pair()
        p["bands"]["between"]["statistics"]["meanAbsoluteAdjacentRGBDifference"] = [8, 8, 8]
        p["bands"]["before"]["statistics"]["meanAbsoluteAdjacentRGBDifference"] = [90 / 70 * 8] * 3
        self.assertEqual(appearance_hypothesis(p, -1)["status"], "conflicting")

    def test_exact_path_attribution_and_unique_scans(self):
        args = fixture(); result = assess_paths(*args)
        self.assertEqual(result["paths"][0]["sides"]["bottom"]["coverage"]["support"], 2)
        self.assertEqual(result["paths"][1]["sides"]["bottom"]["coverage"]["opposition"], 2)
        self.assertEqual(result["comparisons"][0]["pathLinks"]["first"][0]["sourcePositions"], [4])
        args[3]["sides"]["bottom"]["scans"][0]["pairs"].append(pair())
        duplicate = assess_paths(*args)
        self.assertEqual(duplicate["paths"][0]["sides"]["bottom"]["coverage"]["support"], 2)

    def test_opposite_evidence_preserves_spatial_conflict(self):
        args = fixture()
        args[3]["sides"]["bottom"]["scans"][0]["pairs"].append(pair(between=(15, 60, 60)))
        result = assess_paths(*args)
        coverage = result["paths"][0]["sides"]["bottom"]["coverage"]
        self.assertEqual(coverage["conflicting"], 1)
        self.assertEqual(coverage["support"], 1)

    def test_branch_attribution_does_not_vote_all_paths(self):
        args = fixture()
        args[2]["paths"].append({"pathId": 2, "sourceSegmentStartIndices": [0], "points": args[0][:2].tolist()})
        result = assess_paths(*args)
        self.assertEqual(result["comparisons"][0]["hypothesis"]["reason"], "ambiguous_or_missing_path_attribution")
        self.assertEqual(result["paths"][0]["sides"]["bottom"]["coverage"]["support"], 0)

    def test_noded_diagonal_only_attributes_actual_native_endpoint(self):
        points = np.array([[0, 0], [1, 1]])
        candidates = [{"candidateId": 0, "side": "top", "sourcePointStart": 0, "sourcePointStopExclusive": 2}]
        assembly = {"paths": [{"pathId": 0, "sourceSegmentStartIndices": [0], "points": [[0, 0], [.5, .5]]},
                              {"pathId": 1, "sourceSegmentStartIndices": [0], "points": [[.5, .5], [1, 1]]}]}
        lookup, coverage = _membership(points, candidates, assembly)
        self.assertEqual(lookup[(0, 0)][0], {0})
        self.assertEqual(lookup[(0, 1)][1], {1})

    def test_document_interface_and_contradictory_path_is_mixed(self):
        points, candidates, assembly, evidence, prior = fixture()
        evidence["sides"]["bottom"]["scans"][1]["pairs"] = [pair(between=(15, 60, 60))]
        result = assess_paths(points, {"candidates": candidates, "prior": prior}, assembly, evidence)
        self.assertEqual(result["paths"][0]["classification"], "mixed")
        self.assertEqual(result["paths"][0]["sides"]["bottom"]["assessment"], "conflicting")

    def test_partial_same_scan_remains_mixed(self):
        points, candidates, assembly, evidence, prior = fixture()
        points = np.vstack((points, [[0, 5]]))
        candidates[0]["sourcePointStopExclusive"] = 5
        assembly["paths"][0]["sourceSegmentStartIndices"].append(3)
        assembly["paths"][0]["points"].append([0, 5])
        result = assess_paths(points, candidates, assembly, evidence, prior)
        self.assertEqual(result["paths"][0]["sides"]["bottom"]["scans"][0]["outcome"], "mixed")


if __name__ == "__main__":
    unittest.main()
