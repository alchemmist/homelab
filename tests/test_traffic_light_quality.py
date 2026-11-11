import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('quality', ROOT/'scripts/build-traffic-light-quality.py')
Q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Q)


class QualityPanelsTest(unittest.TestCase):
    def setUp(self):
        self.d = json.loads(Q.SOURCE.read_text())
        self.p = {p['id']: p for p in self.d['panels']}

    def test_generator_idempotent_and_preserves_every_unrelated_panel(self):
        self.assertEqual(Q.build(self.d), self.d)
        base = copy.deepcopy(self.d)
        base['panels'] = [p for p in base['panels'] if p['id'] not in Q.IDS]
        built = Q.build(base)
        self.assertEqual([p for p in built['panels'] if p['id'] not in Q.IDS], base['panels'])
        self.assertEqual({k:v for k,v in built.items() if k!='panels'}, {k:v for k,v in base.items() if k!='panels'})

    def test_will_not_move_owner_panels_to_force_space(self):
        self.d['panels'][0]['gridPos'] = {'x':12,'y':14,'w':4,'h':4}
        with self.assertRaises(ValueError): Q.build(self.d)

    def test_latest_state_not_last_known_good(self):
        for i in [931,932,933,934,935]:
            p = self.p[i]
            self.assertEqual(p['options']['reduceOptions']['calcs'], ['last'])
            e = p['targets'][0]['expr']
            self.assertIn('or vector(-2)', e)
            self.assertIn('timestamp(', e)
            self.assertIn('up{', e)
            self.assertNotIn('or vector(0)', e)
            self.assertTrue(p['hideTimeOverride'])

    def test_ttft_sample_gate_and_no_false_latency(self):
        p = self.p[932];e=p['targets'][0]['expr']
        self.assertIn('>= 20',e);self.assertIn('vector(-1)',e)
        self.assertIn('[15m]',e);self.assertIn('histogram_quantile(0.95',e)
        self.assertEqual(p['fieldConfig']['defaults']['mappings'][0]['options']['-1']['text'],'Low sample')
        self.assertEqual(p['options']['graphMode'],'none')

    def test_resource_waiting_complete_fresh_inventory(self):
        e=self.p[930]['targets'][0]['expr']
        for token in ['topk by(resource)', 'count by(resource)', 'kube_node_info', 'last_success_timestamp_seconds', 'collector="pressure"', 'timestamp(']:self.assertIn(token,e)
        self.assertEqual(self.p[930]['options']['sizing'],'manual')
        self.assertEqual(self.p[930]['fieldConfig']['defaults']['unit'],'percentunit')

    def test_backup_success_not_restore_claim(self):
        for i in [934,935]:
            p=self.p[i];self.assertIn('NOT proof',p['description'])
            e=p['targets'][0]['expr'];self.assertIn('last_successful_time',e)
            self.assertIn('vector(-3)',e);self.assertIn('vector(-1)',e)
            self.assertEqual(p['options']['graphMode'],'none')
