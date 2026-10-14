#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import tempfile


CONFIG_DIRECTORIES = ('.config/hypr', '.config/waybar', '.config/alacritty')
SCRIPT_NAMES = ('start-desktop-services.sh', 'layout-listener.sh', 'caffeine-manager.sh',
                'toggle_noscreenshare.sh', 'waybar-gpu.py', 'battery-degradation.sh',
                'pacman_updates.sh', 'paru_updates.sh')
CONFIG_FILES = ('.config/systemd/user/caffeine-lid-inhibit.service', '.tmux.conf',
                '.zprofile', '.zshrc', '.zlogin')


def inside(path, home):
    resolved = path.resolve(strict=True)
    if resolved != home and home not in resolved.parents:
        raise ValueError(f'Configuration target is outside account home: {path}')
    return resolved


def inspect_tree(path, home, ancestors=()):
    resolved = inside(path, home)
    mode = resolved.stat().st_mode
    if stat.S_ISREG(mode):
        return path.is_symlink()
    if not stat.S_ISDIR(mode):
        raise ValueError(f'Unsupported configuration file type: {path}')
    if resolved in ancestors:
        raise ValueError(f'Configuration symlink cycle: {path}')
    linked = path.is_symlink()
    for child in sorted(path.iterdir()):
        linked = inspect_tree(child, home, (*ancestors, resolved)) or linked
    return linked


def check_parents(path, home):
    for parent in path.parents:
        if parent == home:
            return
        if parent.is_symlink():
            raise ValueError(f'Configuration parent is a symlink: {parent}')
    raise ValueError(f'Configuration path is outside account home: {path}')


def isolate(home, check=False):
    home = Path(home).resolve(strict=True)
    paths = list(CONFIG_DIRECTORIES) + list(CONFIG_FILES)
    if (home / 'scripts').is_symlink():
        paths.append('scripts')
    else:
        paths.extend(f'scripts/{name}' for name in SCRIPT_NAMES)
    planned = []
    for relative in paths:
        path = home / relative
        check_parents(path, home)
        if not path.exists() and not path.is_symlink():
            continue
        if inspect_tree(path, home):
            planned.append(relative)
    backup_parent = home / '.local/state/homelab/config-isolation'
    check_parents(backup_parent / 'placeholder', home)
    result = {'changed': bool(planned), 'paths': planned, 'backup': None}
    if not planned or check:
        return result
    backup_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ-')
    backup = Path(tempfile.mkdtemp(prefix=stamp, dir=backup_parent))
    result['backup'] = str(backup)
    metadata = []
    for relative in planned:
        original = home / relative
        metadata.append({'path': relative, 'symlink': os.readlink(original) if original.is_symlink() else None})
    (backup / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    for relative in planned:
        original = home / relative
        archived = backup / 'original' / relative
        staged = backup / 'materialized' / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        archived.parent.mkdir(parents=True, exist_ok=True)
        if original.is_dir():
            shutil.copytree(original, staged, symlinks=False)
        else:
            shutil.copy2(original, staged, follow_symlinks=True)
        original.rename(archived)
        try:
            staged.rename(original)
        except BaseException:
            archived.rename(original)
            raise
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    account = pwd.getpwnam(args.user)
    if account.pw_uid != os.geteuid() or Path(account.pw_dir).resolve() != Path(args.home).resolve():
        raise ValueError('Run as the configured account with its actual home directory')
    print(json.dumps(isolate(args.home, args.check)))


if __name__ == '__main__':
    main()
