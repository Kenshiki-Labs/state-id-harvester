import unittest
import numpy as np
from prepare import working_masks


class WorkingAreaTests(unittest.TestCase):
    def test_viewer_rejects_manifest_symlink_before_reading(self):
        import tempfile
        from pathlib import Path
        from viewer import snapshot
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'manifest.json').symlink_to(root/'missing-manifest')
            with self.assertRaisesRegex(ValueError,'symlink'):
                snapshot(root,{},'boundary','registration')

    def fixture(self):
        mask=np.zeros((100,120),bool);mask[20:81,20:101]=True
        # Deliberate top dent must survive untouched.
        mask[20:23,45:48]=False
        q=[[20,20],[100,20],[100,80],[20,80]]
        candidates=[{'candidateId':17,'sideIndex':2,'tangentialSpanFraction':.75,
                     'points':[[x,75+(x==60)] for x in range(30,91)]},
                    {'candidateId':99,'sideIndex':2,'tangentialSpanFraction':.75,
                     'points':[[x,80] for x in range(30,91)]}]
        return mask,q,candidates

    def test_local_correction_preserves_dent_and_endpoints(self):
        mask,q,cs=self.fixture();result,labels,e=working_masks(mask,cs,q,.1)
        np.testing.assert_array_equal(mask[:74],result[:74])
        np.testing.assert_array_equal(mask[:,:30],result[:,:30])
        np.testing.assert_array_equal(mask[:,91:],result[:,91:])
        self.assertTrue(result[75,60]);self.assertFalse(result[75,59])
        self.assertEqual(e['innerCandidateId'],17);self.assertEqual(e['supportedColumnCount'],61)
        self.assertEqual(labels[77,50],3);self.assertEqual(labels[50,50],1)
        self.assertFalse(np.any((labels==1)&~result))

    def test_extra_alternative_remains_ambiguous(self):
        mask,q,cs=self.fixture()
        with self.assertRaises(ValueError):working_masks(mask,cs+[cs[0]],q,.1)

    def test_missing_column_is_not_filled(self):
        mask,q,cs=self.fixture();cs[0]['points']=[p for p in cs[0]['points'] if p[0]!=50]
        result,labels,e=working_masks(mask,cs,q,.1)
        np.testing.assert_array_equal(result[:,50],mask[:,50]);self.assertEqual(labels[77,50],2)
        self.assertEqual(e['supportedColumnCount'],60)

    def test_candidate_order_and_ids_do_not_select_answer(self):
        mask,q,cs=self.fixture();a=working_masks(mask,cs,q,.1)[0]
        cs.reverse();cs[0]['candidateId']=1;cs[1]['candidateId']=2
        np.testing.assert_array_equal(a,working_masks(mask,cs,q,.1)[0])


if __name__=='__main__':unittest.main()
