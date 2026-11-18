"""Owner capture and narrow TV addition regression."""
import copy
import json
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT/'scripts/build-traffic-light-models.py'))


class Models(unittest.TestCase):
    def setUp(self):
        self.d = json.loads((ROOT/'charts/monitoring-k3s/dashboards/traffic-light.json').read_text())

    def test_idempotent_and_owner_exact(self):
        self.assertEqual(M['build'](self.d), self.d)
        for p in self.d['panels']:
            if p['id'] == 938:
                self.assertTrue(p['options']['legend']['showLegend'])
                self.assertNotIn('timeFrom',p)
                self.assertIn('[1m]',p['targets'][0]['expr'])
                self.assertEqual(p['fieldConfig']['defaults']['color']['mode'],'palette-classic-by-name')
        self.assertNotIn(937,{p['id'] for p in self.d['panels']})
        self.assertIn('sum by (requested_model)', next(p for p in self.d['panels'] if p['id']==938)['targets'][0]['expr'])
        self.assertNotIn(930,{p['id'] for p in self.d['panels']})

    def test_overlap_rejected(self):
        d = copy.deepcopy(self.d)
        next(p for p in d['panels'] if p['id']==938)['gridPos']['y']=10
        with self.assertRaises(ValueError): M['build'](d)

    def test_bottom_rejected(self):
        d = copy.deepcopy(self.d)
        next(p for p in d['panels'] if p['id']==938)['gridPos']['h']=7
        with self.assertRaises(ValueError): M['build'](d)


class SplitCascade(unittest.TestCase):
    def test_split_preserves_query_semantics_and_boundary(self):
        d = json.loads((ROOT/'charts/monitoring-k3s/dashboards/traffic-light.json').read_text())
        p = {p['id']: p for p in d['panels']}
        for pid,x,name in [(936,12,'Cascade age'),(939,14,'Samples/s')]:
            self.assertEqual(p[pid]['gridPos'],dict(x=x,y=18,w=2,h=2))
            self.assertEqual(len(p[pid]['targets']),1)
            self.assertEqual(p[pid]['targets'][0]['legendFormat'],name)
            self.assertEqual(p[pid]['fieldConfig']['defaults']['color']['fixedColor'],'#E0B860')
            self.assertIn('or vector(-2)',p[pid]['targets'][0]['expr'])
        self.assertEqual(p[938]['gridPos'],dict(x=16,y=14,w=8,h=6))
        self.assertEqual(p[938]['gridPos']['y']+p[938]['gridPos']['h'],p[909]['gridPos']['y']+p[909]['gridPos']['h'])
        self.assertNotIn('todo_downsample_blocks',json.dumps(d))
        self.assertNotIn('thanos_compact_halted',json.dumps(d))
