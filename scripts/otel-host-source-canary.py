import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(directory):
    if os.geteuid() != 0 or directory.is_symlink() or not str(directory).startswith('/var/tmp/otel-host-source-canary-'):
        raise ValueError('Private root-owned native canary workspace required')
    stat = directory.lstat()
    if stat.st_uid != 0 or stat.st_mode & 0o022:
        raise ValueError('Canary workspace is not owned exclusively by root')
    request = json.loads((directory / 'request.json').read_text())
    hostname = socket.gethostname()
    legacy_ip = request['legacyIPs'][hostname]
    exporter, probe = directory / 'node_exporter', directory / 'host-source-probe'
    for path, expected in ((exporter, request['exporterSHA256']), (probe, request['probeSHA256'])):
        stat = path.lstat()
        if path.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022 or digest(path) != expected:
            raise ValueError('Untrusted native canary executable')
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', 19100))
    unit = directory.name + '.service'
    result_path = directory / 'source-comparison.json'
    if result_path.exists():
        raise ValueError('Existing comparison output must not be reused')
    properties = ['MemoryMax=67108864', 'CPUQuota=50%', 'RuntimeMaxSec=180',
                  'User=65534', 'Group=65534', 'NoNewPrivileges=yes',
                  'BindReadOnlyPaths=/var/lib/node_exporter/textfile_collector:/host/root/var/lib/node_exporter/textfile_collector']
    arguments = ['systemd-run', '--no-block', '--collect', '--unit=' + unit]
    arguments += ['--property=' + prop for prop in properties]
    arguments += ['--setenv=DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/dbus/system_bus_socket', '--setenv=TZ=UTC',
                  str(exporter), '--web.listen-address=127.0.0.1:19100', '--path.procfs=/proc', '--path.sysfs=/sys',
                  '--path.rootfs=/', '--path.udev.data=/run/udev/data',
                  '--collector.textfile.directory=/host/root/var/lib/node_exporter/textfile_collector',
                  '--collector.systemd', '--collector.systemd.enable-restarts-metrics']
    launched = False
    result = {'hostname': hostname, 'productionIngestionChanged': False}
    try:
        subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=30)
        launched = True
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen('http://127.0.0.1:19100/', timeout=2) as response:
                    if response.status != 200:
                        raise ValueError('Native exporter is not healthy')
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        fields = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID', '-p', 'ControlGroup'], text=True, timeout=15)
        values = dict(line.split('=', 1) for line in fields.splitlines() if '=' in line)
        if int(values.get('MainPID', '0')) <= 0 or not values.get('ControlGroup', '').startswith('/system.slice/otel-host-source-canary-'):
            raise ValueError('Source process is not independent of Kubernetes/containerd')
        completed = subprocess.run([str(probe), '--legacy-url', f'http://{legacy_ip}:9100/metrics',
                                    '--candidate-url', 'http://127.0.0.1:19100/metrics', '--output', str(result_path)],
                                   env={**os.environ, 'GOMAXPROCS': '1', 'GOMEMLIMIT': '128MiB'},
                                   capture_output=True, text=True, timeout=30)
        if result_path.exists():
            result.update(json.loads(result_path.read_text()))
        result['probeReturnCode'] = completed.returncode
        result['exporterBinarySHA256'] = request['exporterSHA256']
        result['probeBinarySHA256'] = request['probeSHA256']
        result['nativeSourceOutsideKubernetesCgroup'] = True
        result['legacyTextfilePathLabelsPreservedByReadOnlyBind'] = True
        result['loopbackOnly'] = True
        result['nodeExporterMaxMemoryBytes'] = 67108864
    finally:
        if launched:
            subprocess.run(['systemctl', 'stop', unit], check=True, capture_output=True, text=True, timeout=30)
            fields = subprocess.check_output(['systemctl', 'show', unit, '-p', 'MainPID'], text=True, timeout=15)
            result['candidateStopped'] = fields.strip() == 'MainPID=0'
        (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    if (result.get('probeReturnCode') != 0 or not result.get('sourceCompatibilityPassed')
            or not result.get('candidateStopped')):
        raise RuntimeError('Native host source canary did not pass; retain private hash-only result')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(run(args.directory)))


if __name__ == '__main__':
    main()
