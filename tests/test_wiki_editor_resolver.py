import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'ansible/roles/wiki_editor_client/files/wiki-editor-resolver.sh'


class WikiEditorResolverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='wiki-resolver-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.resolver_directory = self.root / 'resolvers'
        self.resolver_directory.mkdir()
        self.resolver = self.resolver_directory / 'wiki.socrat.alchemmist.xyz'
        self.marker = self.root / 'owned'
        self.log = self.root / 'commands.log'
        self.environment = {
            **os.environ,
            'FIXTURE_INTERFACE': 'utun7',
            'FIXTURE_ANSWER': '10.250.0.1',
            'FIXTURE_LOG': str(self.log),
            'FIXTURE_PRIMARY_FAILURE': '',
        }
        route = self.fixture('route', 'printf "interface: %s\\n" "$FIXTURE_INTERFACE"\n')
        dig = self.fixture('dig', '''printf 'dig %s\\n' "$*" >> "$FIXTURE_LOG"
case "$*" in
    *'@10.250.0.1'*)
        if [ -n "$FIXTURE_PRIMARY_FAILURE" ]; then exit 1; fi ;;
esac
printf '%s\\n' "$FIXTURE_ANSWER"
''')
        flush = self.fixture('flush', 'printf "flush\\n" >> "$FIXTURE_LOG"\n')
        kill = self.fixture('kill', 'printf "reload\\n" >> "$FIXTURE_LOG"\n')
        source = SOURCE.read_text()
        source = source.replace('/etc/resolver/.socrat-wiki.XXXXXX', shlex.quote(str(self.resolver_directory / '.socrat-wiki.XXXXXX')))
        source = source.replace('/etc/resolver/wiki.socrat.alchemmist.xyz', shlex.quote(str(self.resolver)))
        source = source.replace('/etc/resolver', shlex.quote(str(self.resolver_directory)))
        source = source.replace('/var/db/socrat-wiki-resolver-owned', shlex.quote(str(self.marker)))
        for original, replacement in {
            '/sbin/route': route,
            '/usr/bin/dig': dig,
            '/usr/bin/dscacheutil': flush,
            '/usr/bin/killall': kill,
        }.items():
            source = source.replace(original, shlex.quote(str(replacement)))
        for original in ('/usr/bin/awk', '/usr/bin/grep', '/bin/mkdir', '/usr/bin/mktemp', '/bin/rm', '/bin/chmod', '/usr/bin/cmp', '/usr/bin/touch', '/bin/mv'):
            executable = shutil.which(Path(original).name)
            self.assertIsNotNone(executable)
            source = source.replace(original, shlex.quote(executable))
        self.assertNotIn('/etc/resolver', source)
        self.assertNotIn('/var/db/', source)
        self.script = self.root / 'resolver.sh'
        self.script.write_text(source)

    def fixture(self, name, body):
        path = self.root / name
        path.write_text('#!/bin/sh\nset -eu\n' + body)
        path.chmod(0o700)
        return path

    def run_resolver(self, expected=0, **changes):
        result = subprocess.run(
            ['/bin/sh', str(self.script)],
            env={**self.environment, **changes},
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def commands(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_private_route_creates_owned_resolver_and_is_idempotent(self):
        self.run_resolver()
        self.assertEqual(self.resolver.read_text(), 'nameserver 10.250.0.1\ntimeout 1\noptions attempts:1\n')
        self.assertTrue(self.marker.exists())
        before = self.resolver.stat().st_mtime_ns
        self.run_resolver()
        self.assertEqual(self.resolver.stat().st_mtime_ns, before)
        self.assertEqual(self.commands().count('flush'), 1)
        self.assertEqual(self.commands().count('reload'), 1)
        self.assertEqual(list(self.resolver_directory.glob('.socrat-wiki.*')), [])

    def test_disconnect_removes_owned_override_and_restores_public_dns(self):
        self.run_resolver()
        self.run_resolver(FIXTURE_INTERFACE='en0')
        self.assertFalse(self.resolver.exists())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.commands().count('flush'), 2)
        self.run_resolver(FIXTURE_INTERFACE='en0')
        self.assertEqual(self.commands().count('flush'), 2)

    def test_unmanaged_override_is_preserved_and_rejected(self):
        contents = 'nameserver 192.0.2.1\n'
        self.resolver.write_text(contents)
        self.run_resolver(expected=1)
        self.assertEqual(self.resolver.read_text(), contents)
        self.assertFalse(self.marker.exists())
        self.assertNotIn('flush', self.commands())
        self.run_resolver(expected=1, FIXTURE_INTERFACE='en0')
        self.assertEqual(self.resolver.read_text(), contents)

    def test_public_dns_answer_does_not_enable_private_route(self):
        self.run_resolver(FIXTURE_ANSWER='109.173.40.247')
        self.assertFalse(self.resolver.exists())
        self.assertFalse(self.marker.exists())
        self.assertNotIn('flush', self.commands())

    def test_private_dns_answer_without_tunnel_does_not_enable_route(self):
        self.run_resolver(FIXTURE_INTERFACE='en0')
        self.assertFalse(self.resolver.exists())
        self.assertEqual(self.commands(), [])

    def test_private_dns_loss_removes_previously_enabled_route(self):
        self.run_resolver()
        self.run_resolver(FIXTURE_ANSWER='')
        self.assertFalse(self.resolver.exists())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.commands().count('flush'), 2)

    def test_unreachable_primary_uses_reachable_secondary(self):
        self.run_resolver(FIXTURE_PRIMARY_FAILURE='1')
        self.assertIn('nameserver 10.250.0.3\n', self.resolver.read_text())
        self.assertTrue(self.marker.exists())


if __name__ == '__main__':
    unittest.main()
