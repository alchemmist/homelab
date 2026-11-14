import importlib.util
import json
import unittest
from pathlib import Path


def load(relative):
    source = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(source.stem, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELOCATE = load('ansible/roles/monitoring_stack/files/prometheus_relocate.py')
GUARD = load('ansible/roles/monitoring_k3s/files/prometheus_scrape_guard.py')


def pod(node):
    return {'metadata': {'name': 'prometheus-kube-prometheus-stack-prometheus-0'}, 'spec': {'nodeName': node}}


def volume(node, claim='prometheus-kube-prometheus-stack-prometheus-db-prometheus-kube-prometheus-stack-prometheus-0'):
    return {
        'spec': {
            'claimRef': {'name': claim},
            'nodeAffinity': {'required': {'nodeSelectorTerms': [{'matchExpressions': [
                {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': [node]},
            ]}]}},
        },
    }


class RelocateTests(unittest.TestCase):
    def test_same_node_proceeds_without_the_flag(self):
        decision = RELOCATE.evaluate({'desired': 'socrat-0', 'relocate': False, 'pods': [pod('socrat-0')], 'volumes': []})
        self.assertEqual(decision['action'], 'proceed')

    def test_socrat_1_volume_is_refused_even_with_the_legacy_flag(self):
        payload = {'desired': 'socrat-0', 'relocate': False, 'pods': [], 'volumes': [volume('socrat-1')]}
        self.assertEqual(RELOCATE.evaluate(payload)['action'], 'refuse')
        payload['relocate'] = True
        decision = RELOCATE.evaluate(payload)
        self.assertEqual(decision['action'], 'refuse')
        self.assertTrue(decision['claim'].startswith('prometheus-kube-prometheus-stack-prometheus-db'))

    def test_monitoring_roles_do_not_delete_history(self):
        root = Path(__file__).resolve().parents[1]
        stack = (root / 'ansible/roles/monitoring_stack/tasks/main.yml').read_text()
        thanos = (root / 'ansible/roles/monitoring_thanos/tasks/main.yml').read_text()
        self.assertNotIn('delete, pvc', stack)
        self.assertNotIn('delete, pod', stack)
        self.assertNotIn('state: absent', thanos)
        self.assertNotIn('      - delete', thanos)

    def test_grafana_volume_is_not_selected(self):
        grafana = volume('socrat-1', claim='kube-prometheus-stack-grafana')
        decision = RELOCATE.evaluate({'desired': 'socrat-0', 'relocate': True, 'pods': [], 'volumes': [grafana]})
        self.assertEqual(decision['action'], 'proceed')
        self.assertIsNone(decision['claim'])


class ScrapeGuardTests(unittest.TestCase):
    def test_five_second_scrape_and_eight_gib_limit_pass(self):
        document = {'items': [{'spec': {'scrapeInterval': '5s', 'resources': {'limits': {'memory': '8Gi'}}}}]}
        self.assertEqual(GUARD.problems(document), [])

    def test_old_prometheus_is_rejected(self):
        document = {'items': [{'spec': {'scrapeInterval': '30s', 'resources': {'limits': {'memory': '3Gi'}}}}]}
        self.assertEqual(len(GUARD.problems(document)), 2)

    def test_missing_prometheus_is_rejected(self):
        self.assertEqual(GUARD.problems({'items': []}), ['Prometheus is not installed'])


if __name__ == '__main__':
    unittest.main()


class EffectiveMemoryGuardTests(unittest.TestCase):
    def documents(self, spec_limit='8Gi', runtime_limit='8Gi'):
        cr = {'items': [{'spec': {'scrapeInterval': '5s', 'resources': {'limits': {'memory': '8Gi'}}}}]}
        pods = {'items': [{'spec': {'containers': [{'name': 'prometheus', 'resources': {'limits': {'memory': spec_limit}}}]},
                           'status': {'phase': 'Running', 'containerStatuses': [{'name': 'prometheus', 'ready': True,
                               'resources': {'limits': {'memory': runtime_limit}}}]}}]}
        return cr, pods

    def test_eight_gib_cr_cannot_hide_three_gib_admission(self):
        self.assertTrue(GUARD.problems(*self.documents('3Gi', '3Gi')))

    def test_resize_spec_without_effective_runtime_is_not_acceptance(self):
        self.assertTrue(GUARD.problems(*self.documents('8Gi', '3Gi')))

    def test_eight_gib_effective_runtime_passes(self):
        self.assertEqual(GUARD.problems(*self.documents()), [])

    def test_missing_runtime_does_not_pass(self):
        cr, _ = self.documents()
        self.assertTrue(GUARD.problems(cr, {'items': []}))
