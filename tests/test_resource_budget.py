import copy
import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / 'scripts/check-resource-budget.py'
SPEC = importlib.util.spec_from_file_location('resource_budget', PATH)
BUDGET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUDGET)


def container(name='app', cpu='100m', memory='128Mi', **kwargs):
    return dict(name=name, resources={'requests': {'cpu': cpu, 'memory': memory}}, **kwargs)


def pod():
    return {'metadata': {'namespace': 'test', 'name': 'app-123', 'ownerReferences': [{'controller': True, 'kind': 'ReplicaSet', 'name': 'app-hash'}]}, 'spec': {'nodeName': 'node', 'containers': [container()]}, 'status': {'phase': 'Running'}}


def profiles():
    return [{'namespace': 'test', 'ownerKind': 'ReplicaSet', 'ownerPattern': '^app-.*$', 'containers': {'app': {'requests': {'cpu': '200m', 'memory': '256Mi', 'ephemeral-storage': '32Mi'}, 'removeCpuLimit': True}}}]


def nodes():
    return [{'metadata': {'name': 'node'}, 'status': {'allocatable': {'cpu': '4', 'memory': '2Gi', 'ephemeral-storage': '10Gi'}}}]


class BudgetTests(unittest.TestCase):
    def test_quantities(self):
        for first, second in [('1', '1000m'), ('1Gi', '1024Mi'), ('1e3', '1k'), ('1E', '1000000000000000000'), ('1u', '1000n')]:
            self.assertEqual(BUDGET.quantity(first), BUDGET.quantity(second))
        for invalid in ['-1', 'abc', '3MM']:
            with self.assertRaises(ValueError):
                BUDGET.quantity(invalid)

    def test_ordered_init_sidecars(self):
        value = pod()
        value['spec']['initContainers'] = [container('first', '3'), container('sidecar', '2', restartPolicy='Always'), container('last', '2')]
        self.assertEqual(BUDGET.effective_requests(value)['cpu'], 4)
        value['spec']['initContainers'].reverse()
        self.assertEqual(BUDGET.effective_requests(value)['cpu'], 5)

    def test_regular_init_max_not_sum(self):
        value = pod()
        value['spec']['initContainers'] = [container('a', '1'), container('b', '2')]
        self.assertEqual(BUDGET.effective_requests(value)['cpu'], 2)

    def test_sidecars_added_to_running_containers(self):
        value = pod()
        value['spec']['initContainers'] = [container('sidecar', '2', restartPolicy='Always')]
        self.assertEqual(BUDGET.effective_requests(value)['cpu'], BUDGET.quantity('2.1'))

    def test_overhead_and_pod_resources(self):
        value = pod()
        value['spec'].update(resources={'requests': {'cpu': '2'}}, overhead={'cpu': '250m', 'memory': '1Mi'})
        result = BUDGET.effective_requests(value)
        self.assertEqual(result['cpu'], BUDGET.quantity('2.25'))
        self.assertEqual(result['memory'], BUDGET.quantity('129Mi'))

    def test_current_and_proposed_budget(self):
        result = BUDGET.budget([pod()], nodes(), profiles())
        self.assertTrue(result['ok'])
        self.assertEqual(result['nodes']['node']['current_requests']['cpu'], BUDGET.quantity('100m'))
        self.assertEqual(result['nodes']['node']['proposed_remaining']['memory'], BUDGET.quantity('1792Mi'))

    def test_over_capacity_fails(self):
        expected = profiles()
        expected[0]['containers']['app']['requests']['memory'] = '3Gi'
        result = BUDGET.budget([pod()], nodes(), expected)
        self.assertFalse(result['ok'])
        self.assertIn('exceed allocatable memory', result['errors'][0])

    def test_ambiguous_unmatched_fail(self):
        for expected in [[], profiles() * 2]:
            self.assertFalse(BUDGET.budget([pod()], nodes(), expected)['ok'])
        value = pod()
        value['spec']['initContainers'] = [container('uncovered')]
        self.assertIn('unmatched container', BUDGET.budget([value], nodes(), profiles())['errors'][0])

    def test_completed_pods_excluded(self):
        value = pod()
        value['status']['phase'] = 'Succeeded'
        self.assertTrue(BUDGET.budget([value], nodes(), [])['ok'])

    def test_unassigned_reported_not_charged(self):
        value = pod()
        value['spec'].pop('nodeName')
        result = BUDGET.budget([value], nodes(), profiles())
        self.assertEqual(len(result['unassigned']), 1)
        self.assertEqual(result['nodes']['node']['pods'], 0)

    def test_profile_preserves_custom_resources_and_input(self):
        value = pod()
        value['spec']['containers'][0]['resources']['limits'] = {'cpu': '2', 'nvidia.com/gpu': '1'}
        original = copy.deepcopy(value)
        changed = BUDGET.proposed_pod(value, profiles())
        self.assertEqual(changed['spec']['containers'][0]['resources']['limits'], {'nvidia.com/gpu': '1'})
        self.assertEqual(value, original)

    def test_invalid_profile_requests_fail(self):
        for invalid in ['-1', '0', 'invalid']:
            expected = profiles()
            expected[0]['containers']['app']['requests']['cpu'] = invalid
            with self.assertRaises(ValueError):
                BUDGET.budget([pod()], nodes(), expected)

    def test_unknown_node_fails(self):
        self.assertFalse(BUDGET.budget([pod()], [], profiles())['ok'])


if __name__ == '__main__':
    unittest.main()
