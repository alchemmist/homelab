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

    def test_manual_return_to_legacy_width_is_also_authoritative(self):
        grids={931:{'x':12,'y':14,'w':4,'h':4},932:{'x':16,'y':14,'w':4,'h':4}}
        for p in self.d['panels']:
            if p['id'] in grids:p['gridPos']=grids[p['id']]
        built=Q.build(self.d)
        for p in built['panels']:
            if p['id'] in grids:self.assertEqual(p['gridPos'],grids[p['id']])

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

    def test_one_compact_ai_block_replaces_http_errors(self):
        p=self.p[930];self.assertEqual(p['type'],'stat')
        self.assertEqual(p['options']['graphMode'],'none')
        self.assertEqual(len(p['targets']),2)
        queue,latency=[t['expr'] for t in p['targets']]
        self.assertIn('num_requests_waiting',queue)
        for token in ['histogram_quantile(0.95','[15m]','>=20','vector(-1)','< +Inf']:
            self.assertIn(token,latency)
        for expr in [queue,latency]:
            self.assertIn('timestamp(',expr);self.assertIn('up{',expr)
            self.assertIn('or vector(-2)',expr);self.assertNotIn('or vector(0)',expr)
        self.assertEqual(p['fieldConfig']['overrides'][0]['properties'][0]['value'],'s')
        self.assertNotIn('traefik_service_requests_total',json.dumps(p))

    def test_no_new_blue_and_no_ai_dominance(self):
        for i in Q.IDS & self.p.keys():
            p=self.p[i]
            self.assertNotIn('#5794F2',json.dumps(p))
            if i!=930:self.assertNotIn('vllm:',json.dumps(p))
        self.assertEqual(self.p[931]['fieldConfig']['defaults']['color']['fixedColor'],'#B877D9')
        self.assertEqual(self.p[932]['fieldConfig']['defaults']['color']['fixedColor'],'#2EBFA5')

    def test_more_service_room_without_moving_originals(self):
        self.assertNotIn(933,self.p)
        for i in [931,932]:
            self.assertEqual(self.p[i]['gridPos']['w'],6)
            self.assertEqual(self.p[i]['options']['graphMode'],'area')
        self.assertNotIn('socrat:node_pressure',json.dumps([self.p[i] for i in Q.IDS & self.p.keys()]))

    def test_cascade_six_values_fit_bottom_without_new_css(self):
        self.assertEqual(self.p[931]['gridPos']['h'],4)
        self.assertEqual(self.p[932]['gridPos']['h'],4)
        for i,x in [(934,12),(935,14)]:
            self.assertEqual(self.p[i]['gridPos'],{'x':x,'y':18,'w':2,'h':2})
        p=self.p[936];self.assertEqual(p['gridPos'],{'x':16,'y':18,'w':8,'h':2})
        self.assertEqual(len(p['targets']),4)
        for t in p['targets']:
            self.assertTrue(t['instant']);self.assertIn('or vector(-2)',t['expr'])
            self.assertIn('timestamp(',t['expr']);self.assertIn('up{',t['expr'])
        expr=' '.join(t['expr'] for t in p['targets'])
        for token in ['thanos-cascade','todo_downsample_blocks','compact_halted','count(',')==3','head_samples_appended_total','[5m]']:
            self.assertIn(token,expr)
        self.assertIn('not end-to-end',p['description'])

    def test_backup_success_not_restore_claim(self):
        for i in [934,935]:
            p=self.p[i];self.assertIn('NOT proof',p['description'])
            e=p['targets'][0]['expr'];self.assertIn('last_successful_time',e)
            self.assertIn('vector(-3)',e);self.assertIn('vector(-1)',e)
            self.assertEqual(p['options']['graphMode'],'none')
