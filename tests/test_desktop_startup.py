import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'ansible/roles/desktop_session/files/configure_desktop_startup.py'
SPEC = importlib.util.spec_from_file_location('desktop_startup', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ZSH = shutil.which('zsh')
RUN = subprocess.run
LEGACY = '''if [ "$(tty)" = "/dev/tty1" -o "$(tty)" = "/dev/tty2" ] && [ -z "$(printenv HYPRLAND_INSTANCE_SIGNATURE)" ]; then
    exec ~/.local/bin/wlinitrc
fi
'''


class LoginRewriteTests(unittest.TestCase):
    def test_replaces_selector_preserving_surrounding_shell_configuration(self):
        before = 'export PATH="$HOME/.elan/bin:$PATH"\n'
        after = 'alias ll="ls -l"\n'
        self.assertEqual(MODULE.rewrite_login(before + LEGACY + after, True), before + MODULE.LOGIN_BLOCK + after)

    def test_existing_server_guard_is_normalized_and_idempotent(self):
        old = 'if [[ -o interactive && "$TTY" == /dev/tty1 ]]; then\n    exec /usr/local/bin/start-socrat-hyprland\nfi\n'
        result = MODULE.rewrite_login(old, True)
        self.assertEqual(result, MODULE.LOGIN_BLOCK)
        self.assertEqual(MODULE.rewrite_login(result, True), result)

    def test_nonselected_profile_loses_only_its_competing_startup(self):
        self.assertEqual(MODULE.rewrite_login('export EDITOR=vim\n' + LEGACY, False), 'export EDITOR=vim\n')

    def test_multiple_blocks_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'Multiple'):
            MODULE.rewrite_login(LEGACY + MODULE.LOGIN_BLOCK, True)

    def test_unknown_startup_is_refused_in_every_profile(self):
        for selected in (False, True):
            for prefix in ('', LEGACY):
                with self.subTest(selected=selected, prefix=bool(prefix)):
                    with self.assertRaises(ValueError):
                        MODULE.rewrite_login(prefix + 'exec start-hyprland\n', selected)

    @unittest.skipUnless(ZSH, 'zsh is required')
    def test_guard_only_starts_on_interactive_local_tty1_without_existing_display(self):
        block = MODULE.LOGIN_BLOCK.replace('exec /usr/local/bin/start-socrat-hyprland', 'print -r -- STARTED')
        cases = [({}, True), ({'SSH_CONNECTION': 'remote'}, False), ({'SSH_TTY': '/dev/pts/0'}, False),
                 ({'TTY': '/dev/tty2'}, False), ({'WAYLAND_DISPLAY': 'wayland-1'}, False), ({'DISPLAY': ':0'}, False)]
        for values, expected in cases:
            assignments = dict(TTY='/dev/tty1', SSH_CONNECTION='', SSH_TTY='', WAYLAND_DISPLAY='', DISPLAY='')
            assignments.update(values)
            script = '\n'.join(f'{key}={value!r}' for key, value in assignments.items()) + '\n' + block
            with self.subTest(values=values):
                result = RUN([ZSH, '-f', '-i', '-c', script], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('STARTED' in result.stdout, expected)
        result = RUN([ZSH, '-f', '-c', 'TTY=/dev/tty1\n' + block], capture_output=True, text=True)
        self.assertNotIn('STARTED', result.stdout)


class IdleConfigurationTests(unittest.TestCase):
    def test_retains_lock_dim_and_general_handlers(self):
        retained = 'general {\n    before_sleep_cmd = loginctl lock-session\n}\nlistener {\n    timeout = 120\n    on-timeout = brightnessctl set 10%\n}\nlistener {\n    timeout = 180\n    on-timeout = loginctl lock-session\n}\n'
        for command in ('poweroff', 'suspend', 'hibernate', 'hybrid-sleep', 'suspend-then-hibernate'):
            with self.subTest(command=command):
                shutdown = 'listener {\n    timeout = 1800\n    on-timeout = systemctl ' + command + '\n}\n'
                self.assertEqual(MODULE.remove_idle_shutdown(retained + shutdown), retained)
                self.assertEqual(MODULE.remove_idle_shutdown(retained), retained)


@unittest.skipUnless(ZSH, 'zsh is required')
class ConfigureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name).resolve()
        self.backups = self.home / '.local/state/homelab/desktop-backups'
        self.backups.mkdir(parents=True)
        user = SimpleNamespace(pw_dir=str(self.home), pw_shell='/usr/bin/zsh', pw_uid=os.getuid(), pw_gid=os.getgid())
        account = patch.object(MODULE.pwd, 'getpwnam', return_value=user)
        account.start()
        self.addCleanup(account.stop)
        runner = patch.object(MODULE.subprocess, 'run', side_effect=lambda args, **kwargs: RUN([ZSH, *args[1:]], **kwargs))
        runner.start()
        self.addCleanup(runner.stop)

    def configure(self, cleanup=False, disable_shutdown=False, check=False):
        return MODULE.configure(self.home, 'testuser', '.zshrc', cleanup, disable_shutdown, check=check)

    def test_preserves_symlink_target_mode_and_original_backup_then_is_idempotent(self):
        target = self.home / 'dotfiles/zshrc'
        target.parent.mkdir()
        target.write_text('export EDITOR=vim\n' + LEGACY)
        target.chmod(0o640)
        profile = self.home / '.zshrc'
        profile.symlink_to(target)
        result = self.configure()
        self.assertTrue(profile.is_symlink())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
        self.assertEqual((Path(result['backup']) / '.zshrc').read_text(), 'export EDITOR=vim\n' + LEGACY)
        self.assertIn(MODULE.LOGIN_BLOCK, target.read_text())
        before = target.stat().st_mtime_ns
        self.assertFalse(self.configure()['changed'])
        self.assertEqual(target.stat().st_mtime_ns, before)
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_archives_selector_symlinks_without_removing_their_sources_or_swaync(self):
        source = self.home / 'dotfiles/wlinitrc'
        source.parent.mkdir()
        source.write_text('exec tdm.sh\n')
        launcher = self.home / '.local/bin/wlinitrc'
        launcher.parent.mkdir()
        launcher.symlink_to(source)
        sway = self.home / '.config/sway'
        sway.mkdir(parents=True)
        (sway / 'config').write_text('old config')
        swaync = self.home / '.config/swaync'
        swaync.mkdir()
        result = self.configure(cleanup=True)
        self.assertEqual(set(result['archived']), {'wlinitrc', 'sway'})
        self.assertFalse(launcher.is_symlink())
        self.assertTrue((Path(result['backup']) / 'wlinitrc').is_symlink())
        self.assertEqual(source.read_text(), 'exec tdm.sh\n')
        self.assertTrue(swaync.exists())
        self.assertFalse(self.configure(cleanup=True)['changed'])

    def test_check_reports_planned_changes_without_writes_or_archives(self):
        profile = self.home / '.zshrc'
        profile.write_text(LEGACY)
        idle = self.home / '.config/hypr/hypridle.conf'
        idle.parent.mkdir(parents=True)
        idle_text = 'listener {\n    timeout = 1800\n    on-timeout = systemctl poweroff\n}\n'
        idle.write_text(idle_text)
        selector = self.home / '.local/bin/wlinitrc'
        selector.parent.mkdir()
        selector.write_text('exec tdm.sh\n')
        before = profile.stat().st_mtime_ns
        result = self.configure(cleanup=True, disable_shutdown=True, check=True)
        self.assertTrue(result['changed'])
        self.assertEqual(result['profiles'], ['.zshrc', 'hypridle.conf'])
        self.assertEqual(result['archived'], ['wlinitrc'])
        self.assertEqual(profile.read_text(), LEGACY)
        self.assertEqual(profile.stat().st_mtime_ns, before)
        self.assertEqual(idle.read_text(), idle_text)
        self.assertEqual(selector.read_text(), 'exec tdm.sh\n')
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_check_requires_no_backup_directory_and_does_not_create_profiles(self):
        self.backups.rmdir()
        result = self.configure(check=True)
        self.assertTrue(result['changed'])
        self.assertFalse((self.home / '.zshrc').exists())
        self.assertFalse(self.backups.exists())

    def test_check_reports_no_change_after_configuration(self):
        self.configure()
        before = list(self.backups.iterdir())
        self.assertFalse(self.configure(check=True)['changed'])
        self.assertEqual(list(self.backups.iterdir()), before)

    def test_check_still_rejects_invalid_shell_before_writes(self):
        profile = self.home / '.zshrc'
        profile.write_text('if then\n')
        with self.assertRaisesRegex(ValueError, 'Invalid zsh syntax'):
            self.configure(check=True)
        self.assertEqual(profile.read_text(), 'if then\n')
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_external_profile_symlink_is_rejected_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / 'profile'
            target.write_text('export EDITOR=vim\n')
            (self.home / '.zlogin').symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'outside'):
                self.configure()
            self.assertFalse((self.home / '.zshrc').exists())
            self.assertEqual(list(self.backups.iterdir()), [])
            self.assertEqual(target.read_text(), 'export EDITOR=vim\n')

    def test_invalid_shell_syntax_is_rejected_before_any_mutation(self):
        profile = self.home / '.zshrc'
        profile.write_text('if then\n')
        with self.assertRaisesRegex(ValueError, 'Invalid zsh syntax'):
            self.configure()
        self.assertEqual(profile.read_text(), 'if then\n')
        self.assertEqual(list(self.backups.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
