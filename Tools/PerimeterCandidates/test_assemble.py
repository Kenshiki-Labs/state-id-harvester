import unittest
import numpy as np
from assemble import assemble


def run(parts):
    points=np.array([p for part in parts for p in part],np.int32).reshape(-1,2)
    offsets=np.r_[0,np.cumsum([len(p) for p in parts])]
    candidates=[{'candidateId':i,'sourcePointStart':int(a),'sourcePointStopExclusive':int(b),
                 'sourceChainIndex':i,'sideIndex':i%4,'points':points[a:b].tolist()}
                for i,(a,b) in enumerate(zip(offsets[:-1],offsets[1:]))]
    return assemble(points,offsets,candidates)

class AssemblyTests(unittest.TestCase):
    def test_join_and_dent_preserved(self):
        parts=[[(0,0),(1,0),(2,1)],[(2,1),(3,0),(4,0)]]
        r=run(parts);self.assertEqual(len(r['paths']),1)
        self.assertEqual(set(map(tuple,r['paths'][0]['points'])),{(0,0),(1,0),(2,1),(3,0),(4,0)})
        self.assertEqual(r['summary']['openEndCount'],2)
    def test_branch_all_continuations(self):
        r=run([[(0,1),(1,1)],[(1,1),(2,1)],[(1,1),(1,2)]])
        self.assertEqual(len(r['paths']),3)
        branch=next(n for n in r['nodes'] if n['kind']=='branch')
        self.assertEqual(len(branch['incidentPathIds']),3)
    def test_gap_not_closed(self):
        r=run([[(0,0),(1,0)],[(2,0),(3,0)]])
        self.assertEqual(len(r['paths']),2);self.assertEqual(r['summary']['openEndCount'],4)
    def test_loop(self):
        r=run([[(0,0),(1,0)],[(1,0),(1,1)],[(1,1),(0,1)],[(0,1),(0,0)]])
        self.assertEqual(r['summary']['closedPathCount'],1)
        self.assertEqual(r['summary']['openEndCount'],0)
    def test_crossing_exact(self):
        r=run([[(0,0),(1,1)],[(0,1),(1,0)]])
        n=next(n for n in r['nodes'] if n['kind']=='branch')
        self.assertEqual(n['point'],[.5,.5]);self.assertEqual(n['degree'],4)
    def test_singleton(self):
        r=run([[(2,3)]])
        self.assertEqual(r['isolatedPoints'],[[2.,3.]])
    def test_no_candidates(self):
        r=run([]);self.assertEqual(r['summary']['status'],'no_candidates')
    def test_altered_candidate_rejected(self):
        with self.assertRaises(ValueError):
            assemble(np.array([[0,0],[1,0]],np.int32),np.array([0,2]),[{'sourcePointStart':0,'sourcePointStopExclusive':2,'sourceChainIndex':0,'points':[[0,0],[2,0]]}])
