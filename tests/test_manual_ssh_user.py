import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('manual_ssh_check', ROOT/'ansible/roles/ssh_user/files/check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class ManualSSHTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='manual-ssh-test-')
        cls.key = Path(cls.temp.name)/'fixture'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(cls.key)], check=True)
        cls.public = cls.key.with_suffix('.pub').read_text()

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_real_parser_canonicalizes_public_key_and_reports_fingerprint(self):
        result = check.validate('guest', self.public)
        self.assertEqual(result['public_key'], ' '.join(self.public.split()[:2]))
        self.assertTrue(result['fingerprint'].startswith('SHA256:'))

    def test_private_key_options_certificates_multiline_and_controls_are_rejected(self):
        for bad in [self.key.read_text(), 'command="id" '+self.public, self.public+self.public,
                    self.public.rstrip()+'\tcomment', self.public.replace('ssh-ed25519', 'ssh-ed25519-cert-v01@openssh.com')]:
            with self.assertRaises(ValueError):check.validate('guest', bad)

    def test_invalid_base64_ssh_wire_data_is_rejected_by_actual_parser(self):
        with self.assertRaises(ValueError):check.validate('guest', 'ssh-ed25519 AAAA')

    def test_protected_and_injectable_names_are_rejected_before_parsing_key(self):
        with patch.object(check, 'fingerprint') as parser:
            for name in ['root', 'alchemmist', 'ghactions', 'nobody', '', 'x;id', '../guest', '-guest', 'UPPER', 'x'*32]:
                with self.subTest(name=name), self.assertRaises(ValueError):check.validate(name, self.public)
            parser.assert_not_called()

    def test_play_scope_and_all_host_preflight(self):
        play = yaml.safe_load((ROOT/'ansible/playbooks/ssh-user.yml').read_text())[0]
        self.assertEqual(play['hosts'], 'Socrat')
        self.assertTrue(play['any_errors_fatal'])
        self.assertEqual(play['strategy'], 'linear')
        self.assertFalse(play['gather_facts'])
        self.assertEqual(play['roles'], ['ssh_user'])

    def test_additive_keys_not_exact_replacement_and_no_existing_group_stripping(self):
        tasks = yaml.safe_load((ROOT/'ansible/roles/ssh_user/tasks/main.yml').read_text())
        key = next(t for t in tasks if 'ansible.posix.authorized_key' in t)
        self.assertFalse(key['ansible.posix.authorized_key']['exclusive'])
        self.assertEqual(key['become_user'], '{{ ssh_user_key.username }}')
        self.assertTrue(any(t['name'].startswith('Require target-user execution') for t in tasks))
        self.assertIn('not ssh_user_account.has_requested_key', key['when'])
        user = next(t for t in tasks if 'ansible.builtin.user' in t)['ansible.builtin.user']
        self.assertTrue(user['password_lock'])
        self.assertIn('omit if ssh_user_before.exists', user['groups'])
        self.assertIn('omit if ssh_user_before.exists', user['shell'])
        self.assertFalse(any('ansible.builtin.service' in t or 'ansible.builtin.systemd' in t for t in tasks))

    def test_preflight_precedes_account_and_key_mutations(self):
        tasks = yaml.safe_load((ROOT/'ansible/roles/ssh_user/tasks/main.yml').read_text())
        before = next(i for i,t in enumerate(tasks) if t['name'].startswith('Preflight account'))
        mutate = next(i for i,t in enumerate(tasks) if 'ansible.builtin.user' in t)
        self.assertLess(before, mutate)
        validators = [t for t in tasks if 'ansible.builtin.script' in t and 'before granting a key' in t['name']]
        self.assertEqual(len(validators), 1)

    def test_missing_inputs_stop_without_contacting_a_host(self):
        # Fake local inventory: if the input guard fails, no account action runs.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'inventory.yml'
            path.write_text('all:\n  children:\n    Socrat:\n      hosts:\n        fixture:\n          ansible_connection: local\n          ansible_become: false\n')
            p = subprocess.run(['ansible-playbook', '-i', str(path), 'playbooks/ssh-user.yml', '--check'],
                               cwd=ROOT/'ansible', capture_output=True, text=True, timeout=30)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('Supply ssh_username and ssh_public_key_file', p.stdout)
            self.assertNotIn('Preflight account', p.stdout)
