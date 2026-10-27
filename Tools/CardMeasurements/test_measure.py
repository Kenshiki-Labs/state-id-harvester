import unittest
import numpy as np
from shapely.geometry import box, Polygon
from measure import scan, intersect, unit_perimeter
I=np.eye(3)
class MeasurementTests(unittest.TestCase):
    def test_every_center_and_edge(self):
        a=scan(box(1,1,4,3),6,5,'x',I,I)
        np.testing.assert_array_equal(a['scans'][:,0],np.arange(11)/2)
        self.assertEqual(a['scans'][3,3],3)
        self.assertEqual(a['scans'][0,1],0)
        self.assertEqual(a['scans'][2,1],4)
    def test_hole_not_collapsed(self):
        p=Polygon([(0,0),(6,0),(6,6),(0,6)],holes=[[(2,2),(4,2),(4,4),(2,4)]])
        s=scan(p,6,6,'x',I,I)['scans'][5]
        self.assertEqual(s[1],2);self.assertEqual(s[3],6);self.assertEqual(s[4],4)
    def test_dent_all_rows(self):
        p=Polygon([(0,0),(6,0),(6,6),(0,6),(0,4),(1,4),(1,2),(0,2)])
        s=scan(p,6,6,'x',I,I)['scans']
        self.assertEqual(s[3,3],6);self.assertEqual(s[5,3],5);self.assertEqual(s[9,3],6)
    def test_mm_and_source_endpoint_mapping(self):
        mm=np.diag([.02,.02,1]);s=np.array([[2,0,3],[0,2,4],[0,0,1]])
        r=intersect(box(0,0,3,4),[-1,-4/3],[4,16/3],s,mm)[0]
        self.assertAlmostEqual(r[4],5);self.assertAlmostEqual(r[5],.1)
        np.testing.assert_allclose(r[6:10],[3,4,9,12])
    def test_tangent(self):
        r=intersect(box(0,0,2,2),[-1,1],[1,-1],I,I)
        self.assertEqual(len(r),1);self.assertEqual(r[0][-1],1)
    def test_all_unit_vertices(self):
        p={'type':'Polygon','coordinates':[[[0,0],[3,0],[3,2],[0,2],[0,0]]]}
        points,r=unit_perimeter(p);self.assertEqual(len(points),10)
        self.assertEqual(len(np.unique(points,axis=0)),10)
if __name__=='__main__':unittest.main()

from models import fit_radius, checks
class ModelTests(unittest.TestCase):
    def test_radius_uses_curve_and_straight_support(self):
        r=3.;t=np.linspace(np.pi,1.5*np.pi,90)
        arc=np.column_stack((r+r*np.cos(t),r+r*np.sin(t)))
        lines=np.array([[0,v] for v in np.linspace(r,20,80)]+[[u,0] for u in np.linspace(r,30,100)])
        self.assertAlmostEqual(fit_radius(np.vstack((arc,lines)))['radiusMillimeters'],r,places=8)
    def test_345_detects_skew(self):
        rect=np.array([[0.,0],[10,0],[10,8],[0,8]])
        self.assertLess(max(abs(c['residualFrom5Millimeters']) for c in checks(rect)),1e-12)
        rect[2,0]+=2
        self.assertGreater(max(abs(c['residualFrom5Millimeters']) for c in checks(rect)),.1)

from measure import validate_files
from CardEdges.dataset import digest, json_bytes, npy_bytes
class AdmissionTests(unittest.TestCase):
    def test_model_rejects_artifact_traversal_before_reading(self):
        import tempfile
        from pathlib import Path
        from models import run
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            manifest={'sourceHashes':{},'boundaryId':'test','rectificationManifestSHA256':'test',
                      'artifacts':{'../does-not-exist':{}}}
            (root/'manifest.json').write_bytes(json_bytes(manifest))
            with self.assertRaisesRegex(ValueError,'artifact path'):
                run(root,root/'registration',root/'output')
            self.assertFalse((root/'output').exists())

    def fixture(self):
        files={}
        for f in ['source','rectified']:
            for a in ['x','y']:
                for k,v in scan(box(0,0,3,2),3,2,a,I,I).items():files[f'{f}-{a}-{k}.npy']=npy_bytes(v)
        files['perimeter.npy']=npy_bytes(np.zeros((0,8)));files['diagonals.json']=json_bytes({})
        m={'schemaVersion':1,'type':'id_cadastral_scanline_measurements','scanStepPixels':.5,'method':'shapely_intersection_full_grid','processing':{'skippedRows':0,'skippedColumns':0,'smoothing':False,'newFitting':False},'grids':{f:{'width':3,'height':2} for f in ['source','rectified']}}
        m['artifacts']={n:{'sha256':digest(b),'bytes':len(b)} for n,b in files.items()};files['manifest.json']=json_bytes(m)
        return m,files
    def test_incomplete_rows_rejected_even_with_updated_hash(self):
        import io
        m,f=self.fixture();validate_files(f);n='source-x-scans.npy';v=np.load(io.BytesIO(f[n]));f[n]=npy_bytes(v[:-1]);m['artifacts'][n]={'sha256':digest(f[n]),'bytes':len(f[n])};f['manifest.json']=json_bytes(m)
        with self.assertRaisesRegex(ValueError,'Incomplete'):validate_files(f)
    def test_fabricated_distance_rejected(self):
        import io
        m,f=self.fixture();n='rectified-x-intervals.npy';v=np.load(io.BytesIO(f[n]));v[0,4]+=1;f[n]=npy_bytes(v);m['artifacts'][n]={'sha256':digest(f[n]),'bytes':len(f[n])};f['manifest.json']=json_bytes(m)
        with self.assertRaisesRegex(ValueError,'Inconsistent'):validate_files(f)
