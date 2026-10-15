import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time


def main():
    with sqlite3.connect('file:/srv/x-ui-lab/db/x-ui.db?mode=ro', uri=True) as database:
        clients = []
        for row in database.execute("SELECT settings FROM inbounds WHERE enable = 1 AND protocol = 'trojan'"):
            clients.extend(json.loads(row[0]).get('clients', []))
    client = next(item for item in clients if item.get('enable', True) and item.get('password') and (not item.get('expiryTime') or item['expiryTime'] > time.time() * 1000))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    configuration = {
        'log': {'loglevel': 'none'},
        'inbounds': [{'listen': '127.0.0.1', 'port': port, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': False}}],
        'outbounds': [{
            'protocol': 'trojan',
            'settings': {'servers': [{'address': 'vpn.alchemmist.xyz', 'port': 443, 'password': client['password']}]},
            'streamSettings': {'network': 'ws', 'security': 'tls', 'tlsSettings': {'serverName': 'vpn.alchemmist.xyz'}, 'wsSettings': {'path': '/connect-4e15326936f20a7a4f2cac67', 'headers': {'Host': 'vpn.alchemmist.xyz'}}},
        }],
    }
    with tempfile.TemporaryDirectory(prefix='homelab-vpn-probe-') as directory:
        path = Path(directory) / 'config.json'
        path.write_text(json.dumps(configuration))
        path.chmod(0o600)
        process = subprocess.Popen(['/opt/homelab-vpn-failover/primary/app/bin/xray-linux-amd64', 'run', '-config', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError('VPN probe client exited before readiness')
                try:
                    with socket.create_connection(('127.0.0.1', port), 0.5):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError('VPN probe client did not become ready')
                    time.sleep(0.1)
            result = subprocess.run(['curl', '--silent', '--show-error', '--noproxy', '', '--socks5-hostname', '127.0.0.1:' + str(port), '--max-time', '25', '--output', '/dev/null', '--write-out', '%{http_code}', 'https://example.com/'], capture_output=True, text=True, timeout=30)
            if result.returncode != 0 or result.stdout != '200':
                raise RuntimeError('Authenticated public Trojan HTTPS probe failed')
            print('Authenticated public Trojan TLS/WebSocket tunnel: HTTPS 200')
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()
