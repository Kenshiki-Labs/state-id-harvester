import unittest
from task_contract import load_contract, contract_hash, validate_task_model


class TaskContractTests(unittest.TestCase):
    def valid(self):
        return dict(task_schema='credential_scene_task_v1',
                    task_contract_sha256=contract_hash(),
                    class_keys=[c['key'] for c in load_contract()['classes']],
                    weights_sha256='a'*64, training_manifest_sha256='b'*64,
                    evaluation_manifest_sha256='c'*64)

    def test_apple_material_output_rejected(self):
        with self.assertRaises(ValueError):
            validate_task_model({'schema': 'apple_dms_scores_v1', 'bands': list(range(46))})

    def test_reordered_channels_rejected(self):
        m=self.valid();m['class_keys'].reverse()
        with self.assertRaises(ValueError): validate_task_model(m)

    def test_missing_training_evidence_rejected(self):
        m=self.valid();del m['training_manifest_sha256']
        with self.assertRaises(ValueError): validate_task_model(m)

    def test_matching_contract_admitted(self):
        m=self.valid();self.assertEqual(validate_task_model(m),m)

    def test_unlabeled_is_not_unresolved(self):
        c=load_contract()
        self.assertNotIn(c['unlabeled_value'],[x['id'] for x in c['classes']])
        self.assertTrue(set(a['key'] for a in c['attributes']).isdisjoint(x['key'] for x in c['classes']))


if __name__=='__main__': unittest.main()
