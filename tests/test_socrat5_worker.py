"""Headless LXC worker source invariants; no live operations or credentials."""
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


class Socrat5WorkerSourceTests(unittest.TestCase):
    def test_general_admission_remains_guarded(self):
        host = yaml.safe_load((ROOT / 'ansible/inventory/host_vars/socrat-5.yml').read_text())
        self.assertEqual(host['k3s_worker_bootstrap_taint'], 'homelab.io/bootstrap=true:NoSchedule')
        self.assertTrue(host['homelab_headless'])
        self.assertFalse(host['k3s_worker_manage_kernel_modules'])

    def test_exact_advertised_home_routes_only(self):
        host = yaml.safe_load((ROOT / 'ansible/inventory/host_vars/socrat-5.yml').read_text())
        self.assertEqual(host['wg_socrat_extra_allowed_peer_ips'], {
            'socrat-5': {'socrat-0': ['192.168.0.23/32'], 'socrat-1': ['192.168.0.24/32']}})

    def test_password_tasks_are_private_and_do_not_change_ssh_policy(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/socrat-5-headless.yml').read_text())[0]
        users = [t for t in play['pre_tasks'] if 'ansible.builtin.user' in t]
        self.assertEqual({t['ansible.builtin.user']['name'] for t in users}, {'alchemmist', 'root'})
        self.assertTrue(all(t['no_log'] for t in users))
        self.assertTrue(all('password' in t['ansible.builtin.user'] for t in users))
        self.assertNotIn('sshd_config', str(users))

    def test_no_desktop_roles(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/socrat-5-headless.yml').read_text())[0]
        self.assertEqual(play['roles'], ['starship'])

    def test_native_pipeline_is_durable(self):
        cfg = yaml.safe_load((ROOT / 'deploy/monitoring/native/socrat-5/agent.yaml').read_text())
        self.assertTrue(cfg['extensions']['file_storage']['fsync'])
        for name in ['journald', 'filelog']:
            self.assertEqual(cfg['receivers'][name]['retry_on_failure']['max_elapsed_time'], '0s')

    def test_real_blockers_documented(self):
        text = (ROOT / 'docs/socrat-5-worker-20261110.md').read_text()
        self.assertIn('Negative NetworkPolicy acceptance failed', text)
        self.assertIn('NFS mount denied', text)
        self.assertIn('do not remove bootstrap NoSchedule', text)
