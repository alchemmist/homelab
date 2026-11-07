#!/usr/bin/env python3
"""Install pinned upstream MCP clients and reuse existing Viewer credentials, without rotation."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shlex
import time
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.18.0'
# Upstream v0.18.0 checksums.txt. No latest/main, no prerelease auto-upgrade.
ARTIFACTS = {
    ('Linux', 'x86_64'): ('linux_amd64', '50030346594a4b8d89294f3a2cb9e253caa0bd75e69fefbd9add289cafd6c27c'),
    ('Linux', 'aarch64'): ('linux_arm64', 'e4027f7a47178a3d69ac0974b5cbef5312a855d43b60a4a2686a3db83ed8461e'),
    ('Linux', 'arm64'): ('linux_arm64', 'e4027f7a47178a3d69ac0974b5cbef5312a855d43b60a4a2686a3db83ed8461e'),
    ('Darwin', 'arm64'): ('darwin_all', 'd69df80c4a1459251d74537a565ee725c717475ae956d5c596b1d41792a8cc2e'),
    ('Darwin', 'x86_64'): ('darwin_all', 'd69df80c4a1459251d74537a565ee725c717475ae956d5c596b1d41792a8cc2e'),
}

def private_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.parent.stat().st_uid != os.getuid():
        raise ValueError('Unsafe credentials directory')
    path.parent.chmod(0o700)
    if path.exists() and (path.is_symlink() or path.stat().st_uid != os.getuid()):
        raise ValueError('Unsafe destination')
    fd, tmp = tempfile.mkstemp(prefix='.mcp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ssh-host', default='socrat-0')
    p.add_argument('--archive', type=Path, help='Previously downloaded release archive; the pinned checksum is still mandatory')
    p.add_argument('--offline', action='store_true', help='Use the existing npm cache; combine with --archive')
    p.add_argument('--configure-project', type=Path, help='Install cached-path settings only into an old checkout where .pi/mcp.json remains ignored/untracked; backup first, never merge/reset tracked work')
    args = p.parse_args()
    target = Path.home()/'.local/share/homelab/mcp'
    for name in ('run-official-mcp.py', 'mcp-credential.py'):
        private_write(target/'bin'/name, (ROOT/'scripts'/name).read_bytes())
    npm = target/'npm'
    npm.mkdir(parents=True, exist_ok=True)
    for name in ('package.json', 'package-lock.json'):
        shutil.copyfile(ROOT/'tools/official-mcp'/name, npm/name)
    subprocess.run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'] + (['--offline'] if args.offline else []), cwd=npm, check=True, stdout=subprocess.DEVNULL, timeout=120)
    art = ARTIFACTS.get((platform.system(), platform.machine()))
    if not art: raise SystemExit('Platform not reviewed; add a verified stable release artifact/checksum first.')
    suffix, digest = art
    url = f'https://github.com/prometheus/prometheus-mcp/releases/download/v{VERSION}/prometheus-mcp-server_{VERSION}_{suffix}.tar.gz'
    if args.offline and not args.archive: raise ValueError('Offline setup requires a checksum-verified --archive')
    data = args.archive.read_bytes() if args.archive else urllib.request.urlopen(url, timeout=90).read()
    if hashlib.sha256(data).hexdigest() != digest: raise ValueError('Upstream archive checksum mismatch')
    # Extract a single regular file, never archive paths/symlinks.
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        member = archive.getmember('prometheus-mcp-server')
        if not member.isfile(): raise ValueError('Expected regular binary')
        binary = archive.extractfile(member).read()
    dest = target/f'prometheus-{VERSION}/prometheus-mcp-server'
    dest.parent.mkdir(parents=True, exist_ok=True)
    private_write(dest, binary)
    dest.chmod(0o755)
    cmd = 'K3S_CONFIG_FILE=/dev/null kubectl -n cattle-monitoring-system get secret grafana-mcp-credentials -o json'
    result = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=6',args.ssh_host,cmd],capture_output=True,check=True,timeout=30)
    secret = json.loads(result.stdout)['data']
    folder = Path.home()/'.config/homelab/mcp'
    for key, name in [('client-token','grafana-client-token'),('grafana-token','grafana-viewer-token')]:
        private_write(folder/name, base64.b64decode(secret[key]))
    # Only a filename is stored in the HTTP config, never an inline credential.
    private_write(folder/'metrics-http.yaml', ('bearer_token_file: '+json.dumps(str(folder/'grafana-viewer-token'))+'\nfollow_redirects: false\n').encode())
    if args.configure_project:
        project = args.configure_project.resolve()
        destination = project/'.pi/mcp.json'
        relative = '.pi/mcp.json'
        tracked = subprocess.run(['git','-C',str(project),'ls-files','--error-unmatch',relative],capture_output=True).returncode == 0
        ignored = subprocess.run(['git','-C',str(project),'check-ignore','-q',relative]).returncode == 0
        if tracked or not ignored:
            raise ValueError('Refuse to overwrite tracked/unignored project config; use its committed settings instead.')
        if destination.is_symlink(): raise ValueError('Refuse symlink project config')
        if destination.exists():
            private_write(folder/'project-backups'/('mcp-'+str(time.time_ns())+'.json'),destination.read_bytes())
        config = json.loads((ROOT/'.pi/mcp.json').read_text())
        for server in config['mcpServers'].values():
            if server.get('command') == 'python3':
                server['args'] = [str(target/'bin'/'run-official-mcp.py') if arg=='scripts/run-official-mcp.py' else arg for arg in server.get('args',[])]
            for key,value in server.get('headers',{}).items():
                server['headers'][key] = value.replace('scripts/mcp-credential.py',shlex.quote(str(target/'bin'/'mcp-credential.py')))
        private_write(destination,(json.dumps(config,indent=2)+'\n').encode())
        print('Ignored project MCP settings updated with cached runtime paths; old private settings backed up. Tracked work untouched.')
    print('Installed pinned official stdio clients; existing Grafana Viewer/client credentials reused, not rotated.')
    print('n8n requires owner to enable Instance-level MCP; Umami requires its own authorized API key. See docs/official-mcp.md.')

if __name__ == '__main__':
    main()
