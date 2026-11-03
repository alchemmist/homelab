#!/usr/bin/env python3
"""Render explicit inventory admission into Git-owned Argo CD node resources.

Offline only: no cluster/API writes, no credentials, no implicit removal or
identity replacement. Commit the resulting values with the inventory change.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('node_controller', ROOT/'scripts/netbird-node-reconcile.py')
node = importlib.util.module_from_spec(spec)
spec.loader.exec_module(node)


def desired(values, inventory, image):
    hosts = set()
    def visit(group):
        entry = inventory.get(group, {})
        hosts.update(entry.get('hosts', []))
        for child in entry.get('children', []):visit(child)
    visit('Socrat')
    hostvars = inventory['_meta']['hostvars']
    node.require(hosts, 'explicit Socrat inventory required')
    addresses, reserved = {}, set()
    for host in sorted(hosts):
        variables = hostvars[host]
        reserved.update(v['address'] for v in variables['wg_socrat_admin_clients'].values())
        enabled = variables.get('netbird_node_enabled', True)
        node.require(isinstance(enabled, bool), 'netbird_node_enabled must be an explicit YAML boolean')
        if enabled:
            addresses[host] = variables['wg_socrat_nodes'][host]['address']
    node.validate_config({'nodes': addresses, 'reserved_addresses': sorted(reserved), 'image': image})
    additions = []
    resources = values['resources']
    for host, address in sorted(addresses.items()):
        old = values['nodes'].get(host)
        node.require(old is None or old == address, 'bound node address change requires explicit retirement')
        expected_keys = {('PersistentVolumeClaim', node.NS, 'machine-'+host),
                         ('Deployment', node.NS, 'machine-'+host)}
        found = {(r['kind'], r['metadata'].get('namespace'), r['metadata']['name'])
                 for r in resources} & expected_keys
        if old is not None:
            node.require(found == expected_keys, 'partial Git identity resources; no silent repair')
            continue
        node.require(not found, 'unbound existing Git resources; explicit review required')
        docs = node.manifests(host, image)
        docs[0]['metadata']['annotations'] = {'argocd.argoproj.io/sync-options': 'Prune=false,Delete=false'}
        resources.extend(docs)
        values['nodes'][host] = address
        additions.append(host)
    return additions


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    run = subprocess.run(['ansible-inventory', '--list'], cwd=ROOT/'ansible', capture_output=True, timeout=30)
    node.require(run.returncode == 0, 'inventory render failed; inspect locally without dumping hostvars')
    inventory = json.loads(run.stdout)
    path = ROOT/'deploy/netbird/values.yaml'
    values = yaml.safe_load(path.read_text())
    im = json.loads((ROOT/'deploy/netbird/images.lock.json').read_text())['images']['client']
    additions = desired(values, inventory, im['repository']+':'+im['tag']+'@'+im['digest'])
    if additions and args.check:
        print(json.dumps({'status': 'git-values-update-required', 'nodes': additions}))
        return 1
    if additions:
        path.write_text('# Adopted existing objects; no Secret values or PVC contents. Change through Git only.\n'+
                        yaml.safe_dump(values, sort_keys=False, width=110))
    print(json.dumps({'status': 'git-values-current', 'added': additions,
                      'next': 'commit inventory and values; root/Argo CD deploys, Ansible only enrolls'}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('Blocked: inspect inventory/bindings; no cluster writes were attempted', file=sys.stderr)
        sys.exit(2)
