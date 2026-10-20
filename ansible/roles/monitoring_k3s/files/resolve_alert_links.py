import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import quote, urlencode

PROMETHEUS_PATH = '/api/v1/namespaces/cattle-monitoring-system/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/rules'
RULE_RESOURCES_PATH = '/apis/monitoring.coreos.com/v1/namespaces/cattle-monitoring-system/prometheusrules'
FORMAT_QUERY_PATH = PROMETHEUS_PATH.rsplit('/', 1)[0] + '/format_query'
GRAFANA_PATH = '/api/v1/namespaces/cattle-monitoring-system/services/http:kube-prometheus-stack-grafana:80/proxy/api/frontend/settings'


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def js_hash(value):
    result = 0
    encoded = value.encode('utf-16-le', errors='surrogatepass')
    for index in range(0, len(encoded), 2):
        result = (31 * result + int.from_bytes(encoded[index:index + 2], 'little')) & 0xffffffff
    return result if result < 0x80000000 else result - 0x100000000


def query_fingerprint(query):
    query = '\n'.join(line.strip() for line in re.sub(r'#[^\n]*', '', query).split('\n') if line.strip())
    if len(query) > 1 and query.startswith('(') and query.endswith(')'):
        query = query[1:-1]
    query = re.sub(r'\s', '', query).replace('\\"', '"')
    query = re.sub(r'`([^`]*)`', r'"\1"', query)
    query = re.sub(r',(?=})', '', query).replace('{}', '')
    query = re.sub(r'''['"()\[\]\\`]''', '', query)
    return ''.join(sorted(query, key=lambda char: char.encode('utf-16-be', errors='surrogatepass')))


def pairs_fingerprint(values):
    return compact(sorted((values or {}).items(), key=lambda item: item[0]))


def rule_hash(rule, primary=False):
    fingerprint = [rule['name'], 'alerting', '' if primary else query_fingerprint(rule['query']), pairs_fingerprint(rule.get('annotations')), pairs_fingerprint(rule.get('labels'))]
    return str(js_hash(compact(fingerprint)))


def rule_url(group, rule, primary=False):
    parts = ['pri', 'Prometheus', group['file'], group['name'], rule['name'], rule_hash(rule, primary)]
    identifier = '$'.join(part.replace('$', '_DOLLAR_').replace('/', '\x1f').replace('\\', '\x1e') for part in parts)
    return '/alerting/Prometheus/' + quote(identifier, safe="~!*'()") + '/view'


def panels(dashboard):
    for panel in dashboard.get('panels', []):
        yield panel
        yield from panels(panel)


def panel_rules(panel, name_prefix=""):
    result = set()
    for target in panel.get('targets', []):
        for selector in re.findall(r'\bALERTS\s*\{([^}]*)\}', target.get('expr', '')):
            match = re.search(r'\balertname\s*(=~?)\s*"([^"\\]*)"', selector)
            if match:
                names = match.group(2).split('|')
                if not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in names):
                    if match.group(1) == '=~':
                        continue
                    raise ValueError('Unsupported alert name selector: ' + match.group(2))
                result.update(name for name in names if name.startswith(name_prefix))
    return result


def resolve(dashboard, response, settings, values_key="nodeAlertLinks", name_prefix=""):
    groups = response['data']['groups']
    primary = settings.get('featureToggles', {}).get('alertingPrometheusRulesPrimary', False)
    available = {}
    for group in groups:
        for rule in group.get('rules', []):
            if rule.get('type') == 'alerting':
                available.setdefault(rule['name'], []).append((group, rule))
    result = {}
    for panel in panels(dashboard):
        names = panel_rules(panel, name_prefix)
        if not names:
            continue
        missing = names - available.keys()
        if missing:
            raise ValueError('Rules not loaded: ' + ', '.join(sorted(missing)))
        links = []
        for name in sorted(names):
            for group, rule in available[name]:
                severity = rule.get('labels', {}).get('severity')
                links.append({'title': name + (' · ' + severity if severity else ''), 'url': rule_url(group, rule, primary), 'targetBlank': False})
        result[str(panel['id'])] = sorted(links, key=lambda link: (link['title'], link['url']))
    if not result:
        raise ValueError('Dashboard has no alert panels')
    return {values_key: result}


def expected_rules(dashboard, resources, formatter, name_prefix=""):
    names = set().union(*(panel_rules(panel, name_prefix) for panel in panels(dashboard)))
    expected = []
    cache = {}
    for resource in resources['items']:
        metadata = resource['metadata']
        suffix = metadata['namespace'] + '-' + metadata['name'] + '-' + metadata['uid'] + '.yaml'
        for group in resource['spec'].get('groups', []):
            for rule in group.get('rules', []):
                if rule.get('alert') not in names:
                    continue
                expression = str(rule['expr'])
                if expression not in cache:
                    cache[expression] = formatter(expression)
                expected.append((suffix, group['name'], {
                    'name': rule['alert'],
                    'query': cache[expression],
                    'labels': rule.get('labels', {}),
                    'annotations': rule.get('annotations', {}),
                }))
    missing = names - {rule['name'] for _, _, rule in expected}
    if missing:
        raise ValueError('Referenced rules have no Kubernetes definition: ' + ', '.join(sorted(missing)))
    return expected


def require_convergence(response, expected):
    actual = set()
    for group in response['data']['groups']:
        for rule in group.get('rules', []):
            if rule.get('type') == 'alerting':
                actual.add((group['file'].rsplit('/', 1)[-1], group['name'], rule['name'], rule_hash(rule)))
    missing = []
    for suffix, group_name, rule in expected:
        identity = (suffix, group_name, rule['name'], rule_hash(rule))
        if identity not in actual:
            missing.append(rule['name'])
    if missing:
        raise ValueError('Prometheus has not loaded current rule definitions: ' + ', '.join(sorted(set(missing))))


def fetch(path):
    env = dict(os.environ, K3S_CONFIG_FILE='/dev/null')
    completed = subprocess.run(['k3s', 'kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', 'get', '--raw', path, '--request-timeout=20s'], env=env, capture_output=True, text=True, check=True, timeout=25)
    return json.loads(completed.stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dashboard', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--values-key', default='nodeAlertLinks')
    parser.add_argument('--alert-name-prefix', default='')
    args = parser.parse_args()
    dashboard = json.loads(Path(args.dashboard).read_text())
    deadline = time.monotonic() + args.timeout
    expected = None
    while True:
        try:
            if expected is None:
                expected = expected_rules(dashboard, fetch(RULE_RESOURCES_PATH), lambda expression: fetch(FORMAT_QUERY_PATH + '?' + urlencode({'query': expression}))['data'], args.alert_name_prefix)
            response = fetch(PROMETHEUS_PATH)
            require_convergence(response, expected)
            result = resolve(dashboard, response, fetch(GRAFANA_PATH), args.values_key, args.alert_name_prefix)
            break
        except (ValueError, subprocess.SubprocessError) as error:
            if time.monotonic() >= deadline:
                raise SystemExit('Could not resolve Grafana alert links: ' + str(error)) from error
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    output = Path(args.output)
    fd, temporary = tempfile.mkstemp(prefix=output.name + '.', dir=output.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(compact(result) + '\n')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print('Resolved alert links for ' + str(len(result[args.values_key])) + ' panels')


if __name__ == '__main__':
    main()
