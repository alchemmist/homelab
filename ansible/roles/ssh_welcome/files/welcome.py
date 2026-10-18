import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import textwrap
import unicodedata
from urllib.parse import quote, urlencode, urlsplit

ROOT = Path('/etc/homelab-welcome')


def clean(value):
    return ''.join(c if not unicodedata.category(c).startswith('C') else ' ' for c in str(value)).strip()


def role(labels):
    roles = []
    if any(f'node-role.kubernetes.io/{key}' in labels for key in ('control-plane', 'master')):
        roles.append('master')
    if 'node-role.kubernetes.io/etcd' in labels:
        roles.append('etcd')
    return ' + '.join(roles) or 'worker'


def urls(config, ip):
    base = config['rancher_url'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.netloc or any(ord(c) < 32 for c in base):
        raise ValueError('Rancher must have an HTTPS URL')
    cluster = quote(config['cluster'], safe='')
    node = quote(config['node'], safe='')
    address = f'[{ip}]' if ':' in ip else ip
    query = urlencode({'orgId': 1, '_dash.hideTimePicker': 'true', 'from': 'now-1h', 'to': 'now', 'refresh': '30s', 'var-instance': f"{address}:{config['exporter_port']}", 'theme': 'light', 'timezone': 'browser', 'var-datasource': 'prometheus', 'var-exporter_instance': ''})
    prefix = '' if config['cluster'] == 'local' else f'/k8s/clusters/{cluster}'
    return (f'{base}{prefix}/api/v1/namespaces/cattle-monitoring-system/services/http:rancher-monitoring-grafana:80/proxy/d/rancher-node-detail-1/node-detail?{query}', f'{base}/dashboard/c/{cluster}/explorer/node/{node}')


def metrics(disk):
    os_name = platform.freedesktop_os_release().get('PRETTY_NAME', platform.system())
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.split()[0]) * 1024
    used = memory['MemTotal'] - memory['MemAvailable']
    storage = shutil.disk_usage(disk)
    seconds = int(float(Path('/proc/uptime').read_text().split()[0]))
    cores = set()
    for cpu in Path('/proc/cpuinfo').read_text().split('\n\n'):
        fields = dict(line.split(':', 1) for line in cpu.splitlines() if ':' in line)
        fields = {k.strip(): v.strip() for k, v in fields.items()}
        if 'core id' in fields:
            cores.add((fields.get('physical id', '0'), fields['core id']))
    threads = os.cpu_count() or 1
    cpu = f'{len(cores)} cores / {threads} threads' if cores else f'{threads} logical CPUs'
    gib = lambda n: f'{n / 2**30:.1f}'
    return [('OS', os_name), ('Kernel', platform.release()), ('CPU', cpu), ('RAM', f"{gib(used)} / {gib(memory['MemTotal'])} GiB used"), ('Disk', f'{gib(storage.used)} / {gib(storage.total)} GiB used'), ('Uptime', f'{seconds // 86400}d {seconds // 3600 % 24}h {seconds // 60 % 60}m'), ('Load', ' / '.join(f'{v:.2f}' for v in os.getloadavg()))]


def render(config, portraits, stats, width=100, color=True, hyperlinks=False, logo_frame=None):
    logo = next(v['lines'] for v in portraits['variants'] if v['id'] == config['logo'])
    logo = [line.rstrip() for line in logo]
    ip = next((a['address'] for a in config['addresses'] if a['type'] == 'InternalIP'), 'unknown')
    monitoring, rancher = urls(config, ip)
    title = f"{clean(config['node'])} · Socrat k3s cluster"
    entries = [('Node', config['node']), ('Role', role(config['labels'])), ('Internal IP', ip)] + stats
    entries += [('Description', config.get('description') or 'Not set in Rancher')]
    entries += [('Monitoring', monitoring), ('Rancher', rancher)]
    entries += [(key, value) for key, value in config.get('contacts', {}).items() if value]
    logo_width = max(map(len, logo))
    side = width >= logo_width + 45
    available = max(24, width - logo_width - 4 if side else width - 2)
    info = [title, '─' * min(len(title), available)]
    for key, value in entries:
        if key in ('Monitoring', 'Rancher'):
            label = f'{key}:'
            chunks = textwrap.wrap(f'{label} {value}', available, subsequent_indent='  ', break_on_hyphens=False)
            for index, chunk in enumerate(chunks):
                if index == 0:
                    heading = f'\033[1m{label}\033[0m' if color else label
                    chunk = heading + chunk[len(label):]
                if hyperlinks:
                    chunk = f'\033]8;;{value}\033\\{chunk}\033]8;;\033\\'
                info.append(chunk)
        else:
            info.extend(textwrap.wrap(f'{clean(key)}: {clean(value)}', available, subsequent_indent='  '))
    tint = lambda s: f'\033[38;5;109m{s}\033[0m' if color else s
    lines = ['']
    if side:
        for i in range(max(len(logo), len(info))):
            left = logo[i] if i < len(logo) else ''
            lines.append('  ' + (logo_frame[i] if logo_frame is not None and i < len(logo_frame) else tint(left.ljust(logo_width))) + '  ' + (info[i] if i < len(info) else ''))
    else:
        if width >= logo_width + 2:
            lines.extend('  ' + tint(line) for line in logo)
        lines.extend('  ' + line for line in info)
    lines.append('')
    lines.extend(textwrap.wrap("This node is managed by the root user alchemmist. If you need to change system dependencies or perform other root operations, contact him via email: anton.ingrish@gmail.com or telegram: @alchemmist. More info about cluster on https://wiki.alchemmist.xyz/", min(76, max(24, width - 2))))
    lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--portraits', type=Path, default=ROOT / 'portraits.json')
    parser.add_argument('--plain', action='store_true')
    parser.add_argument('--no-animation', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    portraits = json.loads(args.portraits.read_text())
    terminal = sys.stdout.isatty() and not args.plain
    geometry = shutil.get_terminal_size()
    stats = metrics(config['disk'])
    color = terminal and 'NO_COLOR' not in os.environ and os.environ.get('TERM', 'dumb') != 'dumb'
    hyperlinks = terminal and os.environ.get('HOMELAB_WELCOME_HYPERLINKS', '0') == '1'
    sample = next(v for v in portraits['variants'] if v['id'] == config['logo'])
    animate = (config.get('animation', False) and color and sys.stdin.isatty()
               and not args.no_animation and os.environ.get('HOMELAB_WELCOME_ANIMATION', '1') != '0'
               and geometry.lines >= sample['rows'] + 3 and geometry.columns >= sample['columns'] + 45)
    if animate:
        from portrait_animation import DURATION, play, portrait_frame
        colors = json.loads((ROOT / 'patina.json').read_text())[config['logo']]
        final = render(config, portraits, stats, geometry.columns, color, hyperlinks, portrait_frame(sample, colors, DURATION))
        initial = render(config, portraits, stats, geometry.columns, color, hyperlinks, [' ' * sample['columns']] * sample['rows'])
        if not play(initial, final, sample, colors, geometry, sys.stdout):
            return
        print()
    print(render(config, portraits, stats, shutil.get_terminal_size().columns, color, hyperlinks))


if __name__ == '__main__':
    main()
