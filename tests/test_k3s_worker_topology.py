import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / 'ansible/roles/k3s_role_rebalance/files'
sys.path.insert(0, str(HELPERS))
spec = importlib.util.spec_from_file_location('verify_worker_topology', HELPERS / 'verify_worker_topology.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeEtcd:
    def __init__(self):
        self.data = {name: {'id': i, 'learner': False} for i, name in enumerate(sorted(module.VOTERS), 1)}
        self.checked = []
        self.mismatch = False
        self.unhealthy = None

    def members(self):
        return self.data.copy()

    def health(self, name):
        self.checked.append(name)
        if name == self.unhealthy:
            raise RuntimeError('Unhealthy endpoint')

    def status(self, name):
        return {'header': {'member_id': 999 if self.mismatch else self.data[name]['id']}}


class WorkerTopologyTests(unittest.TestCase):
    def test_three_healthy_votes_without_worker_endpoint(self):
        client = FakeEtcd()
        result = module.verify(client)
        self.assertFalse(result['changed'])
        self.assertEqual(client.checked, ['socrat-0', 'socrat-1', 'socrat-2'])

    def test_old_topology_is_rejected(self):
        client = FakeEtcd()
        client.data['socrat-3'] = client.data.pop('socrat-1')
        with self.assertRaises(RuntimeError):
            module.verify(client)

    def test_learner_is_not_a_completed_migration(self):
        client = FakeEtcd()
        client.data['socrat-1']['learner'] = True
        with self.assertRaises(RuntimeError):
            module.verify(client)

    def test_endpoint_identity_must_match(self):
        client = FakeEtcd()
        client.mismatch = True
        with self.assertRaises(RuntimeError):
            module.verify(client)

    def test_unhealthy_voter_is_not_accepted(self):
        client = FakeEtcd()
        client.unhealthy = 'socrat-2'
        with self.assertRaises(RuntimeError):
            module.verify(client)

    def test_historical_rebalance_is_guarded_before_capacity_checks(self):
        play = (ROOT / 'ansible/playbooks/k3s-role-rebalance.yml').read_text()
        self.assertLess(play.index('Refuse the superseded promotion'), play.index('Require the pinned K3s version'))
        self.assertIn('/var/lib/homelab-k3s-rebalance/worker-topology', play)


if __name__ == '__main__':
    unittest.main()
