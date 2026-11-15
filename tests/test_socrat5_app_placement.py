"""Source contracts for the owner-approved15Nov VM application handoff."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def document(path):
    return yaml.safe_load((ROOT / path).read_text())


class VMApplicationPlacementTests(unittest.TestCase):
    def test_n8n_uses_original_vm_claim_without_repointing_recovery_storage(self):
        values = document('charts/n8n/values.yaml')
        self.assertEqual(values['nodeName'], 'socrat-5')
        self.assertEqual(values['persistence']['claimName'], 'n8n-socrat5')
        self.assertEqual(values['secretName'], 'n8n-secrets')
        self.assertIn(values['replicaCount'], [0, 1])
        self.assertEqual(values['recoveryStorage']['name'], 'n8n-recovery-20261114')
        self.assertEqual(values['recoveryStorage']['nodeName'], 'socrat-1')
        self.assertEqual(values['recoveryStorage']['path'],
                         '/home/alchemmist/.local/share/homelab/n8n-recovery-20261114/data')

    def test_pr_agent_uses_vm_and_preserves_secret_identity(self):
        values = document('charts/pr-agent/values.yaml')
        self.assertEqual(values['nodeName'], 'socrat-5')
        self.assertEqual(values['secretName'], 'pr-agent')
        self.assertEqual(values['replicaCount'], 1)

    def test_rancher_keeps_two_distinct_nodes_and_offloads_home0(self):
        values = document('deploy/platform/rancher/values.yaml')
        role = document('ansible/roles/rancher_placement/defaults/main.yml')
        self.assertEqual(values['replicas'], 2)
        self.assertEqual(values['antiAffinity'], 'required')
        self.assertEqual(values['extraNodeSelectorTerms'], [{
            'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['socrat-1', 'socrat-5']}])
        self.assertNotIn('nodeSelector', values)
        self.assertEqual(role['rancher_placement_nodes'], ['socrat-1', 'socrat-5'])
        self.assertEqual(role['rancher_replicas'], 2)
        self.assertEqual(role['rancher_chart_version'], '2.15.2')
        self.assertFalse(values['ingress']['enabled'])
