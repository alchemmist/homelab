import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('etcd_members', Path(__file__).resolve().parents[1] / 'ansible/roles/k3s_role_rebalance/files/etcd_members.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeEtcd:
    def __init__(self):
        self.membership = {name: {'id': index + 1, 'id_hex': format(index + 1, 'x'), 'learner': False, 'peer_urls': [MODULE.PEERS[name]]} for index, name in enumerate(MODULE.ENDPOINTS)}
        self.leader = 2
        self.healthy = {'socrat-0', 'socrat-1', 'socrat-3'}
        self.calls = []
        self.fail_remove = False
        self.ambiguous_remove = False

    def members(self):
        return dict(self.membership)

    def health(self, name):
        if name not in self.healthy:
            raise RuntimeError('unhealthy')

    def status(self, name):
        return {'header': {'member_id': self.membership[name]['id']}, 'leader': self.leader}

    def call(self, args, endpoint=None, structured=True):
        self.calls.append((args, endpoint))
        if args[0] == 'move-leader':
            self.leader = int(args[1], 16)
        elif args[:2] == ['member', 'remove']:
            if self.fail_remove:
                raise RuntimeError('failed')
            del self.membership['socrat-1']
            if self.ambiguous_remove:
                raise RuntimeError('response lost')


class RebalanceTest(unittest.TestCase):
    def test_final_verification_never_removes_an_unexpected_member(self):
        client = FakeEtcd()
        with self.assertRaises(RuntimeError):
            MODULE.verify_final(client)
        self.assertEqual(client.calls, [])
        self.assertIn('socrat-1', client.membership)

    def test_offline_socrat_2_allows_guarded_removal(self):
        client = FakeEtcd()
        result = MODULE.remove_socrat_1(client)
        self.assertTrue(result['changed'])
        self.assertEqual(set(result['members']), MODULE.FINAL)
        self.assertEqual(client.calls, [(['move-leader', '1'], MODULE.ENDPOINTS['socrat-1']), (['member', 'remove', '2'], None)])

    def test_target_membership_is_idempotent(self):
        client = FakeEtcd()
        del client.membership['socrat-1']
        self.assertFalse(MODULE.remove_socrat_1(client)['changed'])
        self.assertEqual(client.calls, [])

    def test_unhealthy_required_member_blocks_mutation(self):
        for name in ('socrat-0', 'socrat-1', 'socrat-3'):
            client = FakeEtcd()
            client.healthy.remove(name)
            with self.assertRaises(RuntimeError):
                MODULE.remove_socrat_1(client)
            self.assertEqual(client.calls, [])

    def test_learner_blocks_mutation(self):
        client = FakeEtcd()
        client.membership['socrat-3']['learner'] = True
        with self.assertRaises(RuntimeError):
            MODULE.remove_socrat_1(client)
        self.assertEqual(client.calls, [])

    def test_unknown_membership_blocks_mutation(self):
        client = FakeEtcd()
        client.membership['unknown'] = client.membership.pop('socrat-3')
        with self.assertRaises(RuntimeError):
            MODULE.remove_socrat_1(client)
        self.assertEqual(client.calls, [])

    def test_failed_removal_requires_operator_action(self):
        client = FakeEtcd()
        client.fail_remove = True
        with self.assertRaisesRegex(RuntimeError, 'restore its staged configuration'):
            MODULE.remove_socrat_1(client)
        self.assertIn('socrat-1', client.membership)

    def test_lost_success_response_is_verified(self):
        client = FakeEtcd()
        client.ambiguous_remove = True
        self.assertTrue(MODULE.remove_socrat_1(client)['changed'])


if __name__ == '__main__':
    unittest.main()
