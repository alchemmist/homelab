import argparse
import base64
import getpass
import json
import subprocess
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--admin-email', required=True)
args = parser.parse_args()
password = getpass.getpass('Open WebUI password: ')


def kubectl(*argv):
    return subprocess.check_output(['kubectl', '-n', 'llm', *argv], text=True)


ip = kubectl('get', 'svc', 'open-webui', '-o', 'jsonpath={.spec.clusterIP}')
base = 'http://' + ip + ':8080'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, headers=headers, data=None if data is None else json.dumps(data).encode())
    with opener.open(req, timeout=60) as response:
        return json.load(response)


session = request('/api/v1/auths/signin', {'email': args.admin_email, 'password': password})
secret = json.loads(kubectl('get', 'secret', 'open-terminal-api', '-o', 'json'))
key = base64.b64decode(secret['data']['api-key']).decode()
connection = {
    'id': 'socrat-terminal', 'name': 'Socrat Terminal',
    'url': 'http://open-terminal.llm.svc.cluster.local:8000',
    'path': '/openapi.json', 'key': key, 'auth_type': 'bearer',
    'enabled': True, 'server_type': 'terminal',
    'config': {'access_grants': [], 'chat_uploads': 'filesystem'},
}
config = request('/api/v1/configs/terminal_servers', token=session['token'])
existing = next((c for c in config['TERMINAL_SERVER_CONNECTIONS'] if c.get('id') == connection['id']), None)
if existing is not None:
    connection = {**existing, 'url': connection['url'], 'key': key}
    connection['config'] = {**(connection.get('config') or {}), 'chat_uploads': 'filesystem'}
verified = request('/api/v1/configs/terminal_servers/verify', connection, session['token'])
assert verified['status'], 'Terminal verification failed'
config = request('/api/v1/configs/terminal_servers', token=session['token'])
connections = [c for c in config['TERMINAL_SERVER_CONNECTIONS'] if c.get('id') != connection['id']]
connections.append(connection)
request('/api/v1/configs/terminal_servers', {'TERMINAL_SERVER_CONNECTIONS': connections}, session['token'])
visible = request('/api/v1/terminals/', token=session['token'])
assert any(c['id'] == connection['id'] for c in visible)
print('Open Terminal connected; existing access settings and other connections preserved.')
