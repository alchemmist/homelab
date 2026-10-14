#!/usr/bin/env python3
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import ssl
import subprocess
import time

CONFIG_PATH = '/etc/homelab-vpn-failover/config.json'
STATE_DIR = '/var/lib/homelab-vpn-failover'
NATIVE_UNITS = ['homelab-vpn-primary.service', 'homelab-vpn-legacy.service', 'homelab-vpn-caddy.service']


class Watchdog:
    def __init__(self, config):
        self.config = config
        self.state = Path(config.get('state_dir', STATE_DIR))
        self.agent = config.get('agent_unit', 'k3s-agent.service')
        self.units = config.get('native_units', NATIVE_UNITS)
        self.timeout = config.get('timeout_seconds', 4)

    def write(self, name, data):
        target = self.state / name
        temporary = target.with_suffix('.tmp')
        with temporary.open('w') as stream:
            os.chmod(temporary, 0o600)
            stream.write(json.dumps(data))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        descriptor = os.open(self.state, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def command(self, *args):
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=40).stdout.strip()

    def service_active(self, unit):
        return self.command('systemctl', 'show', unit, '--property=ActiveState', '--value') not in ('inactive', 'failed')

    def processes(self):
        result = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                group = (entry / 'cgroup').read_text()
                status = (entry / 'stat').read_text().rsplit(')', 1)[1].split()[0]
            except FileNotFoundError:
                continue
            if status != 'Z' and ('kubepods' in group or '/' + self.agent in group):
                result.append(int(entry.name))
        return result

    def terminate(self, pid, sig):
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            return
        try:
            try:
                group = Path('/proc', str(pid), 'cgroup').read_text()
            except FileNotFoundError:
                return
            if 'kubepods' not in group and '/' + self.agent not in group:
                raise RuntimeError('Process cgroup changed while fencing')
            try:
                signal.pidfd_send_signal(descriptor, sig)
            except ProcessLookupError:
                pass
        finally:
            os.close(descriptor)

    def fence(self):
        self.command('systemctl', 'stop', self.agent)
        if self.service_active(self.agent):
            raise RuntimeError('Kubernetes agent did not stop')
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in self.processes():
                self.terminate(pid, sig)
            deadline = time.monotonic() + self.config.get('fence_timeout_seconds', 10)
            while self.processes() and time.monotonic() < deadline:
                time.sleep(0.2)
            if not self.processes():
                return
        raise RuntimeError('Kubernetes processes remain; refusing native startup')

    def guard(self):
        if not (self.state / 'active').exists() or self.service_active(self.agent) or self.processes():
            raise RuntimeError('Native startup requires verified Kubernetes fencing')

    def occupied(self):
        wanted = {(item['protocol'], int(item['port'])) for item in self.config['listen_ports']}
        found = set()
        for protocol in ('tcp', 'udp'):
            for suffix in ('', '6'):
                for line in Path('/proc/net/' + protocol + suffix).read_text().splitlines()[1:]:
                    fields = line.split()
                    if protocol == 'tcp' and fields[3] != '0A':
                        continue
                    port = int(fields[1].rsplit(':', 1)[1], 16)
                    if (protocol, port) in wanted:
                        found.add((protocol, port))
        return sorted(found)

    def preflight(self):
        for name in self.config.get('preflight_files', []):
            path = Path(name)
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError('Required fallback file missing or empty: ' + name)
        for name in self.config.get('databases', []):
            path = Path(name)
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError('VPN database missing or empty')
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=self.timeout) as database:
                if database.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise RuntimeError('VPN database integrity check failed')

    def health(self):
        errors = []
        for host, port in self.config['tcp_endpoints']:
            try:
                with socket.create_connection((host, port), self.timeout):
                    pass
            except OSError:
                errors.append('TCP listener unavailable: ' + str(port))
        ws = self.config['websocket']
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            context = ssl.create_default_context()
            with socket.create_connection((ws.get('address', '127.0.0.1'), ws.get('port', 443)), self.timeout) as raw:
                with context.wrap_socket(raw, server_hostname=ws['host']) as stream:
                    request = f"GET {ws['path']} HTTP/1.1\r\nHost: {ws['host']}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
                    stream.sendall(request.encode())
                    response = b''
                    deadline = time.monotonic() + self.timeout
                    while b'\r\n\r\n' not in response and len(response) < 16384:
                        stream.settimeout(max(0.01, deadline - time.monotonic()))
                        part = stream.recv(4096)
                        if not part or time.monotonic() >= deadline:
                            break
                        response += part
                    lines = response.split(b'\r\n\r\n', 1)[0].decode('latin1').split('\r\n')
                    headers = dict(line.lower().split(':', 1) for line in lines[1:] if ':' in line)
                    expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                    if len(lines[0].split()) < 2 or lines[0].split()[1] != '101':
                        raise ValueError('WebSocket upgrade rejected')
                    accept = next((line.split(':', 1)[1].strip() for line in lines[1:] if line.lower().startswith('sec-websocket-accept:')), '')
                    if accept != expected or headers.get('upgrade', '').strip() != 'websocket':
                        raise ValueError('WebSocket handshake invalid')
        except (OSError, ValueError):
            errors.append('Public VPN TLS/WebSocket handshake failed')
        return {'healthy': not errors, 'errors': errors}

    def clock(self):
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip(), float(Path('/proc/uptime').read_text().split()[0])

    def counters(self, boot):
        try:
            saved = json.loads((self.state / 'failures.json').read_text())
        except (FileNotFoundError, ValueError):
            saved = {}
        return saved if saved.get('boot_id') == boot else {'boot_id': boot, 'failures': 0, 'grace_until': self.config.get('boot_grace_seconds', 180)}

    def activate(self):
        self.preflight()
        if not (self.state / 'active').exists():
            self.write('active', {'activated_at': time.time()})
        self.fence()
        running = [unit for unit in self.units if self.service_active(unit)]
        if not running and self.occupied():
            raise RuntimeError('VPN ports still occupied; refusing native startup')
        self.guard()
        for unit in self.units:
            if not self.service_active(unit):
                assigned = {(item['protocol'], int(item['port'])) for item in self.config.get('native_unit_ports', {}).get(unit, [])}
                if assigned.intersection(self.occupied()):
                    raise RuntimeError('Native service ports occupied: ' + unit)
                self.command('systemctl', 'start', unit)
        health = self.health()
        boot, _ = self.clock()
        try:
            saved = json.loads((self.state / 'fallback_failures.json').read_text())
        except (FileNotFoundError, ValueError):
            saved = {}
        failures = saved.get('failures', 0) if saved.get('boot_id') == boot else 0
        failures = 0 if health['healthy'] else failures + 1
        if failures >= self.config.get('failure_threshold', 4):
            self.write('fallback_failures.json', {'boot_id': boot, 'failures': 0})
            for unit in reversed(self.units):
                self.command('systemctl', 'stop', unit)
            if any(self.service_active(unit) for unit in self.units) or self.occupied():
                raise RuntimeError('Native VPN did not release ports for recovery restart')
            self.guard()
            for unit in self.units:
                self.command('systemctl', 'start', unit)
            return {'mode': 'fallback', 'restarted': True, **self.health()}
        self.write('fallback_failures.json', {'boot_id': boot, 'failures': failures})
        return {'mode': 'fallback', 'failures': failures, **health}

    def tick(self):
        if (self.state / 'inhibit').exists():
            return {'mode': 'inhibited'}
        if (self.state / 'active').exists():
            return self.activate()
        boot, uptime = self.clock()
        saved = self.counters(boot)
        if uptime < saved['grace_until']:
            return {'mode': 'grace'}
        health = self.health()
        saved['failures'] = 0 if health['healthy'] else saved['failures'] + 1
        self.write('failures.json', saved)
        if saved['failures'] >= self.config.get('failure_threshold', 4):
            return self.activate()
        return {'mode': 'kubernetes', 'failures': saved['failures'], **health}

    def failback(self):
        if not (self.state / 'active').exists():
            raise RuntimeError('Fallback is not active')
        self.fence()
        for unit in reversed(self.units):
            self.command('systemctl', 'stop', unit)
        if any(self.service_active(unit) for unit in self.units) or self.occupied():
            raise RuntimeError('Native VPN has not released its ports; keeping Kubernetes fenced')
        boot, uptime = self.clock()
        self.write('failures.json', {'boot_id': boot, 'failures': 0, 'grace_until': uptime + self.config.get('boot_grace_seconds', 180)})
        (self.state / 'active').unlink()
        descriptor = os.open(self.state, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            self.command('systemctl', 'start', self.agent)
        except Exception:
            self.write('active', {'activated_at': time.time(), 'reason': 'failback failed'})
            self.fence()
            raise
        return {'mode': 'kubernetes', 'grace': True}

    def status(self):
        return {'mode': 'fallback' if (self.state / 'active').exists() else 'kubernetes', 'inhibited': (self.state / 'inhibit').exists(), **self.health()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['tick', 'check', 'status', 'guard', 'failback'])
    parser.add_argument('--config', default=CONFIG_PATH)
    args = parser.parse_args()
    try:
        watchdog = Watchdog(json.loads(Path(args.config).read_text()))
        if args.action in ('tick', 'failback'):
            watchdog.state.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (watchdog.state / 'lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = getattr(watchdog, args.action)()
        else:
            result = getattr(watchdog, 'health' if args.action == 'check' else args.action)()
        print(json.dumps(result or {'guard': True}))
        return 1 if result and result.get('healthy') is False else 0
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
