import argparse
import json
from pathlib import Path
import subprocess
import time

NAMESPACE = 'homelab-tim-check'
INTERFACE = 'wg-tim-check'
ADDRESSES = ['10.250.0.1', '10.250.0.3', '10.250.0.2', '10.250.0.5']


def run(*args, input=None, timeout=30):
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        detail = '' if args[0] in ('wg', 'wg-quick') else ': ' + result.stderr.strip()
        raise RuntimeError(f'{args[0]} failed with status {result.returncode}' + detail)
    return result.stdout


def net(*args, timeout=30):
    return run('ip', 'netns', 'exec', NAMESPACE, *args, timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('profile')
    parser.add_argument('hostkeys')
    options = parser.parse_args()
    expected_keys = json.loads(Path(options.hostkeys).read_text())
    resolver_dir = Path('/etc/netns') / NAMESPACE
    if NAMESPACE in run('ip', 'netns', 'list') or Path('/sys/class/net/' + INTERFACE).exists() or resolver_dir.exists():
        raise RuntimeError('Verification namespace or interface already exists')
    configuration = run('wg-quick', 'strip', options.profile)
    configuration = configuration.replace('Endpoint = socrat.alchemmist.xyz:51830', 'Endpoint = 127.0.0.1:51830')
    configuration = configuration.replace('Endpoint = socrat.alchemmist.xyz:51831', 'Endpoint = 192.168.0.24:51830')
    created_resolver = False
    created_namespace = False
    created_interface = False
    moved = False
    try:
        resolver_dir.mkdir(parents=True, mode=0o700)
        created_resolver = True
        (resolver_dir / 'resolv.conf').write_text('nameserver 10.250.0.2\nnameserver 10.250.0.1\nnameserver 10.250.0.3\n')
        run('ip', 'netns', 'add', NAMESPACE)
        created_namespace = True
        run('ip', 'link', 'add', INTERFACE, 'type', 'wireguard')
        created_interface = True
        run('wg', 'setconf', INTERFACE, '/dev/stdin', input=configuration)
        run('ip', 'link', 'set', INTERFACE, 'netns', NAMESPACE)
        moved = True
        run('ip', '-n', NAMESPACE, 'address', 'add', '10.250.0.7/32', 'dev', INTERFACE)
        run('ip', '-n', NAMESPACE, 'link', 'set', INTERFACE, 'up')
        run('ip', '-n', NAMESPACE, 'link', 'set', 'lo', 'up')
        for address in ADDRESSES:
            run('ip', '-n', NAMESPACE, 'route', 'add', address + '/32', 'dev', INTERFACE)
        time.sleep(3)
        for address in ADDRESSES:
            code = 'import socket; s=socket.create_connection(("' + address + '",2222),8); print(s.recv(128).decode().strip()); s.close()'
            banner = net('python3', '-c', code)
            if not banner.startswith('SSH-2.0-'):
                raise RuntimeError('Unexpected SSH banner from ' + address)
            scanned = net('ssh-keyscan', '-T', '5', '-p', '2222', '-t', 'ed25519', address)
            keys = [' '.join(line.split()[1:3]) for line in scanned.splitlines() if line and not line.startswith('#')]
            if keys != [expected_keys[address]]:
                raise RuntimeError('Wrong SSH server identity at ' + address)
            print(address, 'correct SSH host accessible over client tunnel', flush=True)
        for resolver in ADDRESSES[:3]:
            for name, expected in [('0.socrat.alchemmist.xyz', '10.250.0.1'), ('1.socrat.alchemmist.xyz', '10.250.0.3'), ('2.socrat.alchemmist.xyz', '10.250.0.2'), ('3.socrat.alchemmist.xyz', '10.250.0.5')]:
                answer = net('dig', '@' + resolver, name, 'A', '+short', '+time=3', '+tries=1').strip()
                if answer != expected:
                    raise RuntimeError('Incorrect private DNS answer for ' + name)
            for transport in ([], ['+tcp']):
                answer = net('dig', '@' + resolver, 'debian.org', 'A', '+short', '+time=3', '+tries=1', *transport).strip()
                if not answer or answer.startswith(';'):
                    raise RuntimeError('Public DNS failed on ' + resolver)
            print(resolver, 'private DNS and public UDP/TCP DNS passed', flush=True)
        code = 'import socket; s=socket.socket(); s.settimeout(3); result=s.connect_ex(("10.250.0.5",22)); s.close(); print(result); raise SystemExit(result == 0)'
        run('python3', '-c', 'import socket; s=socket.create_connection(("10.250.0.5",22),5); s.close()')
        net('python3', '-c', code)
        print('Unrequested forwarded recovery SSH port remains blocked', flush=True)
    finally:
        if moved:
            run('ip', '-n', NAMESPACE, 'link', 'delete', INTERFACE)
        elif created_interface:
            run('ip', 'link', 'delete', INTERFACE)
        if created_namespace:
            run('ip', 'netns', 'delete', NAMESPACE)
        if created_resolver:
            (resolver_dir / 'resolv.conf').unlink(missing_ok=True)
            resolver_dir.rmdir()


if __name__ == '__main__':
    main()
