#!/usr/bin/env python3
"""Create the wiki-openapi worker secret, LiteLLM key and inactive n8n workflow.

Nothing secret is printed. Existing secret values are kept.
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync import api, CONFIG

def kubectl(*args, input_text=None):
    result = subprocess.run(['kubectl', *args], input=input_text, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('kubectl failed: ' + ' '.join(args[:3]))
    return result.stdout

def secret(namespace, name):
    result = subprocess.run(['kubectl', '-n', namespace, 'get', 'secret', name, '-o', 'json'],
                            text=True, capture_output=True)
    if result.returncode:
        return None
    data = json.loads(result.stdout).get('data') or {}
    return {key: base64.b64decode(value).decode() for key, value in data.items()}

def apply_secret(namespace, name, data):
    obj = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
           'metadata': {'name': name, 'namespace': namespace}, 'stringData': data}
    kubectl('apply', '-f', '-', input_text=json.dumps(obj))

def ensure_worker():
    current = secret('automation', 'wiki-openapi')
    if current and current.get('WORKER_TOKEN') and current.get('LITELLM_KEY'):
        return current['WORKER_TOKEN']
    import secrets as pysecrets
    remote = r'''
import json, os, urllib.request
body={"key_alias":"socrat-wiki-openapi","models":["qwen3.8-27b"],"rpm_limit":3,"tpm_limit":30000,"max_parallel_requests":1,"metadata":{"purpose":"wiki openapi pull request cleanup"}}
req=urllib.request.Request("http://127.0.0.1:4000/key/generate", data=json.dumps(body).encode(), headers={"Authorization":"Bearer "+os.environ["LITELLM_MASTER_KEY"],"Content-Type":"application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    print(json.load(r)["key"])
'''
    key = subprocess.run(['kubectl', '-n', 'llm', 'exec', 'deploy/litellm', '--', 'python', '-c', remote],
                         text=True, capture_output=True, check=True).stdout.strip()
    if not key.startswith('sk-'):
        raise RuntimeError('LiteLLM key was not created')
    token = pysecrets.token_urlsafe(40)
    apply_secret('automation', 'wiki-openapi', {'WORKER_TOKEN': token, 'LITELLM_KEY': key})
    return token

def ensure_github_slot():
    if secret('automation', 'wiki-openapi-github') is None:
        apply_secret('automation', 'wiki-openapi-github', {'token': 'pending'})

def sync_workflow(worker_token):
    blog = json.loads((CONFIG / 'blog-credentials.json').read_text())
    path = CONFIG / 'wiki-openapi-credentials.json'
    mapping = json.loads(path.read_text()) if path.exists() else {}
    if not mapping.get('httpHeaderAuth', {}).get('id'):
        created = api('POST', 'credentials', {'name': 'wiki-openapi worker', 'type': 'httpHeaderAuth',
                                              'data': {'name': 'X-Worker-Token', 'value': worker_token}})
        mapping['httpHeaderAuth'] = {'id': created['id'], 'name': created['name']}
        os.umask(0o077)
        path.write_text(json.dumps(mapping))
    mapping['githubApi'] = blog['githubApi']
    workflow = json.loads((BASE / 'docs/n8n/wiki-openapi/workflow.json').read_text())
    for node in workflow['nodes']:
        for kind, cred in list(node.get('credentials', {}).items()):
            node['credentials'][kind] = mapping[kind]
    existing = [item for item in api('GET', 'workflows?limit=250')['data'] if item['name'] == workflow['name']]
    if len(existing) > 1:
        raise RuntimeError('Ambiguous workflow name')
    if existing and existing[0].get('active'):
        raise RuntimeError('Deactivate the workflow before syncing')
    body = {key: workflow[key] for key in ('name', 'nodes', 'connections', 'settings')}
    result = api('PUT' if existing else 'POST', 'workflows/' + existing[0]['id'] if existing else 'workflows', body)
    print('Workflow synced inactive:', result['id'])

def main():
    token = ensure_worker()
    ensure_github_slot()
    subprocess.run([sys.executable, str(BASE / 'scripts/wiki_openapi/deploy.py')], check=True)
    sync_workflow(token)
    print('Wiki OpenAPI worker applied. Writes stay disabled until the GitHub App has contents:write.')

if __name__ == '__main__':
    main()
