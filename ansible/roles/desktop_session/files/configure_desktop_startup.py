import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import tempfile


LOGIN_BLOCK = '''if [[ -o interactive && -z "${SSH_CONNECTION:-}" && -z "${SSH_TTY:-}" && "${TTY:-}" == /dev/tty1 && -z "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
    exec /usr/local/bin/start-socrat-hyprland
fi
'''
STARTUP_BLOCK = re.compile(
    r'(?m)^if [^\n]+\n[ \t]+exec (?:/usr/local/bin/start-socrat-hyprland|'
    r'~/\.local/bin/wlinitrc|/home/[^/\n]+/\.local/bin/wlinitrc)\nfi[ \t]*\n?'
)
IDLE_LISTENER = re.compile(r'(?ms)^listener\s*\{[^{}]*^\}[ \t]*\n?')
IDLE_SHUTDOWN = re.compile(r'(?m)^\s*on-timeout\s*=\s*systemctl\s+(?:poweroff|suspend|hibernate|hybrid-sleep|suspend-then-hibernate)\b')
LEGACY_PATHS = {
    '.local/bin/wlinitrc': 'wlinitrc',
    'scripts/tdm.sh': 'tdm.sh',
    '.config/sway': 'sway',
    '.config/swaylock': 'swaylock',
    '.config/swayidle': 'swayidle',
}


def rewrite_login(text, selected):
    matches = list(STARTUP_BLOCK.finditer(text))
    if len(matches) > 1:
        raise ValueError('Multiple startup blocks require manual review')
    residual = STARTUP_BLOCK.sub('', text)
    if re.search(r'(?m)^[^#\n]*\bexec\s+[^\n]*(?:Hyprland|start-hyprland|wlinitrc|tdm\.sh)', residual):
        raise ValueError('Unrecognized desktop startup command requires manual review')
    if matches:
        return STARTUP_BLOCK.sub(lambda _: LOGIN_BLOCK if selected else '', text)
    if not selected:
        return text
    return text + ('\n' if text and not text.endswith('\n') else '') + ('\n' if text else '') + LOGIN_BLOCK


def remove_idle_shutdown(text):
    return IDLE_LISTENER.sub(lambda match: '' if IDLE_SHUTDOWN.search(match.group()) else match.group(), text)


def replace_file(path, content, uid, gid):
    previous = path.stat() if path.exists() else None
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.homelab-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode) if previous else 0o644)
            os.fchown(stream.fileno(), previous.st_uid if previous else uid, previous.st_gid if previous else gid)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def configure(home, username, login_file, cleanup, disable_shutdown, check=False):
    user = pwd.getpwnam(username)
    if not user.pw_shell.endswith('/zsh'):
        raise ValueError('This setup requires the existing zsh login shell')
    home = home.resolve()
    if home != Path(user.pw_dir).resolve():
        raise ValueError('Home directory does not match the account')
    if login_file not in ['.zprofile', '.zshrc']:
        raise ValueError('Unsupported login file')
    edits = []
    for filename in ['.zprofile', '.zshrc', '.zlogin']:
        path = (home / filename).resolve()
        if not path.is_relative_to(home):
            raise ValueError('Profile resolves outside the user home')
        if not path.exists() and filename != login_file:
            continue
        old = path.read_text() if path.exists() else ''
        new = rewrite_login(old, filename == login_file)
        if old != new:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.zsh') as candidate:
                candidate.write(new)
                candidate.flush()
                result = subprocess.run(['/usr/bin/zsh', '-n', candidate.name], capture_output=True)
                if result.returncode:
                    raise ValueError('Invalid zsh syntax in ' + filename)
            edits.append((filename, path, new))
    if disable_shutdown:
        path = (home / '.config/hypr/hypridle.conf').resolve()
        if not path.is_relative_to(home):
            raise ValueError('Idle configuration resolves outside the user home')
        if path.exists():
            old = path.read_text()
            new = remove_idle_shutdown(old)
            if new != old:
                edits.append(('hypridle.conf', path, new))
    obsolete = [(home / name, label) for name, label in LEGACY_PATHS.items()
                if cleanup and ((home / name).exists() or (home / name).is_symlink())]
    if any(not path.parent.resolve().is_relative_to(home) for path, _ in obsolete):
        raise ValueError('Legacy configuration parent resolves outside the user home')
    if not edits and not obsolete:
        return {'changed': False, 'profiles': [], 'archived': []}
    if check:
        return {'changed': True, 'profiles': [label for label, _, _ in edits],
                'archived': [label for _, label in obsolete]}
    backup = home / '.local/state/homelab/desktop-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup.mkdir(mode=0o700)
    os.chown(backup, user.pw_uid, user.pw_gid)
    for label, path, new in edits:
        if path.exists():
            saved = backup / label
            shutil.copy2(path, saved)
            os.chown(saved, user.pw_uid, user.pw_gid)
        replace_file(path, new, user.pw_uid, user.pw_gid)
    for path, label in obsolete:
        path.rename(backup / label)
    return {'changed': True, 'profiles': [label for label, _, _ in edits],
            'archived': [label for _, label in obsolete], 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--login-file', choices=['.zprofile', '.zshrc'], required=True)
    parser.add_argument('--remove-selector', action='store_true')
    parser.add_argument('--disable-idle-shutdown', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(configure(args.home, args.user, args.login_file, args.remove_selector, args.disable_idle_shutdown, check=args.check)))


if __name__ == '__main__':
    main()
