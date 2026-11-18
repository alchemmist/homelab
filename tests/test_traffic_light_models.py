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
            if p['id'] in (937,938):
                self.assertFalse(p['options']['legend']['showLegend'])
                self.assertNotIn('timeFrom',p)
                self.assertIn('[1m]',p['targets'][0]['expr'])
                self.assertEqual(p['fieldConfig']['defaults']['color']['mode'],'palette-classic-by-name')
        self.assertNotIn(930,{p['id'] for p in self.d['panels']})

    def test_overlap_rejected(self):
        d = copy.deepcopy(self.d)
        next(p for p in d['panels'] if p['id']==937)['gridPos']['y']=10
        with self.assertRaises(ValueError): M['build'](d)

    def test_bottom_rejected(self):
        d = copy.deepcopy(self.d)
        next(p for p in d['panels'] if p['id']==938)['gridPos']['h']=5
        with self.assertRaises(ValueError): M['build'](d)
