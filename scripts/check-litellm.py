import base64
import json
import subprocess
import urllib.error
import urllib.request


def kubectl(*args):
    return subprocess.check_output(['kubectl', '-n', 'llm', *args], text=True)


secret = json.loads(kubectl('get', 'secret', 'litellm-env', '-o', 'json'))
master = base64.b64decode(secret['data']['LITELLM_MASTER_KEY']).decode()
ip = kubectl('get', 'svc', 'litellm', '-o', 'jsonpath={.spec.clusterIP}')
base = 'http://' + ip + ':4000'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, key=None, data=None):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    req = urllib.request.Request(base + path, headers=headers, data=None if data is None else json.dumps(data).encode())
    with opener.open(req, timeout=180) as response:
        return json.load(response)


try:
    request('/v1/models')
    raise AssertionError('Unauthenticated API request succeeded')
except urllib.error.HTTPError as exc:
    assert exc.code == 401, exc.code
print('unauthenticated API: 401')
result = request('/key/generate', master, {'models': ['qwen3.8-27b'], 'key_alias': 'deployment-verification', 'duration': '10m', 'rpm_limit': 5})
key = result['key']
try:
    models = request('/v1/models', key)
    assert any(m['id'] == 'qwen3.8-27b' for m in models['data'])
    result = request('/v1/chat/completions', key, {'model': 'qwen3.8-27b', 'messages': [{'role': 'user', 'content': 'Reply only with the number: 2+2'}], 'max_tokens': 16})
    print('virtual key inference:', result['choices'][0]['message']['content'])
finally:
    request('/key/delete', master, {'keys': [key]})
print('temporary key revoked')
