"""Generate stable private Helm values and an admin Secret; never print credentials."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

root = Path(sys.argv[1])
path = root / 'private-values.json'
if not path.exists():
    values = {'harborAdminPassword': secrets.token_urlsafe(32),
              'secretKey': secrets.token_hex(8),
              'database': {'internal': {'password': secrets.token_urlsafe(32)}}}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(values, f)
values = json.loads(path.read_text())
secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {
    'name': 'harbor-bootstrap', 'namespace': 'harbor'}, 'type': 'Opaque',
    'stringData': {'HARBOR_ADMIN_PASSWORD': values['harborAdminPassword'],
                   'secretKey': values['secretKey']}}
subprocess.run(['kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml',
                'apply', '-f', '-'], input=json.dumps(secret), text=True,
               check=True, stdout=subprocess.DEVNULL)
