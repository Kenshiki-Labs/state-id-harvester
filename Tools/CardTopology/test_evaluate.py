import unittest
import numpy as np
from shapely.geometry import Polygon
from Tools.CardTopology.evaluate import audit_graph, window_inventory, edge_density, audit_line_coverage, original_chain_endings

class ReviewTests(unittest.TestCase):
    def test_incidence_loop_and_disconnected_components(self):
        nodes = np.array([[0,0],[1,0],[5,5]],float)
        paths = np.array([[0,1],[2,2]])
        result = audit_graph(nodes, paths, np.array([1,1,2]), np.array([4,4,9]))
        self.assertEqual(result['cycleRank'],1)
        self.assertEqual(result['selfLoopPaths'],1)
        self.assertEqual(result['connectedComponents'],2)
    def test_wrong_degree_fails(self):
        with self.assertRaisesRegex(ValueError,'incidence'):
            audit_graph(np.zeros((2,2)),np.array([[0,1]]),np.array([1,2]),np.array([0,0]))
    def test_wrong_partition_fails(self):
        with self.assertRaisesRegex(ValueError,'partition'):
            audit_graph(np.zeros((2,2)),np.array([[0,1]]),np.array([1,1]),np.array([0,1]))
    def test_window_does_not_invent_endpoints_at_crop(self):
        arrays={'nodes':np.array([[0,0],[8,0],[4,3]],float),'degrees':np.array([1,1,3]),'node_components':np.array([0,0,0])}
        faces=[Polygon([(1,1),(2,1),(2,2),(1,2)]),Polygon([(0,0),(9,0),(9,9),(0,9)])]
        record,keep,ids=window_inventory(arrays,faces,(1,1,5,5))
        self.assertEqual(record['endpoints'],0)
        self.assertEqual(record['junctions'],1)
        self.assertEqual(record['facesContained'],1)
        self.assertEqual(record['facesIntersecting'],2)
    def test_density_deduplicates_shared_points(self):
        mask=np.array([[1,1],[0,0]],np.uint8)
        result=edge_density(np.array([[0,0],[0,0],[1,1]]),mask)
        self.assertEqual(result['retainedPointCount'],3)
        self.assertEqual(result['uniqueEdgePixelCount'],2)
        self.assertEqual(result['inside']['density'],.5)
        self.assertEqual(result['outside']['density'],.5)
    def test_singletons_and_near_closures_are_not_closed(self):
        p=np.array([[9,9],[0,0],[1,0],[1,1],[0,1],[4,4],[5,4],[5,5],[4,4]])
        r=original_chain_endings(p,np.array([0,1,5,9]))
        self.assertEqual(r['singletonChains'],1)
        self.assertEqual(r['exactClosedChainsWithAtLeastThreePoints'],1)
        self.assertEqual(r['distinctEndsOnePixelApart'],1)
    def test_coverage_rejects_connector(self):
        p=np.array([[0,0],[1,0],[3,0],[4,0]],float)
        with self.assertRaisesRegex(ValueError,'differs'):
            audit_line_coverage(p,np.array([0,2,4]),p,np.array([0,4]))
    def test_nested_loops_and_crossings_euler(self):
        from Tools.CardTopology.audit import audit
        fixtures=[[[[0,0],[1,0],[1,1],[0,1],[0,0]]],
                  [[[0,0],[1,1]],[[0,1],[1,0]]],
                  [[[0,0],[1,0],[2,0],[3,0],[3,1],[3,2],[3,3],[2,3],[1,3],[0,3],[0,2],[0,1],[0,0]],
                   [[1,1],[2,1],[2,2],[1,2],[1,1]]]]
        for chains in fixtures:
            p=np.concatenate(chains);o=np.r_[0,np.cumsum([len(c) for c in chains])]
            arrays,regions,summary,_=audit(p,o)
            result=audit_graph(arrays['nodes'],arrays['path_nodes'],arrays['degrees'],arrays['node_components'])
            self.assertEqual(result['cycleRank'],len(regions['features']))
            audit_line_coverage(p,o,arrays['path_points'],arrays['path_offsets'])
    def test_density_empty_side(self):
        result=edge_density(np.array([[0,0]]),np.ones((2,2),np.uint8))
        self.assertIsNone(result['outside']['density'])

if __name__=='__main__': unittest.main()
