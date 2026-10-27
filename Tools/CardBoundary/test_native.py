"""Contract tests: no resolution fallback and exact pixel-edge geometry."""
import inspect,json,subprocess,sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from rasterio.features import shapes,rasterize
from rasterio import Affine
import refine

class NativeContractTests(unittest.TestCase):
    def test_no_resize_api_or_option(self):
        source=inspect.getsource(refine)
        self.assertNotIn('cv2.resize',source)
        self.assertNotIn('--max-side',source)
        p=subprocess.run([sys.executable,str(Path(refine.__file__)),'baseline','output','--max-side','100'],capture_output=True)
        self.assertEqual(p.returncode,2)
        self.assertIn(b"unrecognized arguments: --max-side 100",p.stderr)
    def test_exact_pixel_edge_roundtrip(self):
        mask=np.zeros((9,11),np.uint8);mask[2:7,3:9]=1;mask[2,3]=0
        transform=Affine.identity()
        polygons=[g for g,v in shapes(mask,mask=mask.astype(bool),transform=transform,connectivity=4) if v==1]
        actual=rasterize([(g,1) for g in polygons],out_shape=mask.shape,transform=transform,dtype='uint8')
        np.testing.assert_array_equal(mask,actual)
    def test_degenerate_prior_fails_before_segmentation(self):
        for corners in [[(2,2),(8,2),(2,8),(2,2)],[(2,2),(5,2),(8,2),(2,8)]]:
            with self.subTest(corners=corners), tempfile.TemporaryDirectory() as directory:
                meta={'derivation':{'id1Geometry':{'sourceCorners':[{'x':x,'y':y} for x,y in corners]}}}
                with patch.object(refine,'load_native',return_value=(np.zeros((12,12,3),dtype=np.uint8),meta,{})), patch.object(refine,'segment_native') as segment:
                    result=refine.run(Path(directory),Path(directory)/'failed',.04)
                self.assertEqual(result['status'],'failed')
                segment.assert_not_called()

    def test_nonfinite_failure_is_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'failed'
            result=refine.run(Path(directory),out,float('nan'))
            self.assertEqual(result['status'],'failed')
            self.assertIsNone(result['parameters']['seedBandFractionOfShortEdge'])
            text=(out/'candidate.json').read_text()
            self.assertNotIn('NaN',text)
            self.assertIsNone(json.loads(text)['geometry'])

    def test_failed_run_has_no_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'failed'
            result=refine.run(Path(directory),out,-1)
            self.assertEqual(result['status'],'failed')
            self.assertIsNone(result['geometry'])
            self.assertFalse((out/'candidate-mask.png').exists())
            self.assertEqual(json.loads((out/'candidate.json').read_text())['status'],'failed')

if __name__=='__main__':unittest.main()
