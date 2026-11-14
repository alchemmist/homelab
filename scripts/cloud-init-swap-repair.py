#!/usr/bin/env python3
"""Guarded Moscow-only repair of repeated provider swap initialization.

Never run dd/mkswap/swapon/swapoff or replay all cloud-init stages. Existing
systemd/fstab owns swap activation. Receipts are private and one-shot.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

EXPECTED = ['dd if=/dev/zero of=/swap.img bs=1MiB count=512',
            'mkswap /swap.img', 'chmod 0600 /swap.img', 'swapon /swap.img']
OVERRIDE = '# Managed by homelab: existing swap is activated by fstab/systemd.\n# Never recreate or reformat an active swap file at boot.\nbootcmd: []\n'
DEST = Path('/etc/cloud/cloud.cfg.d/99-homelab-preserve-swap.cfg')
RECEIPT = Path('/var/lib/homelab-recovery/20261114-cloud-init-swap')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate(base, others, swaps, fstab, size):
    require(base.get('bootcmd') == EXPECTED, 'Provider bootcmd differs; refuse')
    require(not any('bootcmd' in d for d in others), 'Another bootcmd owner exists')
    rows = [line.split() for line in swaps.splitlines()[1:] if line.strip()]
    require(any(r[0] == '/swap.img' and r[1] == 'file' for r in rows), 'Swap is not active')
    entries = [line.split() for line in fstab.splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    matching = [r for r in entries if r[0] == '/swap.img']
    require(bool(matching) and all(r == ['/swap.img', 'none', 'swap', 'sw', '0', '0'] for r in matching),
            'Persistent swap definition differs')
    require(size == 512 * 1024 * 1024, 'Unexpected swap file size')


def command(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout


def atomic(path, text, mode):
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    import yaml  # Existing cloud-init dependency on the target, not pip on production.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(os.geteuid() == 0 and socket.gethostname() == 'socrat-4', 'Moscow root only')
    require(not DEST.exists() and not RECEIPT.exists(), 'Existing attempt; inspect receipt, do not replay')
    base_path = Path('/etc/cloud/cloud.cfg')
    raw = base_path.read_text()
    others = [yaml.safe_load(p.read_text()) or {} for p in DEST.parent.glob('*.cfg')]
    # Instance user-data can override system configuration; refuse any competing bootcmd.
    for name in ['user-data.txt', 'cloud-config.txt']:
        p = Path('/var/lib/cloud/instance') / name
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text())
            except yaml.YAMLError:
                raise RuntimeError('Instance configuration is not a simple mapping')
            if isinstance(data, dict):
                others.append(data)
    before_stat = Path('/swap.img').stat()
    fstab = Path('/etc/fstab').read_text()
    validate(yaml.safe_load(raw), others, Path('/proc/swaps').read_text(), fstab, before_stat.st_size)
    before = {'base_sha256': hashlib.sha256(raw.encode()).hexdigest(),
              'fstab_sha256': hashlib.sha256(fstab.encode()).hexdigest(),
              'swap_inode': before_stat.st_ino, 'swap_mtime_ns': before_stat.st_mtime_ns,
              'swap_bytes': before_stat.st_size}
    require(command(['systemctl', 'is-active', 'swap.img.swap']).strip() == 'active', 'Swap unit inactive')
    if not args.apply:
        print(json.dumps({'preflight': 'accepted', 'changes': [str(DEST)], 'before': before}))
        return
    RECEIPT.mkdir(parents=True, mode=0o700)
    os.chmod(RECEIPT, 0o700)
    atomic(RECEIPT / 'before.json', json.dumps(before, indent=2), 0o600)
    atomic(RECEIPT / 'provider-cloud.cfg.private', raw, 0o600)
    atomic(RECEIPT / 'intent.json', json.dumps({'override': str(DEST), 'content': OVERRIDE}), 0o600)
    atomic(DEST, OVERRIDE, 0o644)
    # Validate only the corrected module. No networking, user/password, SSH or final stages.
    result = subprocess.run(['cloud-init', 'single', '--name', 'bootcmd', '--frequency', 'always'],
                            capture_output=True, text=True)
    atomic(RECEIPT / 'module.private.log', result.stdout + result.stderr, 0o600)
    require(result.returncode == 0, 'Corrected module failed; inspect private receipt; states not reset')
    after = Path('/swap.img').stat()
    require((after.st_ino, after.st_mtime_ns, after.st_size) ==
            (before_stat.st_ino, before_stat.st_mtime_ns, before_stat.st_size), 'Swap file changed')
    require(Path('/etc/fstab').read_text() == fstab and base_path.read_text() == raw,
            'Base configuration drift')
    require('/swap.img' in Path('/proc/swaps').read_text(), 'Swap no longer active')
    # Reset only stale service failed flags after source repair and successful module check.
    command(['systemctl', 'reset-failed', 'cloud-init-main.service', 'cloud-init-network.service'])
    for unit in ['cloud-init-main.service', 'cloud-init-network.service']:
        require(command(['systemctl', 'show', unit, '-p', 'ActiveState', '--value']).strip() != 'failed',
                'Failed unit state persists')
    atomic(RECEIPT / 'accepted.json', json.dumps({'module_exit': 0, 'swap_preserved': True,
           'fstab_preserved': True, 'base_preserved': True, 'historical_cloud_init_result_retained': True}), 0o600)
    print(json.dumps({'applied': True, 'module_exit': 0, 'swap_preserved': True,
                      'historical_result_retained': True, 'receipt': str(RECEIPT)}))


if __name__ == '__main__':
    main()
