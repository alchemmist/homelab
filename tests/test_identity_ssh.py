"""Offline only: real OpenSSH key parser, fake HTTPS, local Ansible intent checks."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('identity_ssh_plan', ROOT / 'scripts/identity-ssh-plan.py')
ssh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh)
UUID = '11111111-2222-4333-8444-555555555555'
OTHER = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
# Existing PUBLIC key, not a private fixture; inventory itself is kept byte-for-byte.
TIM = yaml.safe_load((ROOT / 'ansible/inventory/group_vars/Socrat.yml').read_text())['homelab_users'][0]
KEY = TIM['authorized_keys'][0]


def ledger(name='guest'):
    return {'version': 1, 'bindings': [{'uuid': UUID, 'name': name}]}


def policy(state='present', hosts=None, revoked=None):
    return {'version': 1, 'public_key_attribute': 'ssh_public_keys', 'assignments': [
        {'uuid': UUID, 'state': state, 'hosts': ['socrat-1'] if hosts is None else hosts,
         'revoked_hosts': [] if revoked is None else revoked}]}


def user():
    return {'uuid': UUID, 'is_active': True, 'type': 'internal',
            'username': 'editable-name', 'email': 'arbitrary@example.invalid',
            'groups': ['homelab-owner'], 'attributes': {'ssh_public_keys': [KEY],
                'linux_username': 'root', 'hosts': ['unreviewed'], 'sudo': True}}


def plan(p=None, u=None):
    return ssh.build_plan(ssh.bindings_map(ledger()), p or policy(), lambda ident: u or user())


class BindingTests(unittest.TestCase):
    def test_append_only_both_directions(self):
        current = ssh.bindings_map(ledger())
        ssh.validate_history(current, [ledger()])
        added = {**current, OTHER: 'another'}
        ssh.validate_history(added, [ledger()])
        for invalid in [{UUID: 'another'}, {}, {OTHER: 'guest'}]:
            with self.subTest(invalid=invalid), self.assertRaises(ssh.Refused):
                ssh.validate_history(invalid, [ledger()])
        duplicate = ledger(); duplicate['bindings'].append({'uuid': OTHER, 'name': 'guest'})
        with self.assertRaises(ssh.Refused): ssh.bindings_map(duplicate)

    def test_missing_or_mutable_identity_and_reserved_names_rejected(self):
        for name in ['root', 'alchemmist', 'ghactions', 'bad;cmd', '-option', 'Aname']:
            with self.subTest(name=name), self.assertRaises(ssh.Refused): ssh.bindings_map(ledger(name))
        for ident in ['', 'username', UUID.upper(), '00000000-0000-0000-0000-000000000000']:
            if ident == UUID: continue  # UUID above contains digits only.
            doc = ledger(); doc['bindings'][0]['uuid'] = ident
            with self.subTest(ident=ident), self.assertRaises(ssh.Refused): ssh.bindings_map(doc)
        u = user(); del u['uuid']
        with self.assertRaises(ssh.Refused): plan(u=u)
        u = user(); u['uuid'] = OTHER
        with self.assertRaises(ssh.Refused): plan(u=u)

    def test_never_matches_names_groups_or_attributes(self):
        payload, summary = plan()
        entry = payload['by_host']['socrat-1'][0]
        self.assertEqual(entry['name'], 'guest')
        self.assertEqual(entry['hosts'], ['socrat-1'])
        self.assertFalse(entry['sudo']); self.assertEqual(entry['groups'], [])
        self.assertNotIn('arbitrary', json.dumps(payload))
        self.assertNotIn('homelab-owner', json.dumps(payload))
        self.assertTrue(summary[0]['fingerprints'][0].startswith('SHA256:'))
        self.assertEqual(entry['key_fingerprints'], summary[0]['fingerprints'])

    def test_policy_fields_hosts_and_uuid_fail_closed(self):
        for change in [lambda p: p['assignments'][0].pop('hosts'),
                       lambda p: p['assignments'][0].update(hosts=[]),
                       lambda p: p['assignments'][0].update(hosts='socrat-1'),
                       lambda p: p['assignments'][0].update(hosts=['socrat-1;id']),
                       lambda p: p['assignments'][0].update(hosts=['socrat-1', 'socrat-1']),
                       lambda p: p['assignments'][0].update(revoked_hosts=['socrat-1']),
                       lambda p: p['assignments'][0].update(uuid=OTHER),
                       lambda p: p['assignments'][0].update(sudo=True),
                       lambda p: p['assignments'].append(copy.deepcopy(p['assignments'][0]))]:
            p = policy(); change(p)
            with self.assertRaises(ssh.Refused): plan(p=p)

    def test_transition_requires_retained_revocation_tombstones(self):
        old = policy(hosts=['socrat-1', 'socrat-2'])
        with self.assertRaises(ssh.Refused): ssh.validate_transition(policy(), [old])
        moved = policy(hosts=['socrat-1'], revoked=['socrat-2'])
        ssh.validate_transition(moved, [old])
        with self.assertRaises(ssh.Refused): ssh.validate_transition({'assignments': []}, [old])
        # The tombstone cannot vanish in a subsequent commit either.
        with self.assertRaises(ssh.Refused): ssh.validate_transition(policy(), [moved])

    def test_disabled_and_removed_hosts_need_no_live_identity(self):
        p = policy('disabled', hosts=['socrat-1'], revoked=['socrat-2'])
        def unavailable(ident): raise AssertionError('Must not call IdP for revocation')
        payload, _ = ssh.build_plan(ssh.bindings_map(ledger()), p, unavailable)
        for entries in payload['by_host'].values():
            self.assertEqual(entries[0]['state'], 'disabled')
            self.assertEqual(entries[0]['authorized_keys'], [])
            self.assertEqual(entries[0]['key_fingerprints'], [])
        payload, _ = plan(p=policy(revoked=['socrat-2']))
        self.assertEqual(payload['by_host']['socrat-2'][0]['state'], 'disabled')
        self.assertEqual(payload['by_host']['socrat-1'][0]['state'], 'present')

    def test_inactive_service_and_missing_keys_refuse_active_export(self):
        for update in [{'is_active': False}, {'type': 'service_account'}, {'attributes': {}},
                       {'attributes': {'ssh_public_keys': []}}, {'attributes': {'ssh_public_keys': KEY}}]:
            u = user(); u.update(update)
            with self.subTest(update=update), self.assertRaises(ssh.Refused): plan(u=u)


class HistoryTests(unittest.TestCase):
    def test_real_committed_history_catches_rebinding_and_removed_scope(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            binding_path, policy_path = root / 'bindings.json', root / 'policy.json'
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True, text=True,
                                      capture_output=True).stdout
            git('init', '-q'); git('config', 'user.name', 'Offline Test'); git('config', 'user.email', 'test@example.invalid')
            binding_path.write_text(json.dumps(ledger()))
            policy_path.write_text(json.dumps(policy(hosts=['socrat-1', 'socrat-2'])))
            git('add', '.'); git('commit', '-qm', 'Reviewed enrollment')
            with patch.object(ssh, 'ROOT', root), patch.object(ssh, 'BINDINGS', binding_path), patch.object(ssh, 'POLICY', policy_path):
                histories = ssh.binding_history()
                self.assertEqual(histories, [ledger()])
                with self.assertRaises(ssh.Refused): ssh.validate_history({UUID: 'other'}, histories)
                with self.assertRaises(ssh.Refused): ssh.validate_transition(policy(), ssh.policy_history())
                moved = policy(revoked=['socrat-2'])
                ssh.validate_transition(moved, ssh.policy_history())
            (root / '.git/shallow').write_text(git('rev-parse', 'HEAD').strip() + '\n')
            with patch.object(ssh, 'ROOT', root), patch.object(ssh, 'BINDINGS', binding_path):
                with self.assertRaisesRegex(ssh.Refused, 'Shallow'): ssh.binding_history()


class KeyTests(unittest.TestCase):
    def test_real_openssh_parser_strips_comments_and_handles_two_tim_keys(self):
        keys, fingerprints = ssh.public_keys(TIM['authorized_keys'])
        self.assertEqual(len(keys), 2); self.assertEqual(len(set(fingerprints)), 2)
        self.assertTrue(all(len(k.split()) == 2 for k in keys))
        self.assertEqual(ssh.public_keys([KEY + ' ; $(touch /tmp/should-not-execute)'])[0], [KEY.rsplit(' ', 1)[0]])

    def test_invalid_private_cert_options_multiline_and_fake_base64_rejected(self):
        for line in ['-----BEGIN OPENSSH PRIVATE KEY-----', 'command="id" ' + KEY,
                     KEY + '\n' + KEY, KEY + '\r', KEY + '\x00', 'ssh-ed25519 AAAA',
                     KEY.replace('ssh-ed25519 ', 'ssh-ed25519-cert-v01@openssh.com ', 1),
                     KEY.replace('ssh-ed25519 ', 'ssh-rsa ', 1)]:
            with self.subTest(line=line[:24]), self.assertRaises(ssh.Refused): ssh.public_keys([line])
        with self.assertRaises(ssh.Refused): ssh.public_keys([KEY, KEY])
        with patch.object(ssh.subprocess, 'run', side_effect=FileNotFoundError), self.assertRaises(ssh.Refused):
            ssh.public_keys([KEY])


class ApiTests(unittest.TestCase):
    def api(self, doc=None):
        api = ssh.Authentik('https://auth.example.invalid', 'fake-test-token')
        api.opener.open = lambda req, timeout: io.BytesIO(json.dumps(doc if doc is not None else {
            'pagination': {'next': None}, 'results': [user()]}).encode())
        return api

    def test_fixed_get_uuid_tls_and_no_redirects(self):
        api = self.api(); seen = []
        def opened(req, timeout):
            seen.append(req)
            return io.BytesIO(json.dumps({'pagination': {'next': None}, 'results': [user()]}).encode())
        api.opener.open = opened
        self.assertEqual(api.user(UUID)['uuid'], UUID)
        req = seen[0]
        self.assertEqual(req.get_method(), 'GET'); self.assertIsNone(req.data)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)['uuid'], [UUID])
        with self.assertRaises(ssh.Refused):
            ssh.NoRedirect().redirect_request(req, None, 302, '', {}, 'https://elsewhere.invalid')
        import ssl
        handler = next(h for h in api.opener.handlers if isinstance(h, ssh.urllib.request.HTTPSHandler))
        self.assertEqual(handler._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(handler._context.check_hostname)

    def test_http_credentials_bad_tokens_and_incomplete_uuid_lookups_refused(self):
        for url in ['http://auth.invalid', 'https://user:pass@auth.invalid', 'https://auth.invalid/api/v3',
                    'https://auth.invalid/#fragment']:
            with self.assertRaises(ssh.Refused): ssh.Authentik(url, 'fake')
        for token in [None, '', 'token\nInjected: yes']:
            with self.assertRaises(ssh.Refused): ssh.Authentik('https://auth.invalid', token)
        for rows in [[], [user(), user()], [{**user(), 'uuid': OTHER}], [{'uid': UUID}]]:
            with self.assertRaises(ssh.Refused): self.api({'results': rows, 'pagination': {'next': None}}).user(UUID)
        with self.assertRaises(ssh.Refused): self.api({'results': [user()], 'pagination': {'next': 2}}).user(UUID)
        api = self.api()
        api.opener.open = lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError('sensitive-response'))
        with self.assertRaises(ssh.Refused) as caught: api.user(UUID)
        self.assertNotIn('sensitive', str(caught.exception))


class ExportTests(unittest.TestCase):
    def test_explicit_digest_private_new_file_and_public_only_payload(self):
        payload, _ = plan()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'ssh.json'
            with self.assertRaises(ssh.Refused): ssh.export(path, payload, None)
            self.assertFalse(path.exists())
            ssh.export(path, payload, ssh.digest(payload))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            data = json.loads(path.read_text())
            self.assertEqual(data['homelab_authentik_ssh_payload'], payload)
            self.assertNotIn('fake-test-token', path.read_text())
            self.assertNotIn('email', path.read_text()); self.assertNotIn('attributes', path.read_text())
            with self.assertRaises(ssh.Refused): ssh.export(path, payload, ssh.digest(payload))
            changed = copy.deepcopy(payload); changed['required_hosts'].append('unreviewed')
            with self.assertRaises(ssh.Refused): ssh.export(Path(d) / 'new.json', changed, ssh.digest(payload))
        with self.assertRaises(ssh.Refused): ssh.export(ROOT / 'unsafe-export.json', payload, ssh.digest(payload))

    def test_default_empty_plan_no_api_no_files_and_snapshots_never_export(self):
        with patch.object(ssh, 'Authentik', side_effect=AssertionError('No API for empty policy')):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(ssh.main([]), 0)
        self.assertEqual(json.loads(out.getvalue())['assignments'], [])
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ssh.main(['--snapshot', '/not-read', '--export', '/not-written']), 1)

    def test_duplicate_json_fields_fail_closed_without_value_echo(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'bad.json'; path.write_text('{"uuid":"SECRET", "uuid":"OTHER"}')
            with self.assertRaises(ssh.Refused) as error: ssh.read_json(path)
            self.assertNotIn('SECRET', str(error.exception))


class HostBindingTests(unittest.TestCase):
    def setUp(self):
        self.real_location = self.host.verify_key_location
        self.location = patch.object(self.host, 'verify_key_location', return_value=Path('/unused-test-key-path')).start()
        self.addCleanup(patch.stopall)

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('host_binding', ROOT / 'ansible/files/verify_authentik_ssh_binding.py')
        cls.host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.host)

    def test_no_existing_account_is_automatically_adopted(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / 'bindings'
            with patch.object(self.host.pwd, 'getpwnam', side_effect=KeyError):
                result = self.host.verify('guest', UUID, directory)
                self.assertFalse(result['accountExists'])
                self.assertFalse(directory.exists())
            with patch.object(self.host.pwd, 'getpwnam', return_value=object()):
                with self.assertRaisesRegex(ValueError, 'Existing unbound'):
                    self.host.verify('guest', UUID, directory)
            for name in ['root', 'alchemmist', 'ghactions', 'guest;id', '../guest']:
                with self.assertRaises(ValueError): self.host.verify(name, UUID, directory)

    def test_root_marker_is_immutable_private_and_not_symlink(self):
        from types import SimpleNamespace
        original_stat = Path.lstat
        def root_stat(path):
            info = original_stat(path)
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode, st_size=info.st_size)
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d) / 'bindings'; directory.mkdir(mode=0o700)
            marker = directory / 'guest.json'; marker.write_text(json.dumps({'name': 'guest', 'uuid': UUID}))
            marker.chmod(0o600)
            with patch.object(Path, 'lstat', root_stat), patch.object(self.host.pwd, 'getpwnam',
                    return_value=SimpleNamespace(pw_dir='/home/guest', pw_shell='/bin/bash')):
                self.assertTrue(self.host.verify('guest', UUID, directory)['bindingVerified'])
                with self.assertRaisesRegex(ValueError, 'mismatch'): self.host.verify('guest', OTHER, directory)
                marker.chmod(0o644)
                with self.assertRaises(ValueError): self.host.verify('guest', UUID, directory)
                marker.unlink(); marker.symlink_to(directory / 'absent')
                with self.assertRaises(ValueError): self.host.verify('guest', UUID, directory)

    def test_marked_nonstandard_home_rejected_before_key_writes(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            # Metadata is mocked only to allow a non-root offline test process.
            original = Path.lstat
            def root_stat(path):
                info = original(path)
                return SimpleNamespace(st_uid=0, st_mode=info.st_mode, st_size=info.st_size)
            directory.chmod(0o700)
            marker = directory / 'guest.json'
            marker.write_text(json.dumps({'name': 'guest', 'uuid': UUID})); marker.chmod(0o600)
            with patch.object(Path, 'lstat', root_stat), patch.object(self.host.pwd, 'getpwnam',
                    return_value=SimpleNamespace(pw_dir='/srv/guest', pw_shell='/bin/bash')):
                with self.assertRaisesRegex(ValueError, 'Nonstandard passwd home'):
                    self.host.verify('guest', UUID, directory)
                self.location.assert_not_called()

    def test_effective_key_sources_and_contextual_configs_fail_closed(self):
        settings = {'authorizedkeysfile': '.ssh/authorized_keys', 'authorizedkeyscommand': 'none',
                    'trustedusercakeys': 'none', 'pubkeyauthentication': 'yes', 'passwordauthentication': 'no',
                    'kbdinteractiveauthentication': 'no', 'hostbasedauthentication': 'no', 'gssapiauthentication': 'no',
                    'kerberosauthentication': 'no'}
        def response(values):
            return subprocess.CompletedProcess([], 0, '\n'.join(k + ' ' + v for k, v in values.items()), '')
        with tempfile.TemporaryDirectory() as d, patch.object(Path, 'is_symlink', return_value=False):
            config = Path(d) / 'sshd_config'; config.write_text('# synthetic test config\n')
            with patch.object(self.host.subprocess, 'run', return_value=response(settings)):
                self.assertEqual(self.real_location('guest', config), Path('/home/guest/.ssh/authorized_keys'))
            for field, value in [('authorizedkeysfile', '.ssh/authorized_keys .ssh/authorized_keys2'),
                                 ('authorizedkeysfile', '/srv/keys/%u'), ('authorizedkeysfile', 'none'),
                                 ('authorizedkeyscommand', '/opt/key-fetch'), ('trustedusercakeys', '/etc/ssh/ca.pub'),
                                 ('passwordauthentication', 'yes'), ('kbdinteractiveauthentication', 'yes')]:
                with self.subTest(field=field, value=value), patch.object(self.host.subprocess, 'run',
                        return_value=response({**settings, field: value})), self.assertRaises(ValueError):
                    self.real_location('guest', config)
            included = Path(d) / 'extra.conf'; included.write_text('Match=Address 192.0.2.0/24\n AuthorizedKeysFile /srv/keys/%u\n')
            config.write_text('Include=' + str(included) + '\n')
            with self.assertRaisesRegex(ValueError, 'Contextual'):
                self.real_location('guest', config)
            config.write_text('# config\n')
            with patch.object(self.host.subprocess, 'run', return_value=response(settings)), \
                    patch.object(Path, 'is_symlink', return_value=True), self.assertRaisesRegex(ValueError, 'Symlink'):
                self.real_location('guest', config)

    @unittest.skipUnless(shutil.which('sshd'), 'actual OpenSSH sshd required')
    def test_real_openssh_hash_include_cannot_hide_match(self):
        # Real daemon parsing demonstrates why shell comments are not adequate.
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            key = directory / 'host_key'
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
                           check=True, capture_output=True)
            included = directory / 'extra#context.conf'
            included.write_text('Match User guest\n AuthorizedKeysFile /srv/old/%u.keys\n')
            config = directory / 'sshd_config'
            prefix = 'HostKey ' + str(key) + '\nAuthorizedKeysFile .ssh/authorized_keys\n'
            config.write_text(prefix + 'Include ' + str(included) + '\n')
            command = [shutil.which('sshd'), '-T', '-f', str(config)]
            normal = subprocess.run(command, capture_output=True, text=True, check=True).stdout
            matched = subprocess.run(command + ['-C', 'user=guest,host=localhost,addr=127.0.0.1'],
                                     capture_output=True, text=True, check=True).stdout
            self.assertIn('authorizedkeysfile .ssh/authorized_keys\n', normal)
            self.assertIn('authorizedkeysfile /srv/old/%u.keys\n', matched)
            with self.assertRaisesRegex(ValueError, 'Unsupported SSH Include'):
                self.host.reject_contextual_config(config)
            # Quoted hash, escaped hash and trailing-comment variants are also
            # outside our documented strict subset, never silently truncated.
            for argument in ['"' + str(included) + '"', str(included).replace('#', '\\#'),
                             str(directory / 'plain.conf') + ' # comment']:
                config.write_text(prefix + 'Include ' + argument + '\n')
                with self.subTest(argument=argument), self.assertRaises(ValueError):
                    self.host.reject_contextual_config(config)
            plain = directory / 'plain.conf'
            plain.write_text('# supported full-line comment\nPasswordAuthentication no\n')
            config.write_text(prefix + 'Include=' + str(plain) + '\n')
            self.host.reject_contextual_config(config)
            subprocess.run(command, capture_output=True, check=True)
            plain.write_text('Match User guest\n AuthorizedKeysFile /srv/old/%u.keys\n')
            with self.assertRaisesRegex(ValueError, 'Contextual'):
                self.host.reject_contextual_config(config)

    def test_exact_fingerprints_rotation_and_disabled_zero_keys(self):
        from types import SimpleNamespace
        _, expected = ssh.public_keys([KEY])
        with tempfile.TemporaryDirectory() as d:
            keyfile = Path(d) / 'authorized_keys'
            self.location.return_value = keyfile
            with patch.object(self.host, 'verify', return_value={'accountExists': True}), \
                    patch.object(self.host.pwd, 'getpwnam', return_value=SimpleNamespace(pw_shell='/usr/sbin/nologin')):
                keyfile.write_text(KEY + '\n')
                self.assertEqual(self.host.verify_keys('guest', UUID, 'present', expected)['keyCount'], 1)
                # Rotation cannot pass while an old extra effective key remains.
                keyfile.write_text('\n'.join(TIM['authorized_keys']) + '\n')
                with self.assertRaisesRegex(ValueError, 'fingerprints differ'):
                    self.host.verify_keys('guest', UUID, 'present', expected)
                keyfile.write_text(KEY + '\n')
                with self.assertRaisesRegex(ValueError, 'fingerprints differ'):
                    self.host.verify_keys('guest', UUID, 'disabled', [])
                keyfile.write_text('')
                self.assertEqual(self.host.verify_keys('guest', UUID, 'disabled', [])['keyCount'], 0)
                keyfile.write_text('command="id" ' + KEY + '\n')
                with self.assertRaises(ValueError):
                    self.host.verify_keys('guest', UUID, 'present', expected)

    def test_apply_lock_is_exclusive_and_spans_preflight_to_exact_verification(self):
        play = yaml.safe_load((ROOT / 'ansible/playbooks/authentik-ssh-users.yml').read_text())[0]
        outer = play['tasks'][-1]['block']
        acquire, protected = outer
        self.assertEqual(acquire['ansible.builtin.command']['argv'][0], 'mkdir')
        self.assertNotIn('creates', acquire['ansible.builtin.command'])
        self.assertNotIn('ignore_errors', acquire)
        tasks = protected['block']
        self.assertIn('Refuse adoption', tasks[0]['name'])
        self.assertIn('exact effective key', tasks[-1]['name'])
        role = next(t for t in tasks if 'ansible.builtin.include_role' in t)
        self.assertTrue(role['vars']['homelab_authentik_ssh_scoped'])
        user_tasks = yaml.safe_load((ROOT / 'ansible/roles/users/tasks/main.yml').read_text())
        home = next(t['ansible.builtin.user']['home'] for t in user_tasks if 'ansible.builtin.user' in t)
        self.assertIn('homelab_authentik_ssh_scoped | default(false)', home)
        self.assertIn('else omit', home)  # manual users keep the previous home behavior
        self.assertEqual(protected['always'][0]['ansible.builtin.command']['argv'][0], 'rmdir')
        # Exercise the actual lock primitives without remote/root writes. A competing
        # writer must fail, not skip acquisition and proceed with another UUID.
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / 'apply.lock'
            first = subprocess.run(['mkdir', '-m', '0700', str(lock)], capture_output=True)
            second = subprocess.run(['mkdir', '-m', '0700', str(lock)], capture_output=True)
            self.assertEqual(first.returncode, 0); self.assertNotEqual(second.returncode, 0)
            subprocess.run(['rmdir', str(lock)], check=True)


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook unavailable')
class AnsibleIntentTests(unittest.TestCase):
    def run_play(self, payload, *flags, manual=False, review=None):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path / 'inventory.yml').write_text(yaml.safe_dump({'all': {'children': {'Socrat': {'hosts': {
                'socrat-1': {'ansible_connection': 'local', 'homelab_users': [TIM] if manual else []},
                'socrat-2': {'ansible_connection': 'local', 'homelab_users': []}}}}}}))
            (path / 'export.json').write_text(json.dumps({'homelab_authentik_ssh_payload': payload,
                'homelab_authentik_ssh_review_sha256': review or ssh.digest(payload)}))
            # Everything here MUST remain default intent-only or --check; never enable real apply.
            return subprocess.run(['ansible-playbook', '-i', str(path / 'inventory.yml'),
                'playbooks/authentik-ssh-users.yml', '-e', '@' + str(path / 'export.json'), *flags],
                cwd=ROOT / 'ansible', capture_output=True, text=True, timeout=60,
                env={**os.environ, 'ANSIBLE_NOCOLOR': '1', 'ANSIBLE_LOCAL_TEMP': str(path / 'ansible-tmp')})

    def test_default_and_check_are_local_no_mutations(self):
        payload, _ = plan(p=policy(revoked=['socrat-2']))
        for flags in [[], ['--check'], ['--check', '-e', 'homelab_authentik_ssh_apply=true',
                                       '-e', 'homelab_authentik_ssh_approval=' + ssh.digest(payload)]]:
            result = self.run_play(payload, *flags)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('changed=0', result.stdout)
            self.assertIn('read-only-intent-check', result.stdout)
            self.assertNotIn('Manage personal accounts', result.stdout)
            self.assertNotIn(KEY.split()[1], result.stdout)

    def test_unknown_hosts_limits_overlap_and_unguarded_apply_refused(self):
        payload, _ = plan(p=policy(revoked=['socrat-2']))
        result = self.run_play(payload, review='0' * 64)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        result = self.run_play(payload, '--limit', 'socrat-1')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        result = self.run_play(payload, '--check', '-e', 'homelab_authentik_ssh_apply=true')
        self.assertNotEqual(result.returncode, 0, result.stdout)
        payload, _ = plan(p=policy(hosts=['unknown-host']))
        self.assertNotEqual(self.run_play(payload).returncode, 0)
        payload, _ = ssh.build_plan(ssh.bindings_map(ledger('tim')), policy(), lambda ident: user())
        self.assertNotEqual(self.run_play(payload, manual=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
