#!/usr/bin/env python3
"""Add the authorized socrat-4 peer only; preserve every existing WG peer."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess

KEY = 'rOXEc8nrYHuYG0D5t+LwY9jxv05zsjxt0P2scF+Sf0k='
ADDRESS = '10.250.0.40/32'
ENDPOINT = '91.189.82.238:51830'


def main():
    os.umask(0o077)
    config = Path('/etc/wireguard/wg-socrat.conf')
    old = config.read_bytes()
    target = ipaddress.ip_network(ADDRESS)
    legacy_target = ipaddress.ip_network('10.250.0.8/32')
    prior_path = Path('/var/lib/homelab-recovery/20261109-socrat4-peer/receipt.json')
    legacy_owned = prior_path.exists() and json.loads(prior_path.read_text()).get('new_peer') == KEY
    matches = []
    for block in re.split(r'(?m)^\s*\[Peer\]\s*$', old.decode())[1:]:
        fields = {}
        for line in block.splitlines():
            line = line.split('#', 1)[0].strip()
            if '=' in line:
                k, v = line.split('=', 1)
                fields[k.strip()] = v.strip()
        networks = [ipaddress.ip_network(v.strip()) for v in fields.get('AllowedIPs', '').split(',') if v.strip()]
        if fields.get('PublicKey') == KEY:
            assert networks == [target] or (legacy_owned and networks == [legacy_target]), 'Existing target peer differs'
            matches.append(fields)
        else:
            assert not any(n.version == target.version and n.overlaps(target) for n in networks), 'Address overlap'
    assert len(matches) <= 1
    def active():
        lines = subprocess.check_output(['wg', 'show', 'wg-socrat', 'allowed-ips'], text=True).splitlines()
        return dict(line.split(None, 1) for line in lines)
    # A historical restricted admin-client ACL used .8 even though its WG peer
    # was retired. Do not remove that ACL or grant a server identity to a client.
    acl = Path('/usr/local/libexec/wg-socrat-admin-firewall')
    if acl.exists():
        assert '10.250.0.40' not in acl.read_text(), 'Reserved client ACL address'
    before = active()
    for key, addresses in before.items():
        if key == KEY:
            assert addresses == ADDRESS or (legacy_owned and addresses == str(legacy_target))
        else:
            assert not any(ipaddress.ip_network(n).overlaps(target) for n in addresses.replace(',', ' ').split() if n != '(none)' and ':' not in n)
    if matches and before.get(KEY) == ADDRESS:
        print(json.dumps({'already_present': True, 'existing_peers_preserved': True}))
        return
    state = Path('/var/lib/homelab-recovery/20261109-socrat4-peer-address40')
    state.mkdir(mode=0o700, exist_ok=True)
    assert not (state/'attempt.json').exists(), 'Uncertain prior attempt; inspect, never replay'
    with (state/'wg-socrat-before-private.conf').open('xb') as f:
        f.write(old)
    (state/'attempt.json').write_text(json.dumps({'config_sha256': hashlib.sha256(old).hexdigest(), 'new_peer': KEY, 'address': ADDRESS}))
    changing_address = bool(matches) and before.get(KEY) == str(legacy_target)
    if not matches or changing_address:
        if changing_address:
            needle = ('PublicKey = ' + KEY + '\nAllowedIPs = ' + str(legacy_target)).encode()
            assert old.count(needle) == 1
            new = old.replace(needle, ('PublicKey = ' + KEY + '\nAllowedIPs = ' + ADDRESS).encode())
        else:
            new = old.rstrip() + f'\n\n# homelab socrat-4 transit worker\n[Peer]\nPublicKey = {KEY}\nAllowedIPs = {ADDRESS}\nEndpoint = {ENDPOINT}\nPersistentKeepalive = 25\n'.encode()
        temp = config.with_name('wg-socrat.conf.edge-once')
        with temp.open('xb') as f:
            f.write(new)
            f.flush()
            os.fsync(f.fileno())
        assert config.read_bytes() == old
        os.replace(temp, config)
        fd = os.open(str(config.parent), os.O_RDONLY)
        os.fsync(fd)
        os.close(fd)
    subprocess.run(['wg', 'set', 'wg-socrat', 'peer', KEY, 'allowed-ips', ADDRESS, 'endpoint', ENDPOINT, 'persistent-keepalive', '25'], check=True, timeout=10)
    after = active()
    assert after.get(KEY) == ADDRESS
    assert all(after.get(key) == value for key, value in before.items() if key != KEY)
    receipt = {'new_peer': KEY, 'address': ADDRESS, 'existing_peers_preserved': True, 'no_interface_restart': True}
    (state/'receipt.json').write_text(json.dumps(receipt))
    (state/'attempt.json').rename(state/'original-attempt.json')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
