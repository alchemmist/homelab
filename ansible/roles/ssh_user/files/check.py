#!/usr/bin/env python3
"""Read-only key/account checks. Never emit key material, password hashes or sudo output."""
import argparse
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile

PROTECTED = {'root', 'alchemmist', 'ghactions', 'nobody'}
PRIVILEGED = {'root', 'sudo', 'wheel', 'admin', 'docker', 'disk', 'lxd', 'incus', 'kvm', 'libvirt', 'shadow', 'storage', 'podman', 'containerd', 'crio'}
KEY = re.compile(r'^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com) ([A-Za-z0-9+/]+={0,2})(?: [^\r\n]*)?$')


def require(ok, message):
    if not ok:raise ValueError(message)


def username(name):
    require(bool(re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', name)) and name not in PROTECTED,
            'Invalid or protected Linux username')


def fingerprint(line):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as f:
        f.write(line+'\n'); f.flush()
        r = subprocess.run(['ssh-keygen', '-l', '-E', 'sha256', '-f', f.name], capture_output=True, text=True)
    require(r.returncode == 0 and len(r.stdout.splitlines()) == 1, 'Invalid OpenSSH public key')
    fields = r.stdout.split()
    require(len(fields) >= 2 and fields[1].startswith('SHA256:'), 'Cannot validate public-key fingerprint')
    return fields[1]


def validate(name, text):
    username(name)
    require(isinstance(text, str) and len(text) <= 16384, 'Supply one OpenSSH public key')
    # Strip a normal public-file line ending, not arbitrary embedded controls.
    text = text.rstrip('\r\n')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in text), 'Multiline/control characters are forbidden')
    match = KEY.fullmatch(text)
    require(match is not None, 'Supply a public key, not private material, options or a certificate')
    canonical = match.group(1)+' '+match.group(2)
    fp = fingerprint(canonical)
    return {'username': name, 'public_key': canonical, 'fingerprint': fp}


def safe_paths(name, account):
    home = Path('/home')/name
    require(account is None or account.pw_dir == str(home), 'Nonstandard home requires separate review')
    paths = [Path('/home'), home, home/'.ssh', home/'.ssh/authorized_keys']
    for path in paths:
        require(not path.is_symlink(), 'Symlink in managed SSH path; no changes permitted')
        if path.exists():
            mode = path.stat().st_mode
            require(stat.S_ISREG(mode) if path.name == 'authorized_keys' else stat.S_ISDIR(mode),
                    'Unexpected object in managed SSH path')
            if path.name == 'authorized_keys':
                require(path.stat().st_nlink == 1, 'Hard-linked authorized_keys requires separate review')
            if account and path in [home/'.ssh', home/'.ssh/authorized_keys']:
                require(path.stat().st_uid == account.pw_uid, 'SSH path belongs to another identity; no takeover')
    require(account is not None or not home.exists(), 'Unbound existing home; no automatic adoption')
    if account and home.exists():
        require(home.stat().st_uid == account.pw_uid, 'Home belongs to another identity')
        require(not stat.S_IMODE(home.stat().st_mode) & 0o022, 'Group/world-writable home requires separate review')
    return home


def ssh_policy(name):
    daemon = shutil.which('sshd') or '/usr/sbin/sshd'
    r = subprocess.run([daemon, '-T', '-C', 'user='+name+',host=socrat,addr=100.100.240.102'],
                       capture_output=True, text=True)
    require(r.returncode == 0, 'Cannot inspect effective sshd configuration')
    settings = dict(line.split(' ', 1) for line in r.stdout.splitlines() if ' ' in line)
    require(settings.get('pubkeyauthentication') == 'yes' and settings.get('usepam') == 'yes',
            'Host must support public keys and PAM for password-locked accounts; sshd was not modified')
    allowed_files = {'.ssh/authorized_keys', '%h/.ssh/authorized_keys', '/home/'+name+'/.ssh/authorized_keys'}
    require(bool(set(settings.get('authorizedkeysfile', '').split()) & allowed_files),
            'The managed authorized_keys file is not an effective SSH key source')


def inspect(name, expected=None, enforce=False):
    username(name)
    require(os.geteuid() == 0, 'Account verification requires root')
    require(not os.path.lexists(Path('/var/lib/homelab-authentik-ssh-bindings')/(name+'.json')),
            'Authentik-managed identity: use its reviewed lifecycle, not manual adoption')
    try:account = pwd.getpwnam(name)
    except KeyError:account = None
    home = safe_paths(name, account)
    ssh_policy(name)
    if account is None:
        require(not enforce, 'Account missing after apply')
        return {'username': name, 'exists': False, 'has_requested_key': False}
    uid_min = 1000
    for line in Path('/etc/login.defs').read_text().splitlines():
        if re.match(r'^\s*UID_MIN\s+\d+', line):uid_min = int(line.split()[1])
    require(account.pw_uid >= uid_min and account.pw_gid != 0, 'System/root account is protected')
    require(any(line.startswith(name+':') for line in Path('/etc/passwd').read_text().splitlines()),
            'Non-local account requires a separate identity provider procedure')
    groups = {grp.getgrgid(gid).gr_name for gid in os.getgrouplist(name, account.pw_gid)}
    require(not groups & PRIVILEGED, 'Existing privileged account: refuse changes, do not strip privileges')
    require(account.pw_shell in ['/bin/bash', '/usr/bin/bash', '/bin/sh', '/usr/bin/sh', '/bin/zsh', '/usr/bin/zsh'],
            'Disabled/non-login shell: explicit review required before granting SSH')
    sudo = subprocess.run(['sudo', '-n', '-l', '-U', name], capture_output=True, text=True,
                          env={**os.environ, 'LC_ALL': 'C'})
    denied = 'User '+name+' is not allowed to run sudo on '
    require(sudo.returncode in (0, 1) and denied in sudo.stdout+sudo.stderr
            and 'may run the following commands' not in sudo.stdout+sudo.stderr,
            'Effective sudo grant or unverifiable sudo policy; no SSH key will be installed')
    read = subprocess.run(['runuser', '-u', name, '--', 'test', '-r', '/etc/rancher/k3s/k3s.yaml'],
                          capture_output=True).returncode
    require(read == 1, 'Account can read administrative kubeconfig or its isolation cannot be verified')
    keys = home/'.ssh/authorized_keys'
    fingerprints = []
    if keys.exists():
        for line in keys.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                fingerprints.append(fingerprint(line))
    present = expected in fingerprints if expected else False
    locked = False
    for line in Path('/etc/shadow').read_text().splitlines():
        fields = line.split(':')
        if fields[0] == name:locked = fields[1].startswith(('!', '*')); break
    if enforce:
        require(present and locked, 'Requested key/password lock missing after apply')
        require(stat.S_IMODE((home/'.ssh').stat().st_mode) == 0o700 and
                stat.S_IMODE(keys.stat().st_mode) == 0o600 and
                (home/'.ssh').stat().st_uid == keys.stat().st_uid == account.pw_uid,
                'SSH file permissions/ownership incorrect after apply')
    return {'username': name, 'exists': True, 'group': grp.getgrgid(account.pw_gid).gr_name,
            'has_requested_key': present, 'key_count': len(fingerprints), 'password_locked': locked,
            'sudo': False, 'admin_kubeconfig_readable': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['validate', 'inspect', 'as-user'])
    p.add_argument('--username', required=True)
    p.add_argument('--fingerprint')
    p.add_argument('--enforce', action='store_true')
    a = p.parse_args()
    if a.mode == 'as-user':
        username(a.username)
        require(os.geteuid() != 0 and os.geteuid() == pwd.getpwnam(a.username).pw_uid,
                'SSH file writes must run as the target non-root user; review become overrides')
        result = {'username': a.username, 'target_user_execution': True}
    else:
        result = validate(a.username, sys.stdin.read()) if a.mode == 'validate' else inspect(a.username, a.fingerprint, a.enforce)
    print(json.dumps(result))


if __name__ == '__main__':
    try:main()
    except Exception as e:
        print(json.dumps({'status': 'blocked', 'reason': str(e) if isinstance(e, ValueError) else
                          'Verification failed; inspect host locally without dumping credentials'}))
        sys.exit(1)
