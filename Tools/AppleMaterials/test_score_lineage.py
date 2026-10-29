import hashlib
import json
import unittest
from serve_scores import verify_material_lineage


class ScoreLineageTests(unittest.TestCase):
    def test_scores_bind_to_exact_material_run_and_model(self):
        materials=dict(source_sha256='s',model_sha256='m',upstream_commit='u',width=3,height=2)
        raw=json.dumps(materials).encode();scores={**materials,'baseline_manifest_sha256':hashlib.sha256(raw).hexdigest()}
        verify_material_lineage(scores,raw)
        for field in ('source_sha256','model_sha256','upstream_commit','width','height','baseline_manifest_sha256'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                verify_material_lineage({**scores,field:'other'},raw)
        # Equal decoded values do not authorize substituting a different retained manifest.
        with self.assertRaises(ValueError):verify_material_lineage(scores,json.dumps(materials,indent=2).encode())

if __name__=='__main__':unittest.main()
