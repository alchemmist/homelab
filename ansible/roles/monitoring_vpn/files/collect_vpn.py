#!/usr/bin/env python3
"""Collect active VPN client metrics for node exporters.

Observes the local VPN entrypoints (3x-ui/xray on this host) and writes
Prometheus textfile metrics:

* socrat_vpn_trojan_connections - total established TCP streams on inbound
  ports, a transport level intensity signal. Multiplexed clients (XHTTP,
  gRPC, mux) hold many streams at once, so this number is deliberately not
  a client count.
* socrat_vpn_active_clients - VPN client accounts (xray emails) whose
  traffic counters grew within the activity window, i.e. clients currently
  passing traffic. Counted from the xray expvar endpoint, so scanners that
  never authenticate and carrier NAT duplicates never inflate the number.
* socrat_vpn_client_active{email=...} - per-account activity so individual
  clients can be inspected without ssh.
"""

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.request


def peer_host(line):
    """Extract the peer host from an ss line, mapping IPv4-in-IPv6 to dotted form."""
    tokens = [t for t in line.split() if ':' in t]
    if not tokens:
        return None
    token = tokens[-1]
    if token.startswith('['):
        host = token.split(']', 1)[0].lstrip('[')
    else:
        host = token.rsplit(':', 1)[0]
    if host.startswith('::ffff:'):
        host = host[len('::ffff:'):]
    return host


def is_private(host):
    """True for loopback, link-local and RFC1918 ranges the collector ignores."""
    if ':' in host:
        return True
    if host.startswith(('10.', '127.', '192.168.', '0.')):
        return True
    if host.startswith('172.'):
        try:
            second = int(host.split('.')[1])
        except (IndexError, ValueError):
            return False
        return 16 <= second <= 31
    return False


def observe_streams(ports):
    """Return established TCP stream count on the given local ports."""
    filters = ' or '.join(f'sport = :{port}' for port in ports)
    result = subprocess.run(
        ['ss', '-H', '-t', 'state', 'established', f'( {filters} )'],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return len([line for line in result.stdout.splitlines() if line.strip()])


def read_xray_user_counters(url, timeout):
    """Read cumulative per-user traffic counters from the xray expvar endpoint."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.load(response)
    users = payload['stats']['user']
    counters = {}
    for email, usage in users.items():
        counters[email] = int(usage.get('downlink', 0)) + int(usage.get('uplink', 0))
    return counters


def active_users(counters, state, now, window):
    """Merge new counters into the state, refresh per-user last-activity
    timestamps, and return accounts that transferred traffic within the window."""
    last_active = state.setdefault('last_active', {})
    previous = state.setdefault('counters', {})
    for email, total in counters.items():
        if total > previous.get(email, total):
            last_active[email] = now
    for email in list(last_active):
        if email not in counters:
            del last_active[email]
            previous.pop(email, None)
    state['counters'] = dict(counters)
    return sorted(email for email, when in last_active.items()
                  if now - when <= window)


def write_state(path, state):
    handle, name = tempfile.mkstemp(dir=os.path.dirname(path) or '.',
                                    prefix='.vpn-state-')
    try:
        with os.fdopen(handle, 'w') as stream:
            json.dump(state, stream)
        os.chmod(name, 0o644)
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def write_metrics(path, streams, users, success):
    timestamp = time.time()
    lines = [
        '# HELP socrat_vpn_trojan_connections Established TCP streams on the local VPN entrypoint ports.',
        '# TYPE socrat_vpn_trojan_connections gauge',
        f'socrat_vpn_trojan_connections {streams}',
        '# HELP socrat_vpn_active_clients VPN client accounts that transferred traffic within the activity window.',
        '# TYPE socrat_vpn_active_clients gauge',
        f'socrat_vpn_active_clients {len(users)}',
        '# HELP socrat_vpn_client_active Whether this VPN client account transferred traffic within the activity window.',
        '# TYPE socrat_vpn_client_active gauge',
    ]
    for email in sorted(users):
        lines.append(f'socrat_vpn_client_active{{email="{email}"}} 1')
    lines.extend([
        '# HELP socrat_vpn_collection_success Whether the last VPN metric collection succeeded.',
        '# TYPE socrat_vpn_collection_success gauge',
        f'socrat_vpn_collection_success {1 if success else 0}',
        '# HELP socrat_vpn_collection_timestamp_seconds Unix time of the last successful VPN metric collection.',
        '# TYPE socrat_vpn_collection_timestamp_seconds gauge',
        f'socrat_vpn_collection_timestamp_seconds {timestamp if success else 0}',
        '',
    ])
    handle, name = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.vpn-prom-')
    try:
        with os.fdopen(handle, 'w') as stream:
            stream.write('\n'.join(lines))
        os.chmod(name, 0o644)
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def try_load_state(path):
    try:
        with open(path) as stream:
            data = json.load(stream)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def collect(ports, metrics_url, metrics_timeout, window, output, state_path):
    try:
        streams = observe_streams(ports)
        counters = read_xray_user_counters(metrics_url, metrics_timeout)
        state = try_load_state(state_path)
        users = active_users(counters, state, time.time(), window)
        write_state(state_path, state)
    except (subprocess.SubprocessError, OSError, ValueError, KeyError):
        write_metrics(output, 0, [], False)
        return 1
    write_metrics(output, streams, users, True)
    return 0


def _ports(raw):
    ports = []
    for item in raw.split(','):
        item = item.strip()
        if item:
            ports.append(int(item))
    if not ports:
        raise argparse.ArgumentTypeError('at least one TCP port is required')
    return ports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ports', type=_ports, required=True,
                        help='comma-separated local VPN entrypoint TCP ports')
    parser.add_argument('--xray-metrics-url',
                        default='http://127.0.0.1:11112/debug/vars',
                        help='xray expvar endpoint exposing per-user counters')
    parser.add_argument('--xray-timeout', type=float, default=5.0,
                        help='HTTP timeout for the xray expvar endpoint in seconds')
    parser.add_argument('--activity-window', type=float, default=60.0,
                        help='seconds of counter silence before a client stops counting as active')
    parser.add_argument('--state', required=True,
                        help='state file keeping the previous snapshot of per-user counters')
    parser.add_argument('--output', required=True, help='Prometheus textfile output path')
    args = parser.parse_args()

    return collect(args.ports, args.xray_metrics_url, args.xray_timeout,
                   args.activity_window, args.output, args.state)


if __name__ == '__main__':
    raise SystemExit(main())
