"""Read-only pre-SSO snapshot; stdout is consumed only by local AES-GCM encryption."""
import os
os.environ.setdefault("K3S_CONFIG_FILE", "/dev/null")
import io
import json
import subprocess
import tarfile

KUBE = ['kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', '-n', 'llm']
def get(*args):
    return subprocess.check_output(KUBE + list(args), timeout=180)

files = {
    'database.dump': get('exec', 'deployment/litellm-postgres', '--', 'sh', '-c',
                         'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc'),
    'deployment.json': get('get', 'deployment', 'litellm', '-o', 'json'),
    'config.json': get('get', 'configmap', 'litellm-config', '-o', 'json'),
    'secrets.json': get('get', 'secret', 'litellm-env', 'litellm-db', '-o', 'json'),
}
oidc = get('get', 'secret', 'socrat-authentik-litellm', '--ignore-not-found', '-o', 'json')
if oidc.strip():
    files['oidc-secret.json'] = oidc
archive = io.BytesIO()
with tarfile.open(fileobj=archive, mode='w:gz') as tar:
    for name, data in files.items():
        info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o600
        tar.addfile(info, io.BytesIO(data))
import sys
sys.stdout.buffer.write(archive.getvalue())
