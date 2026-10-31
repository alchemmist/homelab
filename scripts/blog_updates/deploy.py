#!/usr/bin/env python3
"""Apply reproducible source ConfigMaps and workload; Secrets must preexist."""
import json
from pathlib import Path
import subprocess
base = Path(__file__).resolve().parents[2]
for name, directory, pattern in [('blog-updates-code', base/'scripts/blog_updates', '*.py'),
                                  ('blog-updates-prompt', base/'docs/n8n/blog-updates', 'prompt.md')]:
    obj = {'apiVersion': 'v1', 'kind': 'ConfigMap',
           'metadata': {'name': name, 'namespace': 'automation'},
           'data': {p.name: p.read_text() for p in directory.glob(pattern)}}
    subprocess.run(['ssh', 'socrat-0', 'kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml apply -f -'],
                   input=json.dumps(obj), text=True, check=True)
subprocess.run(['ssh', 'socrat-0', 'kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml apply -f -'],
               input=(base/'deploy/blog-updates/worker.yaml').read_text(), text=True, check=True)
