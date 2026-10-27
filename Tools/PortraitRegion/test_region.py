import tempfile
import unittest
from pathlib import Path
import numpy as np
from prepare import footprint,measurements,encoded,digest
from viewer import snapshot

class RegionTests(unittest.TestCase):
    def test_saved_crop_mapping_uses_scale_and_inverse_source_transform(self):
        d=dict(outputPixelWidth=100,outputPixelHeight=100,id1Geometry=dict(outputPixelsPerMillimeter=2,
          cardMillimetersToSource=[3,0,10,0,4,20,0,0,1],sourceToCardMillimeters=[1/3,0,-10/3,0,1/4,-5,0,0,1]))
        ring=footprint(dict(x=2,y=4,width=6,height=8),d)
        self.assertEqual(ring,[[13,28],[22,28],[22,44],[13,44],[13,28]])
        with self.assertRaises(ValueError):footprint(dict(x=99,y=0,width=2,height=2),d)
    def test_unique_pixels_not_duplicate_points_or_display_strokes(self):
        points=np.array([[1,1],[2,1],[2,2],[1,1],[1,2],[4,4]])
        offsets=np.array([0,3,5,6]);ring=[[1,1],[3,1],[3,3],[1,3],[1,1]]
        m=measurements(ring,(5,5),points,offsets)
        self.assertEqual(m['sourcePixelCount'],4);self.assertEqual(m['uniqueEdgePixelCount'],4)
        self.assertEqual(m['edgePixelFraction'],1);self.assertEqual(m['intersectingChainCount'],2)
        self.assertEqual(m['interiorSegmentLengthSourcePixels'],3)
        self.assertEqual(m['directionLengthsSourcePixels']['horizontal'],1)
        self.assertEqual(m['directionLengthsSourcePixels']['vertical'],2)
    def test_no_edges_is_valid_zero_density(self):
        m=measurements([[0,0],[2,0],[2,2],[0,2],[0,0]],(3,3),np.empty((0,2),dtype=int),np.array([0]))
        self.assertEqual(m['sourcePixelCount'],4);self.assertEqual(m['edgePixelFraction'],0)
    def test_server_rejects_other_capture_and_tampered_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=b'fixture';(root/'crop.png').write_bytes(data)
            m=dict(schemaVersion=1,type='retained_portrait_regions',sourceHashes={'source':'a'},edgeManifestSHA256='b',candidates=[],artifacts={'crop.png':dict(sha256=digest(data),bytes=len(data))})
            (root/'manifest.json').write_bytes(encoded(m));routes=snapshot(root,{'source':'a'},'b')
            self.assertEqual(routes['/portraits/crop.png'][0],data)
            with self.assertRaises(ValueError):snapshot(root,{'source':'other'},'b')
            (root/'crop.png').write_bytes(b'changed')
            self.assertEqual(routes['/portraits/crop.png'][0],data)
            with self.assertRaises(ValueError):snapshot(root,{'source':'a'},'b')
if __name__=='__main__':unittest.main()
