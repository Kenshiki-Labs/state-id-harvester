"""Adversarial topology admission fixtures with recomputed artifact hashes."""
import unittest
import json
import numpy as np
import shapely
from audit import audit
from CardTopology.dataset import validate_files
from CardEdges.dataset import digest,json_bytes,npy_bytes


def fixture():
    points=np.array([[0,0],[1,0],[1,1],[0,1],[0,0]],dtype=np.int32)
    arrays,regions,summary,extra=audit(points,np.array([0,5]))
    files={k+'.npy':npy_bytes(v) for k,v in arrays.items()}
    files.update({'regions.geojson':json_bytes(regions),'topology.json':json_bytes(summary)})
    files.update({k+'.wkb':shapely.to_wkb(v) for k,v in extra.items()})
    m={'schemaVersion':1,'type':'id_cadastral_edge_topology','sourceHashes':{'source':'a'*64},'edgeManifestSHA256':'b'*64,'coordinateSystem':{'type':'image_pixel_indices','origin':'top_left','xDirection':'right','yDirection':'down','width':10,'height':10,'pixelCenterOffset':[.5,.5]},'method':{'noding':'shapely.node','components':'scipy.sparse.csgraph.connected_components','faces':'shapely.polygonize_full','intersectionPolicy':'exact_geometric','gapBridging':False,'snapping':False,'simplification':False,'downsampling':False},'summary':summary}
    rehash(files,m)
    return files,m,arrays,regions

def rehash(files,m):
    m['artifacts']={k:{'sha256':digest(v),'bytes':len(v)} for k,v in files.items() if k!='manifest.json'}
    files['manifest.json']=json_bytes(m)

class AdmissionTests(unittest.TestCase):
    def test_admits_and_freezes(self):
        files,*_=fixture();_,arrays,_,_=validate_files(files,{'source':'a'*64},'b'*64)
        self.assertFalse(arrays['path_points'].flags.writeable)
    def test_hash_tamper(self):
        files,*_=fixture();files['degrees.npy']+=b'x'
        with self.assertRaises(ValueError):validate_files(files)
    def test_source_mismatch(self):
        files,*_=fixture()
        with self.assertRaises(ValueError):validate_files(files,{'source':'c'*64})
    def test_rehashed_outside_region(self):
        files,m,a,r=fixture();r=json.loads(json_bytes(r));r['features'][0]['geometry']['coordinates'][0][0]=(100,100)
        files['regions.geojson']=json_bytes(r);rehash(files,m)
        with self.assertRaises(ValueError):validate_files(files)
    def test_rehashed_degree(self):
        files,m,a,r=fixture();a['degrees'][0]+=1;files['degrees.npy']=npy_bytes(a['degrees']);rehash(files,m)
        with self.assertRaises(ValueError):validate_files(files)
    def test_rehashed_offsets(self):
        files,m,a,r=fixture();a['path_offsets'][0]=-1;files['path_offsets.npy']=npy_bytes(a['path_offsets']);rehash(files,m)
        with self.assertRaises(ValueError):validate_files(files)
    def test_wrong_method(self):
        files,m,*_=fixture();m['method']['gapBridging']=True;rehash(files,m)
        with self.assertRaises(ValueError):validate_files(files)
if __name__=='__main__':unittest.main()
