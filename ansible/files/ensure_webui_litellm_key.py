import argparse
import base64
import hashlib
import json
import subprocess
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--model', action='append')
args = parser.parse_args()
desired_models = args.model or ['qwen3.8-27b']


def kubectl(*argv, data=None):
    return subprocess.run(['kubectl', '-n', 'llm', *argv], input=data, capture_output=True, text=True, check=True).stdout


secret = json.loads(kubectl('get', 'secret', 'litellm-env', '-o', 'json'))
master = base64.b64decode(secret['data']['LITELLM_MASTER_KEY']).decode()
ip = kubectl('get', 'svc', 'litellm', '-o', 'jsonpath={.spec.clusterIP}')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(path, data=None):
    req = urllib.request.Request(
        'http://' + ip + ':4000' + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization': 'Bearer ' + master, 'Content-Type': 'application/json'},
    )
    with opener.open(req, timeout=30) as response:
        return json.load(response)


existing = kubectl('get', 'secret', 'open-webui-litellm', '--ignore-not-found', '-o', 'name').strip()
if existing:
    client = json.loads(kubectl('get', 'secret', 'open-webui-litellm', '-o', 'json'))
    key = base64.b64decode(client['data']['api-key']).decode()
    info = request('/key/info?key=' + hashlib.sha256(key.encode()).hexdigest())['info']
    models = info.get('models') or []
    if models and '*' not in models and not set(desired_models) <= set(models):
        request('/key/update', {'key': key, 'models': list(dict.fromkeys([*models, *desired_models]))})
        print('updated')
else:
    key = request('/key/generate', {'key_alias': 'open-webui', 'models': desired_models})['key']
    obj = {
        'apiVersion': 'v1', 'kind': 'Secret',
        'metadata': {'name': 'open-webui-litellm', 'namespace': 'llm'},
        'stringData': {'api-key': key},
    }
    kubectl('create', '-f', '-', data=json.dumps(obj))
    print('created')
