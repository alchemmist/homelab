import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import urllib.request


def get_secret(name):
    result = subprocess.run(['kubectl', '-n', 'wiki', 'get', 'secret', name, '--ignore-not-found', '-o', 'json'], text=True, capture_output=True, check=True)
    return json.loads(result.stdout).get('data', {}) if result.stdout.strip() else {}


def apply(kind, namespace, name, data):
    payload = {'apiVersion': 'v1', 'kind': kind, 'metadata': {'name': name, 'namespace': namespace}, 'data' if kind == 'ConfigMap' else 'stringData': data}
    result = subprocess.run(['kubectl', 'apply', '-f', '-'], input=json.dumps(payload), text=True, capture_output=True, check=True)
    print(result.stdout.strip())


existing = get_secret('wiki-editor-git')
with tempfile.TemporaryDirectory(prefix='wiki-editor-key-') as folder:
    key = Path(folder) / 'id_ed25519'
    if 'id_ed25519' in existing:
        key.write_bytes(base64.b64decode(existing['id_ed25519']))
        key.chmod(0o600)
    else:
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'socrat-wiki-editor', '-f', str(key)], check=True)
        apply('Secret', 'wiki', 'wiki-editor-git', {'id_ed25519': key.read_text()})
    public = subprocess.check_output(['ssh-keygen', '-y', '-f', str(key)], text=True).strip()
    print('Repository deploy public key:', public)
existing = get_secret('wiki-editor-auth')
token = base64.b64decode(existing['gateway-token']).decode() if 'gateway-token' in existing else secrets.token_urlsafe(48)
apply('Secret', 'wiki', 'wiki-editor-auth', {'gateway-token': token})
apply('Secret', 'syncthing', 'wiki-editor-gateway', {'headers.conf': 'proxy_set_header X-Socrat-Editor-Key ' + token + ';\n'})
with urllib.request.urlopen('https://api.github.com/meta', timeout=30) as response:
    keys = json.load(response)['ssh_keys']
apply('ConfigMap', 'wiki', 'wiki-editor-hosts', {'known_hosts': ''.join('github.com ' + key + '\n' for key in keys)})
