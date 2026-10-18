import asyncio
import copy
import json
import sqlite3
import urllib.request
from datetime import timedelta


def configure():
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

    if not any(model.get('id') == 'qwen3.8-27b' for model in request('/api/v1/models/all')):
        return {'changed': False, 'skipped': True, 'reason': 'Qwen workspace model is not configured'}
    path = '/api/v1/models/model?id=qwen3.8-27b'
    before = request(path)
    fields = ('id', 'base_model_id', 'name', 'meta', 'params', 'access_grants', 'is_active')
    desired = {key: copy.deepcopy(before[key]) for key in fields if key in before}
    sampling = {'temperature': 0.7, 'top_p': 0.8, 'top_k': 20, 'min_p': 0.0,
                'presence_penalty': 1.5, 'repetition_penalty': 1.0}
    desired['params'] = {**(desired.get('params') or {}), **sampling}
    if isinstance(desired['params'].get('custom_params'), dict):
        for key in sampling:
            desired['params']['custom_params'].pop(key, None)
    changed = desired['params'] != before.get('params')
    if changed:
        request('/api/v1/models/model/update', desired)
    after = request(path)
    if after['params'] != desired['params']:
        raise RuntimeError('Qwen sampling settings failed readback validation')
    for key in ('id', 'user_id', 'base_model_id', 'name', 'meta', 'is_active'):
        if after.get(key) != before.get(key):
            raise RuntimeError('Unrelated model settings changed')
    def grants(model):
        return sorted((g.get('principal_type'), g.get('principal_id'), g.get('permission'))
                      for g in model.get('access_grants') or [])
    if grants(after) != grants(before):
        raise RuntimeError('Model access grants changed')
    return {'changed': changed, 'model': before['id'], 'sampling': sampling}


if __name__ == '__main__':
    print(json.dumps(configure()))
