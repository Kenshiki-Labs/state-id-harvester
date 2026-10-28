import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import serve

class AssemblyRouteTests(unittest.TestCase):
    def test_bound_snapshot_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);data=b'{"paths":[]}'
            manifest={'type':'id_cadastral_path_assembly','schemaVersion':1,
                      'sourceHashes':{'image':'a'*64},'candidateManifestSHA256':'b'*64,
                      'artifacts':{'assembly.json':{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}}}
            (p/'manifest.json').write_text(json.dumps(manifest));(p/'assembly.json').write_bytes(data)
            snap=serve.assembly_snapshot(p,{'image':'a'*64},'b'*64)
            self.assertEqual(snap['/assembly/assembly.json'][0],data)
            with self.assertRaises(ValueError):serve.assembly_snapshot(p,{'image':'a'*64},'c'*64)
            (p/'assembly.json').write_bytes(b'changed')
            self.assertEqual(snap['/assembly/assembly.json'][0],data)
            with self.assertRaises(ValueError):serve.assembly_snapshot(p,{'image':'a'*64},'b'*64)
