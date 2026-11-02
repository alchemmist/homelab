#!/usr/bin/env python3
"""Read-only TCP/TLS probes from a PILOT CLIENT; no enrollment, SSH login or fail injection.

A blocked socket alone does NOT prove policy enforcement: retain concurrent healthy-target
and non-revoked-client controls. Failover identity/timing and existing sessions need the runbook.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import sys
import time

SPEC = importlib.util.spec_from_file_location('netbird_pilot', Path(__file__).with_name('netbird-pilot.py'))
nb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nb)


def probe(ip, port, dns_name=None, tls=False, timeout=4):
    started = time.monotonic()
    result = {'ip': ip, 'port': port, 'tcp_connected': False, 'tls_verified': False}
    try:
        with socket.create_connection((ip, port), timeout=timeout) as raw:
            result['tcp_connected'] = True
            if tls:
                with ssl.create_default_context().wrap_socket(raw, server_hostname=dns_name):
                    result['tls_verified'] = True
    except (OSError, ssl.SSLError) as exc:
        result['error_class'] = type(exc).__name__  # No response bodies, certificates or credentials.
    result['duration_seconds'] = round(time.monotonic() - started, 3)
    return result


def run(c, expect, phase, attempts=1, interval=2, negative=None):
    results = []
    for attempt in range(attempts):
        for r in c['resources'] if negative is None else [negative]:
            ip = str(ipaddress.ip_network(r['address']).network_address)
            dns_ok = True
            # Do not let DNS failure turn an expected denial into a pass.
            if r.get('dns_name') and expect == 'allow':
                try:
                    resolved = {x[4][0] for x in socket.getaddrinfo(r['dns_name'], None)}
                    dns_ok = resolved == {ip}
                except OSError:
                    dns_ok = False
            for port in r['ports']:
                result = dict(probe(ip, port, r.get('dns_name'), tls=r['kind'] == 'web'))
                result.update(phase=phase, resource=r['name'], attempt=attempt + 1,
                              at=datetime.now(timezone.utc).isoformat(), expected=expect, dns_matches=dns_ok)
                result['passed'] = (result['tcp_connected'] and dns_ok and
                                    (r['kind'] != 'web' or result['tls_verified'])) if expect == 'allow' else not result['tcp_connected']
                results.append(result)
        if attempt + 1 < attempts:
            time.sleep(interval)
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', required=True, type=Path)
    p.add_argument('--expect', choices=['allow', 'deny'], required=True)
    p.add_argument('--phase', required=True, help='e.g. baseline, router-a-down, router-b-down, revoked')
    p.add_argument('--attempts', type=int, default=1)
    p.add_argument('--interval', type=float, default=2)
    p.add_argument('--negative-ip', help='One explicit denied IPv4 address, no CIDRs/ranges')
    p.add_argument('--negative-port', type=int)
    a = p.parse_args()
    c = nb.validate(json.loads(a.inputs.read_text()))
    nb.require(1 <= a.attempts <= 30 and 0 <= a.interval <= 60, 'bounded attempts/interval required')
    negative = None
    if a.negative_ip is not None or a.negative_port is not None:
        nb.require(a.expect == 'deny' and a.negative_ip and a.negative_port is not None,
                   'negative probe needs deny + explicit IP and port')
        ip = ipaddress.IPv4Address(a.negative_ip)
        nb.require(not ip.is_multicast and not ip.is_unspecified and 1 <= a.negative_port <= 65535,
                   'invalid negative target')
        negative = {'name': 'explicit-negative', 'kind': 'ssh', 'address': str(ip) + '/32', 'ports': [a.negative_port]}
    results = run(c, a.expect, a.phase, a.attempts, a.interval, negative)
    print(json.dumps({'note': 'Probe results only; see runbook for acceptance controls', 'results': results}, indent=2))
    return 0 if all(x['passed'] for x in results) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError):
        print('BLOCKED: invalid/missing probe inputs', file=sys.stderr)
        sys.exit(2)
