import copy
import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

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

    def test_writer_preserves_existing_format_and_is_stable(self):
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'dashboard.json'
            with patch.object(Q,'SOURCE',path):
                Q.write(self.d);first=path.read_bytes()
                Q.write(Q.build(json.loads(first)));self.assertEqual(path.read_bytes(),first)
            for p in self.d['panels']:
                if p['id'] not in Q.IDS:
                    formatted='\n'.join('    '+line for line in json.dumps(p,ensure_ascii=False,indent=2).splitlines())
                    self.assertIn(formatted,first.decode())

    def test_preserves_future_manual_network_geometry(self):
        panel=next(p for p in self.d['panels'] if p['id']==931)
        panel['gridPos']={'x':12,'y':14,'w':5,'h':4}
        built=Q.build(self.d)
        self.assertEqual(next(p for p in built['panels'] if p['id']==931)['gridPos'],panel['gridPos'])

    def test_will_not_move_owner_panels_to_force_space(self):
        self.d['panels'][0]['gridPos'] = {'x':12,'y':14,'w':4,'h':4}
        with self.assertRaises(ValueError): Q.build(self.d)

    def test_backup_latest_state_not_last_known_good(self):
        for i in [934,935]:
            p = self.p[i]
            self.assertEqual(p['options']['reduceOptions']['calcs'], ['last'])
            e = p['targets'][0]['expr']
            for token in ['or vector(-2)', 'timestamp(', 'up{']:
                self.assertIn(token, e)
            self.assertNotIn('or vector(0)', e)

    def test_native_network_not_fabricated_object_or_image_counts(self):
        for i in [931,932]:
            p=self.p[i];e=p['targets'][0]['expr']
            self.assertEqual(p['type'],'stat')
            for token in ['container_network_receive_bytes_total', 'container_network_transmit_bytes_total', '[5m]', 'timestamp(', 'kube_pod_info', '2*count(', 'metrics/cadvisor', 'label_join(']:
                self.assertIn(token,e)
            self.assertNotIn('or vector(0)',e)
            self.assertEqual(p['options']['reduceOptions']['calcs'],['last'])
            self.assertIn('or on(direction)',e);self.assertIn('vector(-2)',e)
            self.assertTrue(p['hideTimeOverride'])
            self.assertIn('NOT object or OCI counts',p['description'])

    def test_business_http_errors_not_infrastructure_rps(self):
        e=self.p[930]['targets'][0]['expr']
        for token in ['topk(3', 'code=~"5.."', '[1h]', '0*max by(exported_service)', 'timestamp(']:
            self.assertIn(token,e)
        self.assertNotIn('grafana',e);self.assertNotIn('vpn',e)
        self.assertIn('missing backend omitted',self.p[930]['description'])

    def test_no_new_blue_and_no_ai_dominance(self):
        for i in Q.IDS & self.p.keys():
            p=self.p[i]
            self.assertNotIn('#5794F2',json.dumps(p))
            self.assertNotIn('vllm:',json.dumps(p))
        self.assertEqual(self.p[931]['fieldConfig']['defaults']['color']['fixedColor'],'#B877D9')
        self.assertEqual(self.p[932]['fieldConfig']['defaults']['color']['fixedColor'],'#2EBFA5')

    def test_more_service_room_without_moving_originals(self):
        self.assertNotIn(933,self.p)
        for i in [931,932]:
            self.assertEqual(self.p[i]['gridPos']['w'],6)
            self.assertEqual(self.p[i]['options']['graphMode'],'area')
        self.assertNotIn('socrat:node_pressure',json.dumps([self.p[i] for i in Q.IDS & self.p.keys()]))

    def test_backup_success_not_restore_claim(self):
        for i in [934,935]:
            p=self.p[i];self.assertIn('NOT proof',p['description'])
            e=p['targets'][0]['expr'];self.assertIn('last_successful_time',e)
            self.assertIn('vector(-3)',e);self.assertIn('vector(-1)',e)
            self.assertEqual(p['options']['graphMode'],'none')
