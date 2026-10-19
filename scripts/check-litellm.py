import base64
import json
import os
import subprocess
import urllib.error
import urllib.request


def kubectl(*args):
    return subprocess.check_output(['kubectl', '-n', 'llm', *args], text=True)


MODEL = os.environ.get('LLM_MODEL', 'qwen3.8-27b')

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
result = request('/key/generate', master, {'models': [MODEL], 'key_alias': 'deployment-verification', 'duration': '10m', 'rpm_limit': 5})
key = result['key']
try:
    models = request('/v1/models', key)
    assert any(m['id'] == MODEL for m in models['data'])
    result = request('/v1/chat/completions', key, {'model': MODEL, 'messages': [{'role': 'user', 'content': 'What is 2 + 2? Reply with the answer only.'}], 'max_tokens': 64, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}})
    content = result['choices'][0]['message']['content']
    assert content.strip() == '4', 'Unexpected arithmetic response'
    print('virtual key inference:', content)
finally:
    request('/key/delete', master, {'keys': [key]})
print('temporary key revoked')
