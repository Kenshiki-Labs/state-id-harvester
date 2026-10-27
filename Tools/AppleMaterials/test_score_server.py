"""Exercise real loopback routing and immutable admitted score snapshots."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import numpy as np


class ScoreServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();root=Path(cls.temp.name);cls.root=root
        source=Path(__file__).resolve().parent
        # Use the recorded taxonomy to preserve actual UI names in this tiny fixture.
        names=['Plastic, clear','Plastic, non-clear','Paper','Photograph/painting','Glass','Fabric/cloth','Wood','Paint/plaster/enamel']+[f'Other {i}' for i in range(38)]
        np.save(root/'scores.npy',np.broadcast_to(np.arange(46,dtype=np.float32)[:,None,None],(46,2,3)).copy())
        np.save(root/'margin.npy',np.ones((2,3),dtype=np.float32))
        manifest=dict(schema='apple_dms_scores_v1',width=3,height=2,bands=[dict(index=i,name=n) for i,n in enumerate(names)],
                      display_scale=[0,45],margin_display_scale=[0,1],argmax_mismatches=0,
                      artifacts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()})
        (root/'manifest.json').write_text(json.dumps(manifest))
        cls.process=subprocess.Popen([sys.executable,str(source/'serve_scores.py'),'--dataset',str(root),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        selector=selectors.DefaultSelector();selector.register(cls.process.stdout,selectors.EVENT_READ)
        ready=selector.select(timeout=20);selector.close()
        if not ready:
            cls.process.kill();raise RuntimeError('Server failed to start within 20 seconds')
        cls.url=cls.process.stdout.readline().strip()
        if not cls.url.startswith('http://127.0.0.1:'):
            cls.process.kill();raise RuntimeError(cls.process.stderr.read())

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.communicate(timeout=10);cls.temp.cleanup()

    def test_pixel_readout(self):
        with urllib.request.urlopen(self.url+'/pixel?x=2&y=1',timeout=5) as r:
            data=json.load(r)
        self.assertEqual(data['scores'][0]['score'],45)
        self.assertEqual(data['margin'],1)

    def test_bad_coordinate_and_unlisted_path(self):
        for path,code in [('/pixel?x=-1&y=0',400),('/pixel?x=3&y=0',400),('/pixel?x=nan&y=0',400),('/../../etc/passwd',404),('/task-classes.json',404)]:
            with self.assertRaises(urllib.error.HTTPError) as result:
                urllib.request.urlopen(self.url+path,timeout=5)
            self.assertEqual(result.exception.code,code)

    def test_source_mutation_does_not_change_served_scores(self):
        np.save(self.root/'scores.npy',np.zeros((46,2,3),dtype=np.float32))
        with urllib.request.urlopen(self.url+'/pixel?x=0&y=0',timeout=5) as r:
            data=json.load(r)
        self.assertEqual(data['scores'][0]['score'],45)

    def test_controls_and_local_response_headers(self):
        with urllib.request.urlopen(self.url,timeout=5) as r:
            text=r.read().decode();self.assertEqual(r.headers['Cache-Control'],'no-store')
            self.assertEqual(r.headers['X-Content-Type-Options'],'nosniff')
        self.assertIn('id="margin"',text)
        self.assertIn('id="layer"',text)
        self.assertNotIn('Task classifier: not trained',text)


if __name__=='__main__':unittest.main()
