import json
import secrets
import subprocess

result = subprocess.run(['kubectl', '-n', 'llm', 'get', 'secret', 'open-terminal-api', '--ignore-not-found', '-o', 'name'], capture_output=True, text=True, check=True)
if not result.stdout.strip():
    obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'open-terminal-api', 'namespace': 'llm'}, 'stringData': {'api-key': secrets.token_urlsafe(48)}}
    subprocess.run(['kubectl', 'create', '-f', '-'], input=json.dumps(obj), text=True, check=True)
    print('created')
