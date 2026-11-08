#!/usr/bin/env python3
"""Read-only VPN config projection and private online backup. Never emits identities/keys.
This does not authenticate clients, change SQLite, restart Xray or install firewall rules.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

TABLES = ('inbounds', 'clients', 'client_inbounds', 'hosts')
VOLATILE = {'inbounds': {'up', 'down', 'last_traffic_reset_time'}}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def check_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlinks are not allowed')
    return path


def private_directory(path):
    path = check_path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise ValueError('State directory must be caller-owned, mode 0700')
    return path


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(canonical(value) + '\n')
        file.flush()
        os.fsync(file.fileno())


def projection(con):
    con.row_factory = sqlite3.Row
    result = {}
    for table in TABLES:
        result[table] = sorted([
            {k: row[k] for k in row.keys() if k not in VOLATILE.get(table, set())}
            for row in con.execute('SELECT * FROM "' + table + '"')
        ], key=canonical)
    return result


def summarize(config):
    links = config['client_inbounds']
    result = []
    for row in sorted(config['inbounds'], key=lambda x: x['port']):
        stream = json.loads(row['stream_settings'] or '{}')
        reality = stream.get('realitySettings') or {}
        target = reality.get('target', reality.get('dest', ''))
        # Target may be an address or a host:port, never emit arbitrary URLs/userinfo.
        if not isinstance(target, str) or any(x in target for x in ('/', '@', '?', '#', '\n')):
            target = '[non-host target withheld]'
        result.append({'port': row['port'], 'protocol': row['protocol'],
                       'enabled': bool(row['enable']), 'network': stream.get('network'),
                       'security': stream.get('security'), 'target': target,
                       'server_name_count': len(reality.get('serverNames') or []),
                       'client_links': sum(x['inbound_id'] == row['id'] for x in links)})
    encrypted = {row['id'] for row in config['inbounds'] if row['enable'] and
                 json.loads(row['stream_settings'] or '{}').get('security') in ('tls', 'reality')}
    enabled_hosts = {row['inbound_id'] for row in config['hosts'] if not row.get('is_disabled', False)}
    encrypted &= enabled_hosts
    per_client = {}
    for link in links:
        per_client.setdefault(link['client_id'], set()).add(link['inbound_id'])
    for item in result:
        if item['protocol'] == 'vless' and item['security'] in (None, '', 'none'):
            inbound_id = next(row['id'] for row in config['inbounds'] if row['port'] == item['port'])
            clients = [ids for ids in per_client.values() if inbound_id in ids]
            item['links_with_existing_enabled_encrypted_alternative'] = sum(bool(ids & encrypted) for ids in clients)
            item['device_compatibility_and_subscription_render_unproven'] = True
    return {'configuration_sha256': digest(config), 'identities': len(config['clients']),
            'client_links': len(links), 'inbounds': result,
            'records_are_not_active_sessions': True, 'production_configuration_writes': 0}


def inspect(database, state=None):
    database = check_path(database)
    if not database.is_file():
        raise ValueError('Database must be an existing regular file')
    # No immutable=1: include committed WAL state. Copy to one consistent snapshot.
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(':memory:')) as snapshot:
            source.backup(snapshot)
            if snapshot.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite integrity check failed')
            config = projection(snapshot)
            if state is not None:
                directory = private_directory(state)
                if any(directory.iterdir()):
                    raise ValueError('Backup state must be empty; never overwrite evidence')
                path = directory / 'x-ui-before.sqlite3'
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(fd)
                with closing(sqlite3.connect(path)) as backup:
                    snapshot.backup(backup)
                    if backup.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                        raise ValueError('Backup integrity check failed')
                save(directory / 'inventory.json', summarize(config))
    return summarize(config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('/srv/x-ui-lab/db/x-ui.db'))
    parser.add_argument('--backup-state', type=Path, help='Empty private directory; writes backup only, never production DB')
    args = parser.parse_args()
    print(canonical(inspect(args.database, args.backup_state)))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Inventory/backup stopped; inspect private state before retrying') from None
