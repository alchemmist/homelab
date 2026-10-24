from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class VPSWorkloadOffloadTests(unittest.TestCase):
    def test_only_three_selected_profiles_pin_to_home_worker(self):
        profiles = yaml.safe_load((ROOT / 'ansible/vars/container-resources.yml').read_text())['container_resource_policy_profiles']
        selected = [profile for profile in profiles if profile.get('nodeSelector')]
        self.assertEqual({(profile['namespace'], profile['ownerPattern']) for profile in selected}, {
            ('img-proxy', r'^img\-proxy-[a-z0-9]+$'),
            ('kube-system', r'^metrics\-server-[a-z0-9]+$'),
            ('kube-system', r'^local\-path\-provisioner-[a-z0-9]+$'),
        })
        for profile in selected:
            self.assertEqual(profile['nodeSelector'], {'kubernetes.io/hostname': 'socrat-1'})

    def test_rollout_is_sequential_and_scoped(self):
        tasks = yaml.safe_load((ROOT / 'ansible/roles/vps_workload_offload/tasks/main.yml').read_text())
        loops = [task for task in tasks if 'ansible.builtin.include_tasks' in task]
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]['loop'], [
            {'namespace': 'img-proxy', 'name': 'img-proxy'},
            {'namespace': 'kube-system', 'name': 'metrics-server'},
            {'namespace': 'kube-system', 'name': 'local-path-provisioner'},
        ])
        deployment = (ROOT / 'ansible/roles/vps_workload_offload/tasks/deployment.yml').read_text()
        self.assertIn('rollout, status', deployment)
        self.assertIn("pod['spec'].get('nodeName') == 'socrat-1'", deployment)
        self.assertNotIn('delete', deployment)

    def test_playbook_refuses_cluster_wide_eviction(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/socrat-2-offload.yml').read_text())[0]
        checks = [task['ansible.builtin.assert'] for task in play['pre_tasks'] if 'ansible.builtin.assert' in task]
        self.assertEqual(checks[0]['that'], 'not (container_resource_policy_reconcile | default(false) | bool)')
        self.assertEqual(play['roles'], ['container_resource_policy', 'vps_workload_offload'])

    def test_image_proxy_helm_values_persist_home_placement(self):
        values = yaml.safe_load((ROOT / 'charts/img-proxy/values.yaml').read_text())
        self.assertEqual(values['nodeSelector'], {'kubernetes.io/hostname': 'socrat-1'})
        deployment = (ROOT / 'charts/img-proxy/templates/deployment.yaml').read_text()
        self.assertIn('with .Values.nodeSelector', deployment)


if __name__ == '__main__':
    unittest.main()
