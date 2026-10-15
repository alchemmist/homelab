import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def update_config(original, public_key, endpoint):
    if re.search(r'^\s*SaveConfig\s*=\s*true\s*$', original, re.M | re.I):
        raise ValueError('SaveConfig must be disabled')
    blocks = re.split(r'(?=^\s*\[Peer\]\s*$)', original, flags=re.M)
    found = 0
    for index, block in enumerate(blocks):
        key = re.search(r'^\s*PublicKey\s*=\s*(\S+)\s*$', block, re.M)
        if not key or key[1] != public_key:
            continue
        found += 1
        entries = list(re.finditer(r'^[ \t]*Endpoint[ \t]*=[^\n]*(?:\n|$)', block, re.M))
        if len(entries) > 1:
            raise ValueError('Duplicate peer endpoint')
        replacement = 'Endpoint = ' + endpoint + '\n' if endpoint else ''
        if entries:
            entry = entries[0]
            block = block[:entry.start()] + replacement + block[entry.end():]
        elif endpoint:
            block = block.rstrip('\n') + '\n' + replacement + '\n'
        blocks[index] = block
    if found != 1:
        raise ValueError('Expected exactly one matching peer')
    return ''.join(blocks)


def main():
    interface, public_key, endpoint = sys.argv[1:]
    if not re.fullmatch(r'[a-zA-Z0-9_=+.-]{1,15}', interface):
        raise ValueError('Invalid interface')
    if endpoint not in ('', '127.0.0.1:51840'):
        raise ValueError('Unexpected transport endpoint')
    config = Path('/etc/wireguard') / (interface + '.conf')
    original = config.read_text()
    updated = update_config(original, public_key, endpoint)
    live = dict(line.split('\t', 1) for line in subprocess.check_output(
        ['wg', 'show', interface, 'endpoints'], text=True).splitlines())
    if public_key not in live:
        raise ValueError('Peer missing from live interface')
    changed = updated != original
    if changed:
        backup = str(config) + '.before-tcp-transport-' + str(time.time_ns())
        shutil.copy2(config, backup)
        os.chmod(backup, 0o600)
        descriptor, temporary = tempfile.mkstemp(dir=config.parent, prefix='.tcp-transport-')
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
    if endpoint and live[public_key] != endpoint:
        subprocess.run(['wg', 'set', interface, 'peer', public_key, 'endpoint', endpoint], check=True)
        changed = True
    print(json.dumps({'changed': changed}))


if __name__ == '__main__':
    main()
