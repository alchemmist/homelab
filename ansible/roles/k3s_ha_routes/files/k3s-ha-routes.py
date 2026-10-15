import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def merge(values, additions):
    return list(dict.fromkeys(values + additions))


def update_config(original, routes):
    blocks = re.split(r'(?=^\s*\[Peer\]\s*$)', original, flags=re.MULTILINE)
    found = set()
    for index, block in enumerate(blocks):
        public_key = re.search(r'^\s*PublicKey\s*=\s*(\S+)\s*$', block, re.MULTILINE)
        if not public_key or public_key[1] not in routes:
            continue
        key = public_key[1]
        if key in found:
            raise ValueError('Duplicate configured peer')
        found.add(key)
        allowed = re.search(r'^(\s*AllowedIPs\s*=\s*)([^\n]*)', block, re.MULTILINE)
        if not allowed:
            raise ValueError('Missing configured AllowedIPs')
        values = [value.strip() for value in allowed[2].split(',') if value.strip()]
        updated = merge(values, routes[key])
        if updated != values:
            blocks[index] = block[:allowed.start(2)] + ', '.join(updated) + block[allowed.end(2):]
    if found != set(routes):
        raise ValueError('Requested peer absent from persistent configuration')
    return ''.join(blocks)


def main():
    interface, source, payload = sys.argv[1:]
    if not re.fullmatch(r'[a-zA-Z0-9_=+.-]{1,15}', interface):
        raise ValueError('Invalid interface')
    ipaddress.IPv4Address(source)
    routes = {}
    for item in json.loads(payload):
        network = ipaddress.IPv4Network(item['network'], strict=True)
        if network.prefixlen != 32:
            raise ValueError('Only host routes are supported')
        routes.setdefault(item['public_key'], []).append(str(network))
    config = Path('/etc/wireguard') / (interface + '.conf')
    original = config.read_text()
    if re.search(r'^\s*SaveConfig\s*=\s*true\s*$', original, re.MULTILINE | re.IGNORECASE):
        raise ValueError('SaveConfig must be disabled')
    updated = update_config(original, routes)
    live = {}
    for line in run('wg', 'show', interface, 'allowed-ips').splitlines():
        key, values = line.split('\t', 1)
        live[key] = [] if values == '(none)' else values.replace(',', ' ').split()
    if not set(routes).issubset(live):
        raise ValueError('Requested peer absent from live interface')
    for key, networks in live.items():
        if any(network in networks for target, values in routes.items() if target != key for network in values):
            raise ValueError('Host route already belongs to another peer')
    changed = updated != original
    if changed:
        backup = str(config) + '.before-k3s-ha-' + str(time.time_ns())
        shutil.copy2(config, backup)
        os.chmod(backup, 0o600)
        descriptor, temporary = tempfile.mkstemp(dir=config.parent, prefix='.k3s-ha-')
        try:
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, config)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    for key, networks in routes.items():
        allowed = merge(live[key], networks)
        if allowed != live[key]:
            run('wg', 'set', interface, 'peer', key, 'allowed-ips', ','.join(allowed))
            changed = True
        for network in networks:
            current = json.loads(run('ip', '-json', 'route', 'show', 'exact', network))
            if not any(route.get('dev') == interface and route.get('prefsrc') == source for route in current):
                run('ip', 'route', 'replace', network, 'dev', interface, 'src', source)
                changed = True
    print(json.dumps({'changed': changed, 'routes': sum(len(value) for value in routes.values())}))


if __name__ == '__main__':
    main()
