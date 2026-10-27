"""Reject coherent-but-invalid datasets, not only broken file hashes."""
import copy
import json
import unittest
import test_dataset
from dataset import package_boundary, json_bytes, digest
from validate_dataset import validate_dataset, strict_json


class DatasetValidationTests(unittest.TestCase):
    save_candidate = test_dataset.BoundaryDatasetTests.save_candidate
    def setUp(self):
        test_dataset.BoundaryDatasetTests.setUp(self)
        self.candidate['parameters'].update(seedBandFractionOfShortEdge=.04,iterations=5,rngSeed=0,threads=1)
        self.candidate['implementation'].update(rasterio='1',gdal='1',shapely='2',geos='3',scriptSHA256='a'*64,nativeInputSHA256='b'*64)
        self.save_candidate()
        package_boundary(self.base,self.run,self.out)

    # Only validation-specific methods: base tests run separately.
    def test_dataset_round_trip(self):
        self.assertEqual(validate_dataset(self.out,self.base)['boundaryId'],digest((self.out/'geometry.json').read_bytes()))

    def test_coherent_wrong_ring_length(self):
        m=json.loads((self.out/'manifest.json').read_bytes());m['rings'][0]['lengthSourcePixels']+=1
        (self.out/'manifest.json').write_bytes(json_bytes(m))
        with self.assertRaisesRegex(ValueError,'Ring metadata'): validate_dataset(self.out,self.base)

    def test_traversal_path(self):
        m=json.loads((self.out/'manifest.json').read_bytes());m['artifacts']['mask']['path']='../run/candidate-mask.png'
        (self.out/'manifest.json').write_bytes(json_bytes(m))
        with self.assertRaisesRegex(ValueError,'path'): validate_dataset(self.out,self.base)

    def test_unknown_findings_fail_closed(self):
        a=json.loads((self.out/'assessments.json').read_bytes());a['findings']=[{'conclusion':'pass'}]
        data=json_bytes(a);(self.out/'assessments.json').write_bytes(data)
        m=json.loads((self.out/'manifest.json').read_bytes());m['artifacts']['assessments']['sha256']=digest(data)
        (self.out/'manifest.json').write_bytes(json_bytes(m))
        with self.assertRaisesRegex(ValueError,'Unsupported assessments'): validate_dataset(self.out,self.base)

    def test_duplicate_and_nonfinite_json(self):
        for data in [b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1e999}']:
            with self.assertRaises(ValueError): strict_json(data)

    def test_symlink_artifact(self):
        target=self.out/'mask.png'; target.unlink();target.symlink_to(self.run/'candidate-mask.png')
        with self.assertRaisesRegex(ValueError,'symlink'): validate_dataset(self.out,self.base)


if __name__=='__main__':
    suite=unittest.TestSuite(DatasetValidationTests(name) for name in [
        'test_dataset_round_trip','test_coherent_wrong_ring_length','test_traversal_path',
        'test_unknown_findings_fail_closed','test_duplicate_and_nonfinite_json','test_symlink_artifact'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
