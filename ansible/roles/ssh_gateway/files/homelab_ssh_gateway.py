#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys


CONFIG = Path.home() / '.config/homelab/ssh-gateway.json'
STATE = Path.home() / '.local/state/homelab/ssh-mappings.json'


def load_config(path):
    config = json.loads(path.read_text())
    ports = set()
    for node in config['nodes']:
        if not re.fullmatch(r'socrat-\d+', node['name']):
            raise ValueError('Invalid node name')
        ipaddress.IPv4Address(node['address'])
        if not 1024 <= node['external_port'] <= 65535 or node['external_port'] in ports:
            raise ValueError('Invalid or duplicate external port')
        ports.add(node['external_port'])
        if not node['ports'] or any(not 1 <= port <= 65535 for port in node['ports']):
            raise ValueError('Invalid server ports')
    ipaddress.IPv4Address(config['gateway_address'])
    return config


def ssh_port(node):
    for port in node['ports']:
        try:
            with socket.create_connection((node['address'], port), timeout=3) as peer:
                peer.settimeout(3)
                if peer.recv(256).startswith(b'SSH-'):
                    return port
        except OSError:
            continue
    raise RuntimeError(f"No SSH listener on {node['name']} ({node['address']})")


def reconcile(config):
    prefix = ['upnpc', '-u', config['router_description']]
    listing = subprocess.run(prefix + ['-l'], capture_output=True, text=True, timeout=15)
    if listing.returncode or f"ExternalIPAddress = {config['external_address']}" not in listing.stdout:
        raise RuntimeError('Cannot read mappings from the expected gateway: ' + listing.stdout)
    mappings = {
        int(port): (address, int(internal_port), description)
        for port, address, internal_port, description in re.findall(
            r"^\s*\d+\s+TCP\s+(\d+)->([0-9.]+):(\d+)\s+'([^']*)'",
            listing.stdout, re.MULTILINE)
    }
    owned = json.loads(STATE.read_text()) if STATE.exists() else {}
    errors = []
    for node in config['nodes']:
        try:
            port = ssh_port(node)
            address = node['address']
            if node.get('relay', False):
                address = config['gateway_address']
                port = node['external_port']
            description = 'homelab-ssh-' + node['name']
            existing = mappings.get(node['external_port'])
            if existing and existing[:2] == (address, port):
                owned[str(node['external_port'])] = [address, port]
                print(f"{node['name']}: {node['external_port']} -> {address}:{port} (present)", flush=True)
                continue
            if existing:
                if existing[2] != description and owned.get(str(node['external_port'])) != list(existing[:2]):
                    raise RuntimeError('External port is occupied by an unmanaged mapping')
                subprocess.run(prefix + ['-d', str(node['external_port']), 'TCP'],
                               capture_output=True, text=True, timeout=15, check=True)
            command = prefix + ['-e', description, '-a', address, str(port),
                       str(node['external_port']), 'TCP', '0']
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                expected = (f"external {config['external_address']}:{node['external_port']} TCP "
                            f"is redirected to internal {address}:{port}")
                if result.returncode or expected not in result.stdout:
                    raise RuntimeError(result.stdout.strip() + '\n' + result.stderr.strip())
            except (OSError, RuntimeError, subprocess.SubprocessError):
                if existing:
                    try:
                        subprocess.run(prefix + ['-e', existing[2], '-a', existing[0],
                                                 str(existing[1]), str(node['external_port']), 'TCP', '0'],
                                       capture_output=True, text=True, timeout=15)
                    except (OSError, subprocess.SubprocessError) as error:
                        print(f"Rollback failed for {node['name']}: {error}", file=sys.stderr)
                raise
            owned[str(node['external_port'])] = [address, port]
            print(f"{node['name']}: {node['external_port']} -> {address}:{port}", flush=True)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            errors.append(f"{node['name']}: {error}")
    STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(owned, indent=2) + '\n')
    temporary.replace(STATE)
    if errors:
        raise RuntimeError('\n'.join(errors))


def relay(config, name):
    node = next(node for node in config['nodes'] if node['name'] == name and node.get('relay'))
    port = ssh_port(node)
    os.execv('/usr/bin/socat', ['socat', 'STDIO',
                              f"TCP:{node['address']}:{port},connect-timeout=10"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('action', choices=['reconcile', 'relay'])
    parser.add_argument('node', nargs='?')
    args = parser.parse_args()
    config = load_config(args.config)
    if args.action == 'relay':
        if not args.node:
            parser.error('relay requires a node name')
        relay(config, args.node)
    else:
        reconcile(config)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, StopIteration, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
