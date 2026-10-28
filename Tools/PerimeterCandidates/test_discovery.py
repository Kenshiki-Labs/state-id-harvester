import unittest
import numpy as np
from Tools.PerimeterCandidates.discovery import discover


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.quad = np.array([[10.5,10.5],[30.5,10.5],[30.5,30.5],[10.5,30.5]])

    def test_alternatives_and_every_point_membership(self):
        chains = [np.array([[x,y] for x in range(12,29)]) for y in (9,10,11)]
        chains.append(np.array([[20,20]]))
        points = np.concatenate(chains)
        offsets = np.r_[0,np.cumsum([len(c) for c in chains])]
        result = discover(points, offsets, self.quad, .1)
        self.assertEqual(result['summary']['candidateCountBySide'], [3,2,0,2])
        self.assertEqual(result['summary']['pointsOutsideAllCorridors'], 1)
        self.assertEqual(result['arrays']['point_side_membership'].shape, (52,4))
        for candidate in result['candidates']:
            if candidate['side'] != 'top':
                continue
            a,b = candidate['sourcePointStart'], candidate['sourcePointStopExclusive']
            np.testing.assert_array_equal(points[a:b], chains[candidate['sourceChainIndex']])

    def test_chain_leaving_corridor_is_split_without_bridge(self):
        points = np.array([[15,10],[15,11],[15,12],[15,13],[16,13],[16,12],[16,11],[16,10]])
        r = discover(points, np.array([0,len(points)]), self.quad, .1)
        self.assertEqual([(c['sourcePointStart'],c['sourcePointStopExclusive']) for c in r['candidates']], [(0,3),(5,8)])
        self.assertTrue(r['candidates'][0]['continuesOutsideCorridorAfter'])
        self.assertTrue(r['candidates'][1]['continuesOutsideCorridorBefore'])

    def test_distinct_chains_never_join(self):
        points = np.array([[15,10],[16,10],[17,10],[18,10]])
        r = discover(points, np.array([0,2,4]), self.quad, .1)
        self.assertEqual([c['pointCount'] for c in r['candidates']], [2,2])

    def test_corner_membership_and_singleton_preserved(self):
        r = discover(np.array([[10,10]]), np.array([0,1]), self.quad, .1)
        self.assertEqual(r['summary']['candidateCountBySide'], [1,0,0,1])
        self.assertEqual(r['summary']['sharedSourceChainsAcrossSides'], [{'sourceChainIndex':0,'sides':[0,3]}])

    def test_all_four_sides(self):
        points = np.array([[20,10],[30,20],[20,30],[10,20]])
        r = discover(points, np.arange(5), self.quad, .1)
        self.assertEqual(r['summary']['candidateCountBySide'], [1,1,1,1])

    def test_translation_changes_no_membership(self):
        points = np.array([[20,10],[30,20],[20,30],[10,20],[20,20]])
        a = discover(points, np.arange(6), self.quad, .1)
        b = discover(points+103, np.arange(6), self.quad+103, .1)
        np.testing.assert_array_equal(a['arrays']['point_side_membership'], b['arrays']['point_side_membership'])

    def test_empty_input_explicit(self):
        r = discover(np.empty((0,2),dtype=int), np.array([0]), self.quad, .1)
        self.assertEqual(r['summary']['candidateCountBySide'], [0]*4)
        self.assertEqual(r['method']['physicalSelection'], 'unresolved')

    def test_reject_invalid_prior_or_input(self):
        for q in (self.quad[::-1], self.quad[[0,2,1,3]], np.zeros((4,2))):
            with self.assertRaises(ValueError):
                discover(np.array([[10,10]]),np.array([0,1]),q,.1)
        for fraction in (0,-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):
                discover(np.array([[10,10]]),np.array([0,1]),self.quad,fraction)
        with self.assertRaises(ValueError):
            discover(np.array([[10,10],[20,10]]),np.array([0,2]),self.quad,.1)

    def test_unsigned_offsets_admitted_only_with_valid_partition(self):
        points = np.array([[15,10],[16,10],[17,10],[18,10]], dtype=np.uint32)
        good = discover(points, np.array([0,2,4], dtype=np.uint64), self.quad, .1)
        self.assertEqual([c['pointCount'] for c in good['candidates']], [2,2])
        for offsets in ([0,2**64-1,4], [0,4,4], [1,4], [0,3]):
            with self.assertRaises(ValueError):
                discover(points,np.array(offsets,dtype=np.uint64),self.quad,.1)

    def test_prior_exclusions_remain_visible_and_never_selected(self):
        points = np.array([[20,7],[20,8],[20,10]])
        offsets = np.arange(4)
        narrow = discover(points, offsets, self.quad, .04)
        wider = discover(points, offsets, self.quad, .2)
        self.assertEqual(narrow['summary']['pointsOutsideAllCorridors'],2)
        self.assertEqual(wider['summary']['pointsOutsideAllCorridors'],0)
        self.assertEqual(narrow['method']['completeness'],'within_prior_corridors')
        self.assertEqual(narrow['method']['physicalSelection'],'unresolved')

    def test_independent_finite_segment_distance_oracle(self):
        # GEOS supplies an independent oracle, including finite corner caps.
        from shapely.geometry import Point, LineString
        points = np.array([[x,y] for x in range(7,34) for y in range(7,34)])
        offsets = np.arange(len(points)+1)
        result = discover(points, offsets, self.quad, .1)
        expected = np.array([[Point(p+.5).distance(LineString([self.quad[s],self.quad[(s+1)%4]])) <= 2
                              for s in range(4)] for p in points])
        np.testing.assert_array_equal(result['arrays']['point_side_membership'],expected)


if __name__ == '__main__':
    unittest.main()
