"""Offline metadata contract; never provisions alerts or creates notifications."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ExecutionLinks(unittest.TestCase):
    def test_id_is_annotation_not_alert_instance_or_threshold_input(self):
        definition=json.loads((ROOT/'docs/n8n/spi/alerts.json').read_text())
        rule=next(r for r in definition['rules'] if r['uid']=='spi-triage-failures')
        by_id={q['refId']:q for q in rule['data']}
        self.assertEqual(rule['condition'],'C')
        self.assertEqual(by_id['C']['model']['expression'],'A')
        self.assertEqual(by_id['A']['model']['expr'],'sum(count_over_time({k8s_namespace_name="automation"} |= "spi-triage" | json | event=~"stage_failed|handoff_failed" [20m])) or vector(0)')
        self.assertEqual(rule['for'],'2m')
        self.assertNotIn('n8n_execution_id',rule['labels'])
        query=by_id['B']['model']['expr']
        self.assertTrue(query.startswith('max(max_over_time('))
        self.assertIn('unwrap n8n_execution_id',query)
        self.assertIn('__error__="" [20m]',query)
        self.assertTrue(query.endswith('or vector(0)'))
        template=rule['annotations']['n8n_url']
        self.assertIn('if gt $values.B.Value 0.0',template)
        self.assertIn('/workflow/J9akzlydrf9XZiID/executions/',template)
        self.assertNotIn('16473',template) # no hard-coded historical execution
