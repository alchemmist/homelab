import base64
import json
import subprocess
import urllib.request


def kubectl(*args, data=None):
    return subprocess.run(['kubectl', '-n', 'llm', *args], input=data, capture_output=True, text=True, check=True).stdout


existing = kubectl('get', 'secret', 'open-webui-litellm', '--ignore-not-found', '-o', 'name').strip()
if not existing:
    secret = json.loads(kubectl('get', 'secret', 'litellm-env', '-o', 'json'))
    master = base64.b64decode(secret['data']['LITELLM_MASTER_KEY']).decode()
    ip = kubectl('get', 'svc', 'litellm', '-o', 'jsonpath={.spec.clusterIP}')
    request = urllib.request.Request(
        'http://' + ip + ':4000/key/generate',
        data=json.dumps({'key_alias': 'open-webui', 'models': ['qwen3.8-27b']}).encode(),
        headers={'Authorization': 'Bearer ' + master, 'Content-Type': 'application/json'},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=30) as response:
        key = json.load(response)['key']
    obj = {
        'apiVersion': 'v1', 'kind': 'Secret',
        'metadata': {'name': 'open-webui-litellm', 'namespace': 'llm'},
        'stringData': {'api-key': key},
    }
    kubectl('create', '-f', '-', data=json.dumps(obj))
    print('created')
