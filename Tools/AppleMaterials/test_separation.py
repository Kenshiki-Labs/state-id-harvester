import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from evidence import snapshot, publish_staged, strict_json
from metrics import measure, stats


class SeparationTests(unittest.TestCase):
    def fixture(self):
        scores=np.array([[[3,3,0,0],[3,3,0,0]],[[0,0,3,3],[0,0,3,3]]],dtype=np.float32)
        labels=scores.argmax(0).astype(np.uint8)
        regions=np.where(labels==0,1,0).astype(np.uint8)
        inside=labels==0
        meta={'source_sha256':'a'*64,'bands':[dict(index=i,name=str(i),taxonomy_id=i) for i in range(2)]}
        return scores,labels,regions,inside,meta

    def test_exact_separation_and_every_crossing(self):
        report,contrast,target=measure(*self.fixture())
        self.assertEqual(report['target_map']['iou'],1)
        self.assertEqual(report['distribution_total_variation'],1)
        self.assertEqual(report['boundary_adjacent_pairs']['contrast_inside_minus_outside']['count'],2)
        self.assertEqual(report['regions']['shadow']['pixels'],0)
        self.assertIsNone(report['regions']['shadow']['contrast']['mean'])
        json.dumps(report,allow_nan=False)

    def test_same_pattern_is_valid_negative_observation(self):
        s,l,r,i,m=self.fixture();s[0]=4;s[1]=0;l[:]=0
        report,contrast,_=measure(s,l,r,i,m)
        self.assertFalse(report['distinct_dominant_patterns'])
        self.assertTrue((contrast==0).all())
        json.dumps(report,allow_nan=False)

    def test_label_mismatch_rejected(self):
        s,l,r,i,m=self.fixture();l[0,0]=1
        with self.assertRaisesRegex(ValueError,'disagree'):measure(s,l,r,i,m)

    def test_nonfinite_unused_channel_rejected(self):
        s,l,r,i,m=self.fixture();s[1,0,0]=np.nan
        with self.assertRaisesRegex(ValueError,'Nonfinite'):measure(s,l,r,i,m)

    def test_invalid_band_order_rejected(self):
        s,l,r,i,m=self.fixture();m['bands'].reverse()
        with self.assertRaisesRegex(ValueError,'identity'):measure(s,l,r,i,m)

    def test_float_regions_rejected(self):
        s,l,r,i,m=self.fixture()
        with self.assertRaisesRegex(ValueError,'uint8'):measure(s,l,r.astype(float),i,m)

    def test_empty_exterior_rejected(self):
        s,l,r,i,m=self.fixture();i[:]=True
        with self.assertRaisesRegex(ValueError,'Both'):measure(s,l,r,i,m)

    def test_finite_mean_does_not_overflow(self):
        self.assertTrue(np.isfinite(stats(np.full(20,1e38,dtype=np.float32))['mean']))

    def test_snapshot_is_independent_of_source_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=b'original'
            (root/'file').write_bytes(data)
            manifest={'artifacts':{'file':hashlib.sha256(data).hexdigest()}}
            (root/'manifest.json').write_text(json.dumps(manifest))
            with snapshot(root,manifest,['file']) as admitted:
                (root/'file').write_bytes(b'changed')
                self.assertEqual((admitted/'file').read_bytes(),data)

    def test_snapshot_rejects_path_escape_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'file').write_bytes(b'a')
            (root/'link').symlink_to(root/'file')
            for name in ['../file','link']:
                m={'artifacts':{name:hashlib.sha256(b'a').hexdigest()}}
                (root/'manifest.json').write_text(json.dumps(m))
                with self.assertRaises(ValueError):
                    with snapshot(root,m,[name]):pass

    def test_publish_preserves_existing_empty_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'out';out.mkdir();stage=root/'stage';stage.mkdir()
            (stage/'result').write_bytes(b'result')
            with self.assertRaises(FileExistsError):publish_staged(stage,out)
            self.assertEqual(list(out.iterdir()),[])

    def test_nonfinite_and_duplicate_json_rejected(self):
        for data in ['{"a":NaN}','{"a":1,"a":2}']:
            with self.assertRaises(ValueError):strict_json(data)


if __name__=='__main__':unittest.main()
