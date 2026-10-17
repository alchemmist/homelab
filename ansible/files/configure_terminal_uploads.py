import argparse
import asyncio
import copy
import json
import sqlite3
import urllib.request
from datetime import timedelta


def configure(terminal_id):
    from open_webui.utils.auth import create_token
    from open_webui.utils.mfa import get_auth, get_mfa_config, is_mfa_required

    with sqlite3.connect('file:/app/backend/data/webui.db?mode=ro', uri=True) as db:
        admins = db.execute("SELECT id FROM user WHERE role = 'admin'").fetchall()
    if len(admins) != 1:
        raise RuntimeError('Expected one administrator for local configuration')
    admin_id = admins[0][0]
    auth = asyncio.run(get_auth(admin_id))
    mfa_config = asyncio.run(get_mfa_config())
    if (auth.mfa and auth.mfa.secret) or is_mfa_required('password', mfa_config):
        raise RuntimeError('An authenticated administrator session is required with MFA')
    token = create_token({
        'id': admin_id, 'typ': 'session', 'auth_method': 'password',
        'session_stamp': auth.session_stamp, 'mfa_verified': False,
    }, timedelta(minutes=5))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None):
        req = urllib.request.Request(
            'http://127.0.0.1:8080' + path,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
            data=None if payload is None else json.dumps(payload).encode(),
        )
        with opener.open(req, timeout=60) as response:
            return json.load(response)

    path = '/api/v1/configs/terminal_servers'
    before = request(path)
    desired = copy.deepcopy(before)
    matches = [c for c in desired['TERMINAL_SERVER_CONNECTIONS'] if c.get('id') == terminal_id]
    if len(matches) != 1 or not matches[0].get('enabled', True):
        raise RuntimeError('Expected one enabled terminal connection')
    connection = matches[0]
    connection['config'] = {**(connection.get('config') or {}), 'chat_uploads': 'filesystem'}
    changed = desired != before
    if changed:
        request(path, desired)
    after = request(path)
    for expected in desired['TERMINAL_SERVER_CONNECTIONS']:
        actual = next(c for c in after['TERMINAL_SERVER_CONNECTIONS'] if c.get('id') == expected.get('id'))
        if any(actual.get(key) != value for key, value in expected.items()):
            raise RuntimeError('Terminal settings failed readback validation')
    visible = request('/api/v1/terminals/')
    if not any(c['id'] == terminal_id and c['config']['chat_uploads'] == 'filesystem' for c in visible):
        raise RuntimeError('Filesystem upload mode is not visible to clients')
    return {'changed': changed, 'terminal': terminal_id, 'chat_uploads': 'filesystem'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--terminal-id', default='socrat-terminal')
    print(json.dumps(configure(parser.parse_args().terminal_id)))
