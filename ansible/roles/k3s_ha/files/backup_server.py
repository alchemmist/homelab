import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

CONFIG_PATHS = [Path('/etc/rancher/k3s'), Path('/etc/systemd/system/k3s.service'), Path('/etc/systemd/system/k3s.service.env'), Path('/etc/systemd/system/k3s.service.d')]


def backup():
    root = Path('/var/backups/homelab-k3s')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix='pre-ha-', dir=root))
    for path in CONFIG_PATHS:
        target = destination / 'config' / path.relative_to('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, target, symlinks=True)
        elif path.exists():
            shutil.copy2(path, target)
    with sqlite3.connect('file:/var/lib/rancher/k3s/server/db/state.db?mode=ro', uri=True) as database:
        if database.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise RuntimeError('SQLite datastore integrity check failed')
    subprocess.run(['tar', '-C', '/var/lib/rancher/k3s', '-cpf', str(destination / 'server.tar'), 'server'], check=True)
    print(json.dumps({'backup': str(destination)}))


def restore(directory):
    directory = Path(directory).resolve()
    if directory.parent != Path('/var/backups/homelab-k3s') or not (directory / 'server.tar').is_file():
        raise RuntimeError('Unrecognized backup')
    server = Path('/var/lib/rancher/k3s/server')
    if server.exists():
        server.rename(directory / 'failed-server')
    subprocess.run(['tar', '-C', '/var/lib/rancher/k3s', '-xpf', str(directory / 'server.tar')], check=True)
    for path in CONFIG_PATHS:
        if path.is_dir():
            shutil.move(str(path), str(directory / ('failed-' + path.name)))
        elif path.exists():
            path.rename(directory / ('failed-' + path.name))
        saved = directory / 'config' / path.relative_to('/')
        if saved.is_dir():
            shutil.copytree(saved, path, symlinks=True)
        elif saved.exists():
            shutil.copy2(saved, path)
    print(json.dumps({'restored': str(directory)}))


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('--directory')
    args = parser.parse_args()
    if args.action == 'backup':
        backup()
    else:
        restore(args.directory)
