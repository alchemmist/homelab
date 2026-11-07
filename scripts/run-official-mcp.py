#!/usr/bin/env python3
"""Exec pinned upstream stdio binaries; this script implements no MCP tools/protocol."""
import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mcp_credentials', Path(__file__).with_name('mcp-credential.py'))
creds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(creds)
BASE = Path.home()/'.local/share/homelab/mcp'

def command(name):
    env = dict(os.environ)
    if name == 'argocd':
        env.update(ARGOCD_BASE_URL='https://argocd.socrat.alchemmist.xyz',
                   ARGOCD_API_TOKEN=creds.read_private(Path.home()/creds.FILES['argocd']),
                   MCP_READ_ONLY='true')
        args = ['node', str(BASE/'npm/node_modules/argocd-mcp/dist/index.js'), 'stdio']
    elif name == 'metrics':
        # This datasource intentionally points to Thanos, NOT directly to the TSDB.
        # v0.18.0 --prometheus.backend overrides the tool allowlist, even for
        # prometheus; omit it. Core query APIs are Thanos-compatible.
        # Restrict the ancillary web listener too: stdio must not open :8080.
        args = [str(BASE/'prometheus-0.18.0/prometheus-mcp-server'),
                '--mcp.transport=stdio',
                '--web.listen-address=127.0.0.1:0',
                '--prometheus.url=https://grafana.socrat.alchemmist.xyz/api/datasources/proxy/uid/prometheus',
                '--http.config='+str(Path.home()/'.config/homelab/mcp/metrics-http.yaml'),
                '--mcp.tools=build_info',
                '--prometheus.truncation-limit=100', '--prometheus.timeout=30s']
    elif name == 'umami':
        env.update(UMAMI_URL='https://umami.alchemmist.xyz',
                   UMAMI_API_TOKEN=creds.read_private(Path.home()/creds.FILES['umami']))
        args = ['node', str(BASE/'npm/node_modules/@umami/mcp/bin/umami-mcp.js')]
    else:
        raise ValueError('Unknown official MCP server')
    return args, env

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('argocd', 'metrics', 'umami'):
        raise SystemExit('Usage: run-official-mcp.py {argocd|metrics|umami}')
    try:
        args, env = command(sys.argv[1])
        os.execvpe(args[0], args, env)
    except (OSError, ValueError):
        raise SystemExit('Official MCP prerequisite missing/unsafe; run scripts/setup-official-mcp.py (no tokens in logs).') from None

if __name__ == '__main__':
    main()
