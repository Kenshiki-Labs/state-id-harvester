import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from run import admitted_bytes, validate_classes, validate_labels
import report


class InferenceAdmissionTests(unittest.TestCase):
    def test_hash_binds_returned_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'model';path.write_bytes(b'first')
            data=admitted_bytes(path,hashlib.sha256(b'first').hexdigest())
            path.write_bytes(b'second')
            self.assertEqual(data,b'first')
            with self.assertRaises(ValueError):admitted_bytes(path,hashlib.sha256(b'first').hexdigest())

    def test_nonintegral_or_nonfinite_labels_rejected(self):
        for values in [np.array([[1.5]]),np.array([[np.nan]]),np.array([[46]]),np.array([[-1]])]:
            with self.subTest(values=values),self.assertRaises(ValueError):validate_labels(values,(1,1))

    def test_class_indices_must_match_array_order(self):
        classes=[dict(model_index=i,taxonomy_id=i,name=str(i)) for i in range(46)]
        validate_classes(classes)
        classes[0]['model_index']=1
        with self.assertRaises(ValueError):validate_classes(classes)

    def test_report_preserves_input_and_rejects_existing_output(self):
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
            root=Path(d);materials=root/'materials';materials.mkdir();working=root/'working';working.mkdir()
            source=root/'source.png';Image.fromarray(np.zeros((2,3,3),np.uint8)).save(source)
            source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
            for name,array in [('labels.png',np.zeros((2,3),np.uint8)),
                               ('materials.png',np.zeros((2,3,3),np.uint8)),
                               ('overlay.png',np.zeros((2,3,3),np.uint8))]:Image.fromarray(array).save(materials/name)
            classes=[dict(model_index=i,taxonomy_id=i,name=str(i),pixels=6 if i==0 else 0,
                          fraction=1 if i==0 else 0,rgb=[0,0,0]) for i in range(46)]
            manifest=dict(schema='apple_dms_materials_v1',source=str(source),source_sha256=source_hash,
                          width=3,height=2,pixels=6,elapsed_seconds=1,classes=classes,
                          artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in materials.iterdir()})
            (materials/'manifest.json').write_text(json.dumps(manifest))
            region=working/'source-labels.png';Image.fromarray(np.array([[0,1,1],[0,2,3]],np.uint8)).save(region)
            (working/'manifest.json').write_text(json.dumps(dict(schemaVersion=1,type='id_cadastral_interior_working_area',
                sourceHashes={'browser-viewer/original.png':source_hash},artifacts={region.name:dict(sha256=hashlib.sha256(region.read_bytes()).hexdigest())})))
            before={p.name:p.read_bytes() for p in materials.iterdir()}
            args=['report.py','--result',str(materials),'--regions',str(region),'--output',str(root/'report')]
            with patch.object(sys,'argv',args):report.main()
            self.assertEqual(before,{p.name:p.read_bytes() for p in materials.iterdir()})
            self.assertTrue((root/'report'/'index.html').is_file())
            summary=json.loads((root/'report'/'region-summary.json').read_text())
            self.assertEqual(sum(r['pixels'] for r in summary['summaries']),6)
            with patch.object(sys,'argv',args),self.assertRaises(FileExistsError):report.main()


if __name__=='__main__':unittest.main()
