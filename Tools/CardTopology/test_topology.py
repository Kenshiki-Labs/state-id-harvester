import unittest
import numpy as np
from audit import audit

def run(chains):
    return audit(np.array([p for c in chains for p in c],dtype=np.int32),np.r_[0,np.cumsum([len(c) for c in chains])])

class TopologyTests(unittest.TestCase):
    def test_open(self):
        a,r,s,_=run([[(0,0),(1,0),(2,0)]])
        self.assertEqual(s['endpointCount'],2);self.assertEqual(s['closedRegionCount'],0)
    def test_closed(self):
        _,r,s,_=run([[(0,0),(1,0),(1,1),(0,1),(0,0)]])
        self.assertEqual(s['closedRegionCount'],1);self.assertEqual(s['cycleRank'],1)
    def test_t_junction(self):
        _,_,s,_=run([[(0,1),(1,1),(2,1)],[(1,1),(1,0)]])
        self.assertEqual(s['junctionCount'],1);self.assertEqual(s['endpointCount'],3)
    def test_crossing(self):
        a,_,s,_=run([[(0,0),(1,1)],[(0,1),(1,0)]])
        self.assertEqual(s['sharedVertexComponentCount'],2);self.assertEqual(s['planarComponentCount'],1)
        self.assertEqual(s['introducedIntersectionNodeCount'],1);self.assertTrue(np.any(np.all(a['nodes']==[.5,.5],axis=1)))
    def test_diagonal_neighbors_not_joined(self):
        _,_,s,_=run([[(0,0),(1,0)],[(2,1),(3,1)]])
        self.assertEqual(s['planarComponentCount'],2)
    def test_adjacent_end_gap_not_closed(self):
        _,_,s,_=run([[(0,0),(1,0),(1,1),(0,1)]])
        self.assertEqual(s['closedRegionCount'],0)
    def test_duplicate_segments(self):
        a,_,s,_=run([[(0,0),(1,0)],[(1,0),(0,0)]])
        self.assertEqual(s['endpointCount'],2);self.assertEqual(s['cycleRank'],0)
        self.assertEqual(len(a['path_source_segments']),2)
    def test_singleton_contact(self):
        _,_,s,_=run([[(0,0),(1,0),(2,0)],[(1,0)]])
        self.assertEqual(s['isolatedNodeCount'],0);self.assertEqual(s['planarComponentCount'],1)
        self.assertEqual(s['endpointCount'],2)
    def test_singleton_diagonal_contact(self):
        _,_,s,_=run([[(0,0),(1,1),(2,2)],[(1,1)]])
        self.assertEqual(s['isolatedNodeCount'],0);self.assertEqual(s['planarComponentCount'],1)
    def test_only_singletons(self):
        _,_,s,_=run([[(0,0)],[(1,1)]])
        self.assertEqual(s['isolatedNodeCount'],2);self.assertEqual(s['closedRegionCount'],0)
    def test_empty(self):
        _,_,s,_=audit(np.empty((0,2),dtype=np.int32),np.array([0],dtype=np.int64))
        self.assertEqual(s['nodeCount'],0);self.assertEqual(s['planarComponentCount'],0)
    def test_input_unchanged(self):
        p=np.array([[0,0],[1,0],[1,1]],dtype=np.int32);before=p.copy()
        audit(p,np.array([0,3]));np.testing.assert_array_equal(p,before)
if __name__=='__main__':unittest.main()
