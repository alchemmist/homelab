import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.parse
import urllib.request

DATABASES = {'primary': '/srv/x-ui-lab/db/x-ui.db', 'legacy': '/etc/x-ui/x-ui.db'}
TABLES = ('users', 'inbounds', 'settings', 'clients', 'client_inbounds', 'client_traffics', 'api_tokens', 'hosts', 'client_external_links', 'inbound_fallbacks', 'sub_balancers')
RUNTIME_COLUMNS = {
    'users': {'login_epoch'},
    'inbounds': {'up', 'down', 'last_traffic_reset_time'},
    'client_traffics': {'up', 'down', 'last_online', 'last_sub_fetch', 'reset_count'},
    'client_external_links': {'last_fetch_at', 'last_fetch_error'},
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def configuration(connection):
    connection.row_factory = sqlite3.Row
    result = {}
    for table in TABLES:
        rows = []
        for row in connection.execute('SELECT * FROM "' + table + '"'):
            item = {key: row[key] for key in row.keys() if key not in RUNTIME_COLUMNS.get(table, set())}
            rows.append(item)
        result[table] = sorted(rows, key=canonical)
    return result


def normalize_subscription(body):
    text = body.decode('utf-8').strip()
    if '://' not in text:
        text = base64.b64decode(text + '=' * (-len(text) % 4), validate=True).decode('utf-8')
    links = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = urllib.parse.urlsplit(line)
        if not parsed.scheme or '://' not in line:
            raise ValueError('Invalid subscription response')
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if ('security', 'reality') in query:
            query = [(key, value) for key, value in query if key != 'sid']
        links.append(urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(sorted(query)))))
    if not links:
        raise ValueError('Empty subscription response')
    return sorted(links)


def subscriptions(connection):
    settings = dict(connection.execute('SELECT key, value FROM settings'))
    if settings.get('subCertFile') or settings.get('subKeyFile'):
        raise ValueError('Local TLS subscription endpoint is unsupported')
    port = int(settings.get('subPort', '2096'))
    host = settings.get('subListen', '') or ('127.0.0.1' if port == 12096 else '172.18.0.1')
    if host in ('0.0.0.0', '::'):
        host = '127.0.0.1'
    if host not in ('127.0.0.1', '172.18.0.1'):
        raise ValueError('Unexpected local subscription address')
    path = settings.get('subPath', '/sub/')
    identifiers = set()
    for row in connection.execute('SELECT settings FROM inbounds WHERE enable = 1'):
        for client in json.loads(row[0]).get('clients', []):
            if client.get('enable', True) and client.get('subId'):
                identifiers.add(client['subId'])
    for row in connection.execute('SELECT DISTINCT c.sub_id FROM clients c JOIN client_inbounds ci ON ci.client_id = c.id JOIN inbounds i ON i.id = ci.inbound_id WHERE c.enable = 1 AND i.enable = 1'):
        if row[0]:
            identifiers.add(row[0])
    if not identifiers:
        raise ValueError('No enabled subscriptions found')
    result = {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for identifier in sorted(identifiers):
        url = 'http://' + host + ':' + str(port) + '/' + path.strip('/') + '/' + urllib.parse.quote(identifier, safe='')
        try:
            with opener.open(url, timeout=15) as response:
                links = normalize_subscription(response.read(4 * 1024 * 1024))
        except Exception:
            raise ValueError('Subscription request or validation failed') from None
        result[digest(identifier)] = {'fingerprint': digest(links), 'links': len(links)}
    return result


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def inspect(connection):
    if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite integrity check failed')
    config = configuration(connection)
    return {'configuration': {table: digest(rows) for table, rows in config.items()}, 'subscriptions': subscriptions(connection)}


def run(mode, directory):
    if os.geteuid() != 0:
        raise ValueError('Run as root')
    os.umask(0o077)
    directory = Path(directory)
    if mode == 'snapshot':
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != 0 or directory.stat().st_mode & 0o077:
        raise ValueError('Snapshot directory must be root-owned and mode 0700')
    manifest_path = directory / 'manifest.json'
    if mode == 'snapshot' and any(directory.iterdir()):
        raise ValueError('Snapshot directory must be empty')
    current = {}
    for name, path in DATABASES.items():
        with connect(path) as source:
            if mode == 'snapshot':
                backup_path = directory / (name + '.db')
                with sqlite3.connect(backup_path) as backup:
                    source.backup(backup)
                    current[name] = inspect(backup)
                os.chmod(backup_path, 0o600)
            else:
                with sqlite3.connect(':memory:') as snapshot:
                    source.backup(snapshot)
                    current[name] = inspect(snapshot)
    if mode == 'snapshot':
        with manifest_path.open('x') as output:
            json.dump(current, output, sort_keys=True)
        os.chmod(manifest_path, 0o600)
    else:
        expected = json.loads(manifest_path.read_text())
        if expected != current:
            raise ValueError('VPN configuration or subscriptions changed')
    count = sum(len(item['subscriptions']) for item in current.values())
    links = sum(sub['links'] for item in current.values() for sub in item['subscriptions'].values())
    print(f'{mode}: {len(current)} databases, {count} subscriptions, {links} links verified')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('snapshot', 'verify'))
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        run(args.mode, args.directory)
    except Exception as error:
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print('VPN snapshot operation failed: ' + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
