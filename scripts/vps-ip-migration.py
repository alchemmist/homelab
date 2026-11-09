#!/usr/bin/env python3
"""Auditable host/source portion of a VPS IPv4 migration; no implicit apply.

Stdlib only. Never prints configuration contents, peer keys, database rows or
command stderr. This is not a disk backup, GitOps deploy or acceptance runner.
"""
import argparse
import copy
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import uuid

HOSTS = ('socrat-0', 'socrat-1', 'socrat-2', 'socrat-3')
SOURCE_FILES = (
    'ansible/inventory/direct.yml', 'ansible/inventory/group_vars/Socrat.yml',
    'ansible/inventory/host_vars/socrat-2.yml',
    'ansible/roles/public_authoritative_dns/defaults/main.yml',
    'ansible/roles/wireguard_admin_client/defaults/main.yml',
    'ansible/roles/wireguard_tcp_transport/defaults/main.yml',
    'ansible/roles/identity_integrations/files/netbird_oidc.py',
    'ansible/roles/identity_integrations/files/xui_gateway.py',
    'charts/traefik-edge/values.yaml', 'charts/monitoring-k3s/values.yaml',
    'charts/monitoring-k3s/dashboards/traffic-light.json',
    'charts/rustfs/values-foundation-live.yaml',
    'deploy/netbird/values.yaml', 'deploy/socrat-bot/values.yaml',
    'scripts/public_dns_zone.py', 'scripts/check-public-ingress.py',
    'scripts/netbird-host-router.py', 'scripts/netbird-independent-relay.py',
    'scripts/netbird-signal-check.py', 'scripts/netbird-stun.py',
    'scripts/netbird-stun-check.py', 'scripts/netbird-transport-check.py',
    'scripts/identity-argocd-refresh-smoke.py', 'scripts/identity-branding-smoke.py',
    'scripts/identity-branding-controls-check.py',
    'scripts/identity-branding-error-mfa-check.py', 'scripts/identity-nature-smoke.py',
    'scripts/identity-litellm-smoke.py', 'scripts/identity-xui-gateway-smoke.py',
    'tests/test_inventory.py', 'tests/test_wireguard_admin_peers.py',
    'tests/test_wireguard_admin_client.py', 'tests/test_monitoring_vpn.py',
    'tests/test_netbird_host_router.py', 'tests/test_netbird_host_peer.py',
    'tests/test_otel_scrape_config.py', 'tests/test_public_dns_zone.py',
    'scripts/public-entry-health.py', 'scripts/vpn-home-probe.py',
    'scripts/vpn-path-check.py', 'scripts/vpn-home-session.py',
    'scripts/check-grafana-tv-public.py',
    'charts/spi-queue-ui/values.yaml', 'deploy/spi-queue-ui/values.yaml',
    'charts/spi-triage/values-off-live.yaml', 'charts/spi-triage/templates/validate.yaml',
    'tests/test_mac_private_mesh.py', 'tests/test_spi_queue_ui.py',
)
COMMON_FILES = (
    '/usr/local/libexec/public_dns_zone.py', '/usr/local/libexec/public-dns-refresh',
    '/etc/wireguard/wg-socrat.conf', '/etc/wireguard-tcp-transport/config.yaml',
    '/etc/systemd/system/wireguard-tcp-transport-guard.service',
)
VPS_FILES = ('/etc/hosts', '/etc/knot/knot.conf', '/etc/wireguard/params',
             '/etc/x-ui/install-result.env')
DATABASES = ('/srv/x-ui-lab/db/x-ui.db', '/etc/x-ui/x-ui.db')


class MigrationError(Exception):
    pass


def addresses(old, new):
    try:
        parsed = tuple(ipaddress.IPv4Address(v) for v in (old, new))
    except ipaddress.AddressValueError:
        raise MigrationError('Both addresses must be canonical IPv4 literals') from None
    if old == new or tuple(str(v) for v in parsed) != (old, new):
        raise MigrationError('Require two different canonical IPv4 addresses')
    if not all(v.is_global and not v.is_multicast and not v.is_reserved for v in parsed):
        raise MigrationError('Require public unicast IPv4 addresses')
    return parsed


def replace_address(text, old, new):
    return re.sub(r'(?<![0-9.])' + re.escape(old) + r'(?![0-9.])', new, text)


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    if result.returncode:
        # stderr may contain credentials/configuration; never echo it.
        raise MigrationError('Command failed: ' + Path(argv[0]).name)
    return result.stdout


class Preimages:
    def __init__(self, root, label):
        raw = Path(root).expanduser()
        if not raw.is_absolute() or raw.is_symlink():
            raise MigrationError('Backup root must be an absolute non-symlink directory')
        root = raw.resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise MigrationError('Backup root must be owned by caller and mode 0700')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.path = root / (label + '-' + stamp + '-' + uuid.uuid4().hex[:8])
        self.path.mkdir(mode=0o700)

    def target(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise MigrationError('Invalid preimage path')
        dest = self.path / relative
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return dest

    def save(self, path, relative):
        dest = self.target(relative)
        with dest.open('xb') as stream:
            stream.write(path.read_bytes())
        dest.chmod(0o600)
        return dest

    def receipt(self, report):
        p = self.path / 'receipt.json'
        p.write_text(json.dumps(report, indent=2) + '\n')
        p.chmod(0o600)


def refuse_unfinished(root, label):
    if not root:
        return
    directory = Path(root).expanduser()
    if not directory.is_absolute() or directory.is_symlink():
        raise MigrationError('Backup root must be absolute and not a symlink')
    if directory.exists():
        info = directory.stat()
        if not directory.is_dir() or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise MigrationError('Existing backup root must be caller-owned and mode 0700')
        for path in directory.glob(label + '-*/receipt.json'):
            state = json.loads(path.read_text()).get('state')
            if state in ('applying', 'partial-failure-stop-and-investigate'):
                raise MigrationError('Unfinished prior migration: inspect private receipts; no blind rerun')


def file_plan(paths, old, new):
    changes = []
    for path in paths:
        if path.is_symlink():
            raise MigrationError('Refusing a symlink configuration file')
        if not path.exists():
            continue
        if not path.is_file():
            raise MigrationError('Expected a regular configuration file')
        text = path.read_text()
        updated = replace_address(text, old, new)
        if updated != text:
            changes.append((path, text, updated))
    return changes


def write_changes(changes, preimages, relative):
    for path, before, after in changes:
        if path.is_symlink() or path.read_text() != before:
            raise MigrationError('Configuration drift after planning; stop and re-audit')
        preimages.save(path, relative(path))
        # Preserve owner/mode and support /etc/hosts bind mounts. Replacements
        # never change syntax, only validated IP literals. Preimages survive errors.
        with path.open('w') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())


def validate_dns_anchor(text, old, new):
    values = {}
    for name in ('HOME', 'VPS'):
        match = re.search(r'^' + name + r' = [\'"]([^\'"]+)[\'"]$', text, re.M)
        if not match:
            raise MigrationError('DNS owner anchors changed; review required')
        values[name] = match[1]
    if values['VPS'] not in (old, new):
        raise MigrationError('VPS anchor differs from both requested addresses')
    if values['HOME'] in (old, new):
        raise MigrationError('Refusing to replace the HOME entrance as a VPS address')


def repository(root, old, new, apply=False, backup_root=None):
    refuse_unfinished(backup_root, old + '-to-' + new)
    root = Path(root).resolve()
    required = (root / 'scripts/public_dns_zone.py', root / 'charts/traefik-edge/values.yaml')
    if not all(p.is_file() for p in required):
        raise MigrationError('Not the reviewed homelab repository')
    validate_dns_anchor(required[0].read_text(), old, new)
    paths = [root / name for name in SOURCE_FILES]
    if any(not p.resolve().is_relative_to(root) for p in paths):
        raise MigrationError('Source path escapes the worktree')
    if not all(p.is_file() for p in paths):
        raise MigrationError('Owned source layout changed; review the explicit manifest')
    changes = file_plan(paths, old, new)
    report = {'component': 'repository', 'apply': apply, 'changed': False,
              'planned_files': [str(p.relative_to(root)) for p, _, _ in changes]}
    if apply and changes:
        dirty = run(['git', '-C', str(root), 'status', '--porcelain=v1', '--untracked-files=all', '--', *SOURCE_FILES])
        if dirty.strip():
            raise MigrationError('Owned source files are dirty; use a clean isolated worktree')
        if not backup_root:
            raise MigrationError('Apply requires a private backup root')
        dest = Path(backup_root).expanduser().resolve()
        if dest == root or root in dest.parents:
            raise MigrationError('Repository preimages must be outside the worktree')
        store = Preimages(backup_root, old + '-to-' + new)
        report.update(preimages=str(store.path), state='applying')
        store.receipt(report)
        try:
            write_changes(changes, store, lambda p: p.relative_to(root))
            report.update(changed=True, state='source-phase-complete-not-acceptance')
        except Exception:
            report['state'] = 'partial-failure-stop-and-investigate'
            store.receipt(report)
            raise
        store.receipt(report)
    return report


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def db_state(connection):
    names = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    return {name: sorted(connection.execute('SELECT * FROM ' + quote_identifier(name)).fetchall(), key=repr)
            for (name,) in names}


def db_plan(path, old):
    if path.is_symlink():
        raise MigrationError('Refusing a symlink database')
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=20) as connection:
        if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise MigrationError('SQLite quick_check failed; preserve data and investigate')
        table = connection.execute("SELECT type FROM sqlite_master WHERE name='hosts'").fetchone()
        cols = [r[1] for r in connection.execute('PRAGMA table_info(hosts)')]
        if table != ('table',) or 'address' not in cols:
            raise MigrationError('3x-ui hosts schema changed; manual review required')
        count = connection.execute('SELECT count(*) FROM hosts WHERE address = ?', (old,)).fetchone()[0]
        partial = connection.execute('SELECT count(*) FROM hosts WHERE instr(address, ?) > 0 AND address != ?', (old, old)).fetchone()[0]
        if partial:
            raise MigrationError('Non-literal host address contains old IP; do not rewrite automatically')
    return count


def backup_database(path, store):
    """Consistent private preimage only; production connection is read-only."""
    target = store.target('sqlite/' + str(path).lstrip('/'))
    target.touch(mode=0o600, exist_ok=False)
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=20) as source:
        with sqlite3.connect(target) as backup:
            source.backup(backup)
            if backup.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise MigrationError('Database preimage failed integrity; stop')
    return target


def migrate_database(path, old, new, store):
    raise MigrationError('Production panel writes require native API; SQL migration prohibited')


def service_plan(services, reviewed=None):
    reviewed = reviewed or {}
    restart, dormant = [], []
    for service in services:
        state = run(['systemctl', 'show', service, '-p', 'ActiveState', '--value']).strip()
        if service in reviewed and reviewed[service] != state:
            raise MigrationError('Reviewed native service state drifted; re-audit')
        if state == 'activating' and run(['systemctl', 'show', service, '-p', 'SubState', '--value']).strip() != 'auto-restart':
            raise MigrationError('Only reviewed auto-restarting native transport may recover')
        if state != 'active' and reviewed.get(service) != state:
            raise MigrationError('Affected native service is not active; review before changing it')
        if state in ('active', 'activating'):
            restart.append(service)
        elif state == 'inactive':
            dormant.append(service)
        else:
            raise MigrationError('Unsupported reviewed native service state')
    return restart, dormant


def wg_endpoint_changes(text, old, new):
    result = []
    for block in text.split('[Peer]')[1:]:
        key = re.search(r'^PublicKey\s*=\s*([A-Za-z0-9+/]{43}=)\s*$', block, re.M)
        endpoint = re.search(r'^Endpoint\s*=\s*([^\s#]+)', block, re.M)
        if endpoint and endpoint[1].startswith(old + ':'):
            if not key:
                raise MigrationError('Malformed WireGuard peer block')
            allowed = re.search(r'^AllowedIPs\s*=\s*([^\n#]+)', block, re.M)
            if not allowed or '10.250.0.2/32' not in [p.strip() for p in allowed[1].split(',')]:
                raise MigrationError('Old endpoint belongs to a different peer; do not retarget it')
            port = endpoint[1].split(':')[1]
            if not port.isdigit() or not 0 < int(port) < 65536:
                raise MigrationError('Invalid WireGuard peer port')
            result.append((key[1], new + ':' + port))
    return result


def required_services(changes):
    paths = {str(p) for p, _, _ in changes}
    return [unit for path, unit in (
        ('/etc/systemd/system/wireguard-tcp-transport-guard.service', 'wireguard-tcp-transport-guard.service'),
        ('/etc/wireguard-tcp-transport/config.yaml', 'wireguard-tcp-transport.service'),
        ('/etc/knot/knot.conf', 'knot.service')) if path in paths]


def refresh_guard(old_text, new):
    match = re.search(r'wireguard-tcp-transport-guard.py\s+([A-Za-z0-9_.:-]{1,15})\s+([0-9.]+)\s+([0-9]+)', old_text)
    if not match:
        raise MigrationError('Unknown guard unit format; manual review required')
    interface, old, port = match.groups()
    # Add the new owned rule before removing exactly its old counterpart.
    run([sys.executable, '/usr/local/libexec/wireguard-tcp-transport-guard.py', interface, new, port])
    rule = ['-i', interface, '-s', old, '-p', 'udp', '--sport', port, '--dport', port,
            '-m', 'comment', '--comment', 'homelab-wg-tcp-direct-guard', '-j', 'DROP']
    check = subprocess.run(['iptables', '-w', '10', '-C', 'INPUT', *rule], capture_output=True, timeout=30)
    if check.returncode == 0:
        run(['iptables', '-w', '10', '-D', 'INPUT', *rule])
    elif check.returncode != 1:
        raise MigrationError('Unable to inspect old owned guard rule')


def host(hostname, old, new, apply=False, backup_root=None,
         allow_service_restarts=False, require_assigned=False, reviewed_service_states=None):
    if hostname not in HOSTS or socket.gethostname().split('.')[0] != hostname:
        raise MigrationError('Unexpected host identity')
    refuse_unfinished(backup_root, hostname + '-' + old + '-to-' + new)
    if require_assigned and hostname == 'socrat-2':
        links = json.loads(run(['ip', '-j', '-4', 'addr', 'show']))
        assigned = [a['local'] for link in links for a in link.get('addr_info', [])]
        if new not in assigned:
            raise MigrationError('Provider has not assigned new IPv4 on this VPS')
    paths = [Path(p) for p in COMMON_FILES + (VPS_FILES if hostname == 'socrat-2' else ())]
    if not Path('/etc/wireguard/wg-socrat.conf').is_file():
        raise MigrationError('Required WireGuard configuration is missing')
    if hostname in HOSTS[:3] and not Path('/usr/local/libexec/public_dns_zone.py').is_file():
        raise MigrationError('Required authoritative DNS owner is missing')
    dns_owner = Path('/usr/local/libexec/public_dns_zone.py')
    if dns_owner.is_file():
        validate_dns_anchor(dns_owner.read_text(), old, new)
    changes = file_plan(paths, old, new)
    peers = []
    for path, before, _ in changes:
        if str(path) == '/etc/wireguard/wg-socrat.conf':
            peers += wg_endpoint_changes(before, old, new)
        if str(path).endswith('wireguard-tcp-transport-guard.service') and not re.search(
                r'wireguard-tcp-transport-guard.py\s+\S+\s+' + re.escape(old) + r'\s+\d+', before):
            raise MigrationError('Unknown guard unit format')
    databases = {}
    if hostname == 'socrat-2':
        if not Path(DATABASES[0]).is_file():
            raise MigrationError('Primary 3x-ui database missing')
        databases = {p: db_plan(Path(p), old) for p in DATABASES if Path(p).exists()}
    services = required_services(changes)
    restart_services, dormant_services = service_plan(services, reviewed_service_states)
    report = {'component': 'host', 'host': hostname, 'apply': apply, 'changed': False,
              'planned_files': [str(p) for p, _, _ in changes],
              'planned_database_address_rows': databases, 'planned_native_service_restarts': restart_services,
              'dormant_services_preserved': dormant_services,
              'planned_wg_endpoint_updates': len(peers),
              'xui_reload_required': False,
              'native_api_address_migration_pending': bool(databases.get(DATABASES[0], 0))}
    if apply and changes:
        if os.geteuid() != 0 or not backup_root or not allow_service_restarts:
            raise MigrationError('Host apply requires root, private backup root and restart approval')
        store = Preimages(backup_root, hostname + '-' + old + '-to-' + new)
        report['preimages'] = str(store.path)
        report['state'] = 'applying'
        store.receipt(report)
        try:
            write_changes(changes, store, lambda p: str(p).lstrip('/'))
            report['database_address_rows_updated'] = {}
            for path, count in databases.items():
                if count:
                    backup_database(Path(path), store)
            for key, endpoint in peers:
                run(['wg', 'set', 'wg-socrat', 'peer', key, 'endpoint', endpoint])
            if 'wireguard-tcp-transport-guard.service' in services:
                run(['systemctl', 'daemon-reload'])
                if 'wireguard-tcp-transport-guard.service' in restart_services:
                    before = next(text for p, text, _ in changes if str(p).endswith('wireguard-tcp-transport-guard.service'))
                    refresh_guard(before, new)
            for service in restart_services:
                run(['systemctl', 'restart', service])
            if hostname in HOSTS[:3] and any(str(p).startswith('/usr/local/libexec/public') or str(p) == '/etc/hosts' for p, _, _ in changes):
                run(['/usr/local/libexec/public-dns-refresh'])
            report.update(changed=True, state='host-phase-complete-not-acceptance')
        except Exception:
            report['state'] = 'partial-failure-stop-and-investigate'
            store.receipt(report)
            raise
        store.receipt(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['repository', 'host'])
    parser.add_argument('--old-ip', required=True)
    parser.add_argument('--new-ip', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-root')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--host', choices=HOSTS)
    parser.add_argument('--require-assigned', action='store_true')
    parser.add_argument('--allow-service-restarts', action='store_true')
    parser.add_argument('--reviewed-service-states', type=json.loads, default={})
    args = parser.parse_args()
    os.umask(0o077)
    try:
        addresses(args.old_ip, args.new_ip)
        if args.component == 'repository':
            if args.root is None:
                raise MigrationError('Repository root is required')
            report = repository(args.root, args.old_ip, args.new_ip, args.apply, args.backup_root)
        else:
            report = host(args.host, args.old_ip, args.new_ip, args.apply, args.backup_root,
                          args.allow_service_restarts, args.require_assigned, args.reviewed_service_states)
        print(json.dumps(report, sort_keys=True))
    except MigrationError as error:
        print(json.dumps({'ok': False, 'error': str(error)}), file=sys.stderr)
        return 1
    except Exception as error:
        # Unanticipated errors can include SQL rows, secrets, command arguments.
        print(json.dumps({'ok': False, 'error_type': type(error).__name__,
                          'action': 'stop; inspect private preimages; no automatic rollback'}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
