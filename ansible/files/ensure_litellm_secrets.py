import base64
import json
import secrets
import subprocess

for name, values in {
    'litellm-db': {'username': 'litellm', 'password': secrets.token_hex(32)},
    'litellm-env': {'LITELLM_MASTER_KEY': 'sk-' + secrets.token_hex(32), 'LITELLM_SALT_KEY': 'sk-' + secrets.token_hex(32)},
}.items():
    result = subprocess.run(['kubectl', '-n', 'llm', 'get', 'secret', name, '--ignore-not-found', '-o', 'name'], check=True, capture_output=True, text=True)
    if not result.stdout.strip():
        obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': 'llm'}, 'type': 'Opaque', 'data': {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}}
        subprocess.run(['kubectl', 'create', '-f', '-'], input=json.dumps(obj), text=True, check=True)
