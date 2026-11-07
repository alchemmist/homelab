"""Render app-owned public access, without an aggregate chart/Application."""
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHARTS = {
    'grafana': 'deploy/platform/grafana/public-entry',
    'searxng': 'charts/searxng',
    'open-webui': 'charts/open-webui',
    'litellm': 'deploy/platform/litellm/public-entry',
    'rancher': 'deploy/platform/rancher/public-entry',
    'grafana-mcp': 'charts/grafana-mcp',
    'syncthing': 'charts/syncthing',
    'uptime-kuma': 'charts/uptime-kuma',
}

def values(owner):
    value = yaml.safe_load((ROOT / CHARTS[owner] / 'values.yaml').read_text())
    return value if CHARTS[owner].startswith('deploy/') else value['publicEntry']

def render(owner=None):
    docs = []
    for name in ([owner] if owner else CHARTS):
        output = subprocess.check_output(['helm', 'template', name, str(ROOT / CHARTS[name])], text=True)
        docs.extend(d for d in yaml.safe_load_all(output) if d and (d['metadata']['name'].startswith('public-web-') or d['metadata']['name'].endswith('-browser')))
    return docs
