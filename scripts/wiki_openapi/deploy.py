#!/usr/bin/env python3
"""Apply source ConfigMaps and the worker. Secrets must already exist."""
import json
from pathlib import Path
import subprocess
base = Path(__file__).resolve().parents[2]
maps = [
    ('wiki-openapi-code', 'automation', base / 'scripts/wiki_openapi', '*.py'),
    ('wiki-openapi-broker-code', 'pr-agent', base / 'scripts/wiki_openapi', 'github_broker.py'),
]
for name, namespace, directory, pattern in maps:
    obj = {'apiVersion': 'v1', 'kind': 'ConfigMap',
           'metadata': {'name': name, 'namespace': namespace},
           'data': {p.name: p.read_text() for p in sorted(directory.glob(pattern))}}
    subprocess.run(['kubectl', 'apply', '-f', '-'], input=json.dumps(obj), text=True, check=True)
subprocess.run(['kubectl', 'apply', '-f', str(base / 'deploy/wiki-openapi/worker.yaml')], check=True)
