"""Root-only, scoped Authentik SSH pre/postflight. Never rewrite unsupported hosts.

The playbook holds a host-wide mkdir lock from preflight through postflight.
No marker is inferred from usernames, email, groups or keys.
"""
import argparse
import glob
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import uuid

DIRECTORY = Path('/var/lib/homelab-authentik-ssh-bindings')
CONFIG = Path('/etc/ssh/sshd_config')


def reject_contextual_config(path=CONFIG, seen=None):
    """We cannot prove all Match contexts via one sshd -T -C probe. Reject them.

    Follow OpenSSH Include globs, including inside included files. This deliberately
    supports less than sshd, instead of silently checking one client address only.
    """
    seen = set() if seen is None else seen
    path = path.resolve(strict=True)
    if path in seen or len(seen) >= 100:
        raise ValueError('Recursive/oversized SSH configuration unsupported')
    seen.add(path)
    for line in path.read_text().splitlines():
        # Deliberately accept a strict subset rather than emulate OpenSSH with
        # shell tokenization: an unquoted # may be literal in an Include path.
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        directive = re.fullmatch(r'([A-Za-z][A-Za-z0-9]*)(?:\s*=\s*|\s+)(.*)', stripped)
        if directive is None:
            raise ValueError('Unsupported SSH directive syntax')
        keyword, arguments = directive.groups()
        if keyword.lower() == 'match':
            raise ValueError('Contextual SSH configuration unsupported')
        if keyword.lower() == 'include':
            # No quotes, escapes, hash, tilde, percent expansions or comments.
            # Administrators may use those with sshd, but this importer refuses
            # them instead of possibly checking a different effective key file.
            patterns = arguments.split()
            if not patterns or any(not re.fullmatch(r'[A-Za-z0-9_./*?\[\]-]+', p) for p in patterns):
                raise ValueError('Unsupported SSH Include syntax')
            for pattern in patterns:
                if not pattern.startswith('/'):
                    pattern = '/etc/ssh/' + pattern
                for included in sorted(glob.glob(pattern)):
                    reject_contextual_config(Path(included), seen)


def verify_key_location(name, config=CONFIG):
    reject_contextual_config(config)
    parsed = subprocess.run([shutil.which('sshd') or '/usr/sbin/sshd', '-T'],
                            text=True, capture_output=True, check=True)
    settings = dict(line.split(None, 1) for line in parsed.stdout.splitlines() if line.strip())
    allowed = {'.ssh/authorized_keys', '%h/.ssh/authorized_keys', '/home/' + name + '/.ssh/authorized_keys'}
    if (settings.get('authorizedkeysfile') not in allowed or
            settings.get('authorizedkeyscommand') != 'none' or
            settings.get('trustedusercakeys') != 'none' or
            settings.get('pubkeyauthentication') != 'yes' or
            any(settings.get(k) != 'no' for k in ['passwordauthentication', 'kbdinteractiveauthentication',
                                                  'hostbasedauthentication', 'gssapiauthentication',
                                                  'kerberosauthentication'])):
        raise ValueError('Unsupported effective SSH key source/authentication policy')
    # Do not follow home/key symlinks and then mistake an unrelated file for revocation.
    for path in [Path('/home'), Path('/home') / name, Path('/home') / name / '.ssh',
                 Path('/home') / name / '.ssh/authorized_keys']:
        if path.is_symlink():
            raise ValueError('Symlink home/key location unsupported')
    return Path('/home') / name / '.ssh/authorized_keys'


def verify(name, ident, directory=DIRECTORY):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', name) or name in {'root', 'alchemmist', 'ghactions'}:
        raise ValueError('Restricted username required')
    if str(uuid.UUID(ident)) != ident or uuid.UUID(ident).int == 0:
        raise ValueError('Canonical UUID required')
    try:
        account = pwd.getpwnam(name)
        exists = True
    except KeyError:
        account = None
        exists = False
    marker = directory / (name + '.json')
    if os.path.lexists(directory):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('Enrollment directory must be root-owned and private')
    if os.path.lexists(marker):
        info = marker.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 1024:
            raise ValueError('Enrollment marker must be a private root-owned regular file')
        if json.loads(marker.read_text()) != {'name': name, 'uuid': ident}:
            raise ValueError('Immutable host binding mismatch')
    elif exists:
        raise ValueError('Existing unbound Linux account: stop for separately reviewed migration')
    if exists and account.pw_dir != '/home/' + name:
        raise ValueError('Nonstandard passwd home unsupported')
    verify_key_location(name)
    return {'bindingVerified': True, 'accountExists': exists}


def fingerprints(path):
    """Parse every non-comment line; reject options, duplicates and invalid keys."""
    result = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not re.fullmatch(r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com) [A-Za-z0-9+/]+={0,3}( .*)?', line):
            raise ValueError('Unsupported effective key line')
        with tempfile.NamedTemporaryFile(mode='w') as key:
            key.write(line + '\n'); key.flush()
            parsed = subprocess.run(['ssh-keygen', '-lf', key.name, '-E', 'sha256'],
                                    text=True, capture_output=True, check=True)
        match = re.fullmatch(r'\d+ (SHA256:[A-Za-z0-9+/]+) .+\n?', parsed.stdout)
        if not match or match[1] in result:
            raise ValueError('Invalid/duplicate effective key')
        result.append(match[1])
    return sorted(result)


def verify_keys(name, ident, state, expected, directory=DIRECTORY):
    if (state not in {'present', 'disabled'} or not isinstance(expected, list) or
            any(not isinstance(x, str) or not re.fullmatch(r'SHA256:[A-Za-z0-9+/]+', x) for x in expected) or
            len(expected) != len(set(expected)) or (state == 'disabled' and expected) or
            (state == 'present' and not expected)):
        raise ValueError('Invalid expected key state')
    if not verify(name, ident, directory)['accountExists']:
        raise ValueError('Applied account missing')
    actual = fingerprints(verify_key_location(name))
    if actual != sorted(expected):
        raise ValueError('Effective key fingerprints differ from reviewed assignment')
    if state == 'disabled' and pwd.getpwnam(name).pw_shell != '/usr/sbin/nologin':
        raise ValueError('Disabled shell mismatch')
    return {'effectiveKeysVerified': True, 'keyCount': len(actual)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    parser.add_argument('uuid')
    parser.add_argument('--state', choices=['present', 'disabled'])
    parser.add_argument('--expected-fingerprints')
    args = parser.parse_args()
    try:
        if args.state is not None:
            result = verify_keys(args.name, args.uuid, args.state, json.loads(args.expected_fingerprints))
        else:
            result = verify(args.name, args.uuid)
        print(json.dumps(result))
    except (ValueError, OSError, TypeError, subprocess.SubprocessError):
        # Never print raw files/exception text from a host.
        raise SystemExit('SSH binding/key verification refused; inspect supported host policy and root enrollment marker')
