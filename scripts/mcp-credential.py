#!/usr/bin/env python3
"""Credential command for the MCP client's private pipe. Never run to display tokens."""
import argparse
import os
from pathlib import Path
import stat

FILES = {
    'grafana': '.config/homelab/mcp/grafana-client-token',
    'argocd': '.pi/agent/argocd-mcp-token',
    'n8n': '.config/n8n/mcp-token',
    'umami': '.config/homelab/mcp/umami-api-key',
    'grafana-viewer': '.config/homelab/mcp/grafana-viewer-token',
}

def read_private(path):
    # O_NOFOLLOW + fstat avoids a symlink/permission race for the secret file.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError('Credential must be a current-user-owned regular file with mode 0600')
        value = stream.read(16385).strip()
    if not value or len(value) > 16384 or '\n' in value or '\r' in value:
        raise ValueError('Invalid credential file format')
    return value

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('name', choices=FILES)
    p.add_argument('--raw', action='store_true')
    args = p.parse_args()
    try:
        value = read_private(Path.home()/FILES[args.name])
    except (OSError, ValueError):
        p.exit(1, 'MCP credential unavailable or unsafe; follow docs/official-mcp.md.\n')
    print(value if args.raw else 'Bearer '+value)

if __name__ == '__main__':
    main()
