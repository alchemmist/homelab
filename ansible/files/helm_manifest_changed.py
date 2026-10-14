import argparse
import json
import subprocess


parser = argparse.ArgumentParser()
parser.add_argument('--release', required=True)
parser.add_argument('--chart', required=True)
parser.add_argument('--namespace', required=True)
parser.add_argument('--values', required=True)
parser.add_argument('--kubeconfig', required=True)
arguments = parser.parse_args()
common = ['--namespace', arguments.namespace, '--kubeconfig', arguments.kubeconfig]
desired = subprocess.run(
    ['helm', 'template', arguments.release, arguments.chart, *common,
     '--values', arguments.values, '--dry-run=server', '--is-upgrade'],
    text=True, capture_output=True, check=True,
)
installed = subprocess.run(
    ['helm', 'get', 'manifest', arguments.release, *common],
    text=True, capture_output=True,
)
if installed.returncode != 0 and installed.stderr.strip() != 'Error: release: not found':
    installed.check_returncode()
print(json.dumps({'changed': installed.returncode != 0 or desired.stdout.strip() != installed.stdout.strip()}))
