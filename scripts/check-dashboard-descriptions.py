import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOTE_AUDIT = '''
import concurrent.futures
import json
import subprocess

command = ['env', 'K3S_CONFIG_FILE=/dev/null', 'k3s', 'kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', 'get', '--raw']
base = '/api/v1/namespaces/cattle-monitoring-system/services/http:kube-prometheus-stack-grafana:80/proxy/api/'

def get(path):
    return json.loads(subprocess.check_output(command + [base + path], timeout=60))

uids = [entry['uid'] for entry in get('search?limit=1000') if entry['type'] == 'dash-db']
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    dashboards = list(pool.map(lambda uid: get('dashboards/uid/' + uid)['dashboard'], uids))
print(json.dumps(dashboards))
'''


def panel_descriptions(dashboard):
    result = {}
    for panel in dashboard.get('panels', []):
        if panel.get('type') not in {'row', 'text'}:
            result[str(panel['id'])] = panel.get('description', '')
        result.update(panel_descriptions(panel))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ssh-host', default='socrat-0')
    args = parser.parse_args()
    expected = {}
    for path in sorted((ROOT / 'deploy/monitoring/dashboard-descriptions').glob('*.json')):
        entries = json.loads(path.read_text())
        if expected.keys() & entries.keys():
            raise RuntimeError('Duplicate dashboard UID in description catalog')
        expected.update(entries)
    for path in sorted((ROOT / 'charts/monitoring-k3s/dashboards').glob('*.json')):
        dashboard = json.loads(path.read_text())
        expected[dashboard['uid']] = panel_descriptions(dashboard)
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', args.ssh_host, 'python3', '-'],
                            input=REMOTE_AUDIT, capture_output=True, text=True, timeout=180, check=True)
    dashboards = json.loads(result.stdout)
    actual = {dashboard['uid']: panel_descriptions(dashboard) for dashboard in dashboards}
    if actual.keys() != expected.keys():
        raise RuntimeError(f'Dashboard catalog differs: {sorted(actual.keys() ^ expected.keys())}')
    total = 0
    for dashboard in dashboards:
        uid = dashboard['uid']
        if actual[uid] != expected[uid]:
            raise RuntimeError(f'Descriptions differ from the repository: {dashboard["title"]}')
        for panel_id, description in actual[uid].items():
            if not isinstance(description, str) or not description.strip():
                raise RuntimeError(f'Missing description: {uid}, panel {panel_id}')
        total += len(actual[uid])
    print(f'PASS: {total} panels across {len(dashboards)} dashboards have provisioned descriptions matching the repository')


if __name__ == '__main__':
    main()
