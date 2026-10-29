import unittest
import numpy as np
from prepare_regula import project_geometry,registration_correlation

class ProviderRegionTests(unittest.TestCase):
    def geometry(self):
        return dict(left=10,top=20,width=30,height=40,documentWidth=100,documentHeight=80,
          documentPosition=[dict(x=0,y=80),dict(x=100,y=80),dict(x=100,y=0),dict(x=0,y=0)])
    def test_provider_raster_and_position_have_different_vertical_origins(self):
        matrix,ring=project_geometry(self.geometry(),(100,80))
        np.testing.assert_allclose(matrix,np.eye(3),atol=1e-10)
        self.assertEqual(ring,[[10,20],[40,20],[40,60],[10,60],[10,20]])
    def test_wrong_registration_does_not_match_pixels(self):
        rgb=np.random.default_rng(123).integers(0,256,(80,100,3),dtype=np.uint8)
        self.assertAlmostEqual(registration_correlation(rgb,rgb,np.eye(3)),1)
        self.assertLess(registration_correlation(rgb,rgb,np.array([[1,0,0],[0,-1,80],[0,0,1]],float)),.98)
    def test_no_silent_clipping_or_crossed_document_corners(self):
        g=self.geometry();g['width']=200
        with self.assertRaises(ValueError):project_geometry(g,(100,80))
        g=self.geometry();g['documentPosition'][1],g['documentPosition'][2]=g['documentPosition'][2],g['documentPosition'][1]
        with self.assertRaises(ValueError):project_geometry(g,(100,80))
        g=self.geometry();g['documentPosition'][0]['x']=-1
        with self.assertRaises(ValueError):project_geometry(g,(100,80))
if __name__=='__main__':unittest.main()
