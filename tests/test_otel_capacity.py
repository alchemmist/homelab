import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('otel_capacity', Path(__file__).parents[1] / 'scripts/otel-capacity-placement.py')
capacity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capacity)


def deployment():
    return {'metadata': {'namespace': 'cattle-fleet-system', 'name': 'gitjob',
                         'uid': 'controller-uid', 'resourceVersion': '123'},
            'spec': {'replicas': 1, 'strategy': {'type': 'RollingUpdate'},
                     'template': {'spec': {'nodeSelector': {'kubernetes.io/os': 'linux'},
                                           'containers': [{'image': 'rancher/fleet:v0.16.2', 'imagePullPolicy': 'IfNotPresent'}]}}},
            'status': {'readyReplicas': 1}}


class CapacityPlacementTests(unittest.TestCase):
    def test_only_scheduling_and_zero_unavailable_strategy_change(self):
        doc = deployment()
        before = copy.deepcopy(doc)
        patch, undo = capacity.placement(doc)
        self.assertEqual(doc, before)
        self.assertEqual(patch['metadata']['resourceVersion'], '123')
        self.assertEqual(patch['spec']['strategy']['rollingUpdate'], {'maxSurge': 1, 'maxUnavailable': 0})
        self.assertEqual(set(patch['spec']['template']['spec']), {'affinity'})
        self.assertNotIn('replicas', patch['spec'])
        self.assertEqual(undo['uid'], 'controller-uid')
        self.assertIsNone(undo['originalAffinity'])
        expression = patch['spec']['template']['spec']['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]['matchExpressions'][0]
        self.assertEqual(expression['values'], ['socrat-0', 'socrat-1'])

    def test_pod_anti_affinity_preserved_and_reapply_is_idempotent(self):
        doc = deployment()
        doc['spec']['template']['spec']['affinity'] = {'podAntiAffinity': {'preferredDuringSchedulingIgnoredDuringExecution': []}}
        patch, _ = capacity.placement(doc)
        affinity = patch['spec']['template']['spec']['affinity']
        self.assertIn('podAntiAffinity', affinity)
        doc['spec']['template']['spec']['affinity'] = affinity
        self.assertEqual(capacity.placement(doc), (None, None))

    def test_persistent_or_host_data_refused(self):
        for key in ('persistentVolumeClaim', 'hostPath', 'nfs'):
            doc = deployment()
            doc['spec']['template']['spec']['volumes'] = [{'name': 'data', key: {}}]
            with self.assertRaises(ValueError):
                capacity.placement(doc)

    def test_unhealthy_unapproved_paused_and_conflicting_placements_refused(self):
        for change in (
            lambda d: d['metadata'].update(name='prometheus'),
            lambda d: d['status'].update(readyReplicas=0),
            lambda d: d['spec'].update(paused=True),
            lambda d: d['spec']['strategy'].update(type='Recreate'),
            lambda d: d['spec']['template']['spec'].update(nodeSelector={'kubernetes.io/hostname': 'socrat-2'}),
            lambda d: d['spec']['template']['spec'].update(affinity={'nodeAffinity': {'other': True}}),
            lambda d: d['spec']['template']['spec']['containers'][0].update(imagePullPolicy='Always'),
        ):
            doc = deployment()
            change(doc)
            with self.assertRaises(ValueError):
                capacity.placement(doc)
