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

    web_settings = {
        'ENABLE_WEB_SEARCH': True,
        'WEB_SEARCH_ENGINE': 'searxng',
        'SEARXNG_QUERY_URL': 'http://searxng.llm.svc.cluster.local:8080/search?q=<query>&format=json',
    }
    retrieval = request('/api/v1/retrieval/config')
    web_changed = any(retrieval['web'].get(key) != value for key, value in web_settings.items())
    if web_changed:
        request('/api/v1/retrieval/config/update', {'web': {**retrieval['web'], **web_settings}})
    after_retrieval = request('/api/v1/retrieval/config')
    expected_retrieval = copy.deepcopy(retrieval)
    expected_retrieval['web'].update(web_settings)
    if after_retrieval != expected_retrieval:
        raise RuntimeError('Unrelated retrieval settings changed')
    if any(after_retrieval['web'].get(key) != value for key, value in web_settings.items()):
        raise RuntimeError('Web search configuration failed readback validation')
    permissions = request('/api/v1/users/default/permissions')
    desired_permissions = copy.deepcopy(permissions)
    desired_permissions.setdefault('features', {})['web_search'] = True
    permissions_changed = desired_permissions != permissions
    if permissions_changed:
        request('/api/v1/users/default/permissions', desired_permissions)
    if request('/api/v1/users/default/permissions') != desired_permissions:
        raise RuntimeError('User search permissions failed readback validation')
    path = '/api/v1/models/model?id=qwen3.8-27b'
    before = request(path)
    fields = ('id', 'base_model_id', 'name', 'meta', 'params', 'access_grants', 'is_active')
    desired = {key: copy.deepcopy(before[key]) for key in fields if key in before}
    desired['meta'] = desired.get('meta') or {}
    desired['meta']['capabilities'] = {**(desired['meta'].get('capabilities') or {}), 'web_search': True}
    features = desired['meta'].get('defaultFeatureIds') or []
    desired['meta']['defaultFeatureIds'] = list(dict.fromkeys([*features, 'web_search']))
    desired['params'] = {**(desired.get('params') or {}), 'function_calling': 'native'}
    public_read = {'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}
    desired['access_grants'] = desired.get('access_grants') or []
    if not any(all(grant.get(key) == value for key, value in public_read.items())
               for grant in desired['access_grants']):
        desired['access_grants'].append(public_read)
    model_changed = any(desired.get(key) != before.get(key)
                        for key in ('meta', 'params', 'access_grants'))
    if model_changed:
        request('/api/v1/models/model/update', desired)
    after = request(path)
    if after['meta'] != desired['meta'] or after['params'] != desired['params']:
        raise RuntimeError('Qwen search settings failed readback validation')
    for key in ('id', 'user_id', 'base_model_id', 'name', 'is_active'):
        if after.get(key) != before.get(key):
            raise RuntimeError('Unrelated model settings changed')

    def grants(model):
        return sorted((g.get('principal_type'), g.get('principal_id'), g.get('permission'))
                      for g in model.get('access_grants') or [])

    if grants(after) != grants(desired):
        raise RuntimeError('Model access grants changed')

    async def verify_users():
        from open_webui.utils.access_control import has_permission, has_access
        with sqlite3.connect('file:/app/backend/data/webui.db?mode=ro', uri=True) as db:
            users = db.execute("SELECT id FROM user WHERE role IN ('admin', 'user')").fetchall()
        for (user_id,) in users:
            if not await has_permission(user_id, 'features.web_search', desired_permissions):
                raise RuntimeError('A user does not have web search permission')
            if not await has_access(user_id, 'read', after['access_grants']):
                raise RuntimeError('A user does not have Qwen model access')
        return len(users)

    user_count = asyncio.run(verify_users())
    return {'changed': web_changed or permissions_changed or model_changed,
            'engine': 'searxng', 'model': before['id'], 'users_verified': user_count}


if __name__ == '__main__':
    print(json.dumps(configure()))
