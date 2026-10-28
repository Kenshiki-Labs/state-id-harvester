"""Export admission and failure receipts, independently of image-algorithm tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from ingest import ingest


def sha(data):return hashlib.sha256(data).hexdigest()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.export=self.root/'export';self.export.mkdir()
        self.capture='1FA2E4EA-CC73-4276-B2E5-92E7F13BEB49'
        self.source=self.export/self.capture;self.source.mkdir();self.output=self.root/'prepared'
        geometry=dict(captureID=self.capture,sourceSHA256=sha(b'camera'),derivation=dict(sourceSHA256=sha(b'camera'),outputSHA256=sha(b'rectified')))
        manifest=dict(captureID=self.capture,profile='License front',fidelity=dict(uniformTypeIdentifier='public.heic',sha256=sha(b'camera')))
        payloads={'original.bin':b'camera','rectified.png':b'rectified','geometry.json':json.dumps(geometry).encode(),'capture-manifest.json':json.dumps(manifest).encode()}
        self.entry=dict(captureID=self.capture,profile='License front')
        for name,key in [('original.bin','sourceSHA256'),('rectified.png','derivativeSHA256'),('geometry.json','geometrySHA256'),('capture-manifest.json','manifestSHA256')]:
            (self.source/name).write_bytes(payloads[name]);self.entry[key]=sha(payloads[name])
        self.index=dict(kind='sdk_viewer_export',schemaVersion=1,captures=[self.entry]);self.save()
        self.calls=[]

    def save(self):(self.export/'index.json').write_text(json.dumps(self.index))

    def run_stage(self,command,**kwargs):
        self.calls.append(command);return subprocess.CompletedProcess(command,0)

    def test_explicit_capture_keeps_exact_bytes_and_records_all_preparation_stages(self):
        base,boundary=ingest(self.export,self.capture.lower(),self.output,'/usr/bin/python3',self.run_stage)
        self.assertEqual((base/'front-original.heic').read_bytes(),b'camera')
        self.assertEqual((base/'front-geometry.json').read_bytes(),(self.source/'geometry.json').read_bytes())
        self.assertEqual(boundary,base/'boundary-v1')
        receipt=json.loads((base/'import.json').read_text())
        self.assertTrue(receipt['preparationComplete']);self.assertEqual(len(receipt['stages']),5)
        self.assertEqual(receipt['capture'],self.entry)
        with self.assertRaisesRegex(ValueError,'Output exists'):
            ingest(self.export,self.capture,self.output,'/usr/bin/python3',self.run_stage)

    def test_changed_bytes_rejected_before_any_analysis_or_output(self):
        (self.source/'original.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            ingest(self.export,self.capture,self.output,'/usr/bin/python3',self.run_stage)
        self.assertFalse(self.output.exists());self.assertFalse(self.calls)

    def test_missing_and_duplicate_selection_rejected(self):
        for captures in ([],[self.entry,self.entry]):
            self.index['captures']=captures;self.save()
            with self.assertRaisesRegex(ValueError,'exactly one'):
                ingest(self.export,self.capture,self.output,'/usr/bin/python3',self.run_stage)
        self.assertFalse(self.output.exists())

    def test_rehashed_geometry_for_another_capture_is_rejected(self):
        path=self.source/'geometry.json';geometry=json.loads(path.read_text());geometry['captureID']='B141D618-C3A9-4FF8-85FA-369415EAE10B'
        path.write_text(json.dumps(geometry));self.entry['geometrySHA256']=sha(path.read_bytes());self.save()
        with self.assertRaisesRegex(ValueError,'identity mismatch'):
            ingest(self.export,self.capture,self.output,'/usr/bin/python3',self.run_stage)
        self.assertFalse(self.output.exists())

    def test_failed_preparation_stops_and_leaves_incomplete_receipt(self):
        def failure(command,**kwargs):return subprocess.CompletedProcess(command,7)
        with self.assertRaisesRegex(ValueError,'Spatial preparation failed'):
            ingest(self.export,self.capture,self.output,'/usr/bin/python3',failure)
        receipt=json.loads((self.output/'import.json').read_text())
        self.assertFalse(receipt['preparationComplete']);self.assertEqual(len(receipt['stages']),1)
        self.assertEqual(receipt['stages'][0]['exitCode'],7)

if __name__=='__main__':unittest.main()
