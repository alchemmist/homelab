import importlib.util
from pathlib import Path
import unittest
from urllib.parse import unquote

MODULE_PATH = Path(__file__).resolve().parents[1] / 'ansible/roles/monitoring_k3s/files/resolve_alert_links.py'
SPEC = importlib.util.spec_from_file_location('resolve_alert_links', MODULE_PATH)
LINKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINKS)

RULE = {
    'name': 'SocratNodeResourceContention',
    'type': 'alerting',
    'query': 'socrat:node_pressure_waiting:ratio5m{resource="cpu"} > 0.25 or socrat:node_pressure_waiting:ratio5m{resource=~"memory|io"} > 0.1',
    'labels': {'severity': 'warning'},
    'annotations': {
        'description': 'Node {{ $labels.node }} has sustained {{ $labels.resource }} PSI some pressure for 10m: above 25% for CPU or 10% for memory or I/O, averaged over 5m. This measures time with at least one stalled task, not resource utilization or Kubernetes eviction pressure.',
        'rancher_url': 'https://rancher.socrat.alchemmist.xyz/dashboard/c/local/explorer/node/{{ $labels.node }}',
        'summary': 'Tasks are persistently waiting for a node resource.',
    },
}


class AlertLinksTest(unittest.TestCase):
    def test_native_live_fingerprint(self):
        self.assertEqual(LINKS.rule_hash(RULE), '2002033236')

    def test_runtime_state_does_not_change_url(self):
        changed = dict(RULE, state='firing', alerts=[{'value': '100'}], lastEvaluation='now')
        self.assertEqual(LINKS.rule_hash(RULE), LINKS.rule_hash(changed))

    def test_expression_change_changes_fingerprint(self):
        self.assertNotEqual(LINKS.rule_hash(RULE), LINKS.rule_hash(dict(RULE, query='up == 0')))
        self.assertEqual(LINKS.rule_hash(RULE, True), LINKS.rule_hash(dict(RULE, query='up == 0'), True))

    def test_javascript_utf16_hash(self):
        self.assertEqual(LINKS.js_hash('😀'), 1772899)
        self.assertEqual(LINKS.js_hash('hello world'), 1794106052)

    def test_native_escaping(self):
        group = {'file': '/etc/rules/a.yaml', 'name': 'group$one'}
        url = LINKS.rule_url(group, RULE)
        self.assertIn('pri$Prometheus$\x1fetc\x1frules\x1fa.yaml$group_DOLLAR_one$', unquote(url))
        self.assertTrue(url.endswith('%242002033236/view'))

    def test_grouped_selectors_keep_severity_variants_and_ignore_other_metrics(self):
        other = dict(RULE, name='Other', labels={'severity': 'critical'})
        warning = dict(other, labels={'severity': 'warning'})
        dashboard = {'panels': [{'id': 1, 'targets': [{'expr': 'ALERTS{alertname=~"SocratNodeResourceContention|Other"} or ALERTS{alertname="Other"} or up{alertname="Unrelated"}'}]}]}
        response = {'data': {'groups': [{'name': 'group', 'file': '/x', 'rules': [RULE, other, warning]}]}}
        links = LINKS.resolve(dashboard, response, {})['nodeAlertLinks']['1']
        self.assertEqual(len(links), 3)
        self.assertEqual(len({link['url'] for link in links}), 3)
        self.assertIn('Other · critical', [link['title'] for link in links])

    def test_missing_rule_fails_instead_of_incomplete_links(self):
        dashboard = {'panels': [{'id': 2, 'targets': [{'expr': 'ALERTS{alertname="Missing"}'}]}]}
        with self.assertRaisesRegex(ValueError, 'Missing'):
            LINKS.resolve(dashboard, {'data': {'groups': []}}, {})

    def test_convergence_rejects_old_expression_and_accepts_current(self):
        group = {'name': 'group', 'file': '/rules/ns-resource-uid.yaml', 'rules': [RULE]}
        expected = [('ns-resource-uid.yaml', 'group', RULE)]
        LINKS.require_convergence({'data': {'groups': [group]}}, expected)
        stale = dict(group, rules=[dict(RULE, query='up == 0')])
        with self.assertRaisesRegex(ValueError, 'current rule definitions'):
            LINKS.require_convergence({'data': {'groups': [stale]}}, expected)

    def test_convergence_checks_annotations_and_resource_uid(self):
        expected = [('ns-resource-uid.yaml', 'group', RULE)]
        for rule, filename in [(dict(RULE, annotations={}), 'ns-resource-uid.yaml'), (RULE, 'ns-resource-old.yaml')]:
            group = {'name': 'group', 'file': '/rules/' + filename, 'rules': [rule]}
            with self.assertRaises(ValueError):
                LINKS.require_convergence({'data': {'groups': [group]}}, expected)

    def test_expected_rule_formatting_is_cached(self):
        rule = {'alert': RULE['name'], 'expr': '(up > 0)', 'labels': RULE['labels'], 'annotations': RULE['annotations']}
        resources = {'items': [{'metadata': {'name': 'resource', 'namespace': 'ns', 'uid': 'uid'}, 'spec': {'groups': [{'name': 'group', 'rules': [rule, rule]}]}}]}
        dashboard = {'panels': [{'id': 1, 'targets': [{'expr': 'ALERTS{alertname="SocratNodeResourceContention"}'}]}]}
        calls = []
        def formatter(expression):
            calls.append(expression)
            return 'up > 0'
        expected = LINKS.expected_rules(dashboard, resources, formatter)
        self.assertEqual(calls, ['(up > 0)'])
        self.assertEqual(expected[0][0], 'ns-resource-uid.yaml')
        self.assertEqual(expected[0][2]['query'], 'up > 0')

    def test_query_normalization(self):
        self.assertEqual(LINKS.query_fingerprint('(up{foo="bar",} > 0) # comment'), LINKS.query_fingerprint('up{foo="bar"}>0'))


if __name__ == '__main__':
    unittest.main()
