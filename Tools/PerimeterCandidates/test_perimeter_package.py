import json
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from pathlib import Path
import tempfile
import unittest
from PerimeterCandidates.dataset import digest, encode, load_dataset

class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.files={n:b'{}' for n in ('candidates.json','evidence.json','relationships.json','membership.npz')}
        self.manifest={'type':'id_cadastral_perimeter_candidates','schemaVersion':1,
                       'sourceHashes':{'source':'a'*64},'edgeManifestSHA256':'b'*64,
                       'physicalSelection':{'status':'unresolved','selectedCandidateIds':[]},
                       'artifacts':{n:{'bytes':len(v),'sha256':digest(v)} for n,v in self.files.items()}}
        for n,v in self.files.items():(self.root/n).write_bytes(v)
        self.write()
    def write(self):(self.root/'manifest.json').write_bytes(encode(self.manifest))
    def test_immutable_snapshot_and_tamper(self):
        _,files=load_dataset(self.root,{'source':'a'*64},'b'*64)
        (self.root/'evidence.json').write_bytes(b'changed')
        self.assertEqual(files['evidence.json'],b'{}')
        with self.assertRaises(ValueError):load_dataset(self.root)
    def test_lineage(self):
        with self.assertRaises(ValueError):load_dataset(self.root,{'source':'c'*64})
        with self.assertRaises(ValueError):load_dataset(self.root,edge_hash='c'*64)
    def test_forced_selection_rejected(self):
        self.manifest['physicalSelection']['selectedCandidateIds']=[0];self.write()
        with self.assertRaises(ValueError):load_dataset(self.root)
    def test_unexpected_path_rejected(self):
        self.manifest['artifacts']['../leak']={};self.write()
        with self.assertRaises(ValueError):load_dataset(self.root)
    def test_symlink_rejected(self):
        p=self.root/'evidence.json';p.unlink();p.symlink_to(self.root/'candidates.json')
        with self.assertRaises(ValueError):load_dataset(self.root)
