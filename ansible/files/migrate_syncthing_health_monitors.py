import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def migrate(database, plan, check=False):
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    updates = []
    for item in plan:
        row = connection.execute(
            'SELECT id,url,method,accepted_statuscodes_json,description FROM monitor WHERE name=?',
            (item['name'],),
        ).fetchone()
        if row is None:
            continue
        desired = (
            item['url'],
            'GET',
            json.dumps(['200']),
            'Private node-local Syncthing health check',
        )
        if row[1:] != desired:
            updates.append((*desired, row[0]))
    connection.close()
    if check or not updates:
        return {'changed': bool(updates), 'updated': len(updates)}
    backup_dir = database.parent / 'backups'
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup_path = backup_dir / f'kuma-before-syncthing-private-ui-{stamp}.db'
    descriptor = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    connection = sqlite3.connect(database)
    backup = sqlite3.connect(backup_path)
    connection.backup(backup)
    backup.close()
    with connection:
        connection.executemany(
            'UPDATE monitor SET url=?,method=?,accepted_statuscodes_json=?,description=? WHERE id=?',
            updates,
        )
    connection.close()
    return {'changed': True, 'updated': len(updates), 'backup': str(backup_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    arguments = parser.parse_args()
    plan = json.loads(arguments.plan.read_text())
    print(json.dumps(migrate(arguments.database, plan, arguments.check)))


if __name__ == '__main__':
    main()
