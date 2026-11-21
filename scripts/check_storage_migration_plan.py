#!/usr/bin/env python3
"""Offline fail-closed validation of the socrat-5 cold runtime migration contract."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate(plan):
    assert plan['status'] in ('prepared-not-applied', 'applied-retained-ssd-preimage')
    assert plan['node'] == 'socrat-5' and plan['service'] == 'k3s.service'
    hdd = plan['required_hdd']
    assert hdd == {'mountpoint': '/mnt/files', 'source': '/dev/sdb1', 'fstype': 'ext4'}
    runtime = plan['runtime']
    assert runtime['source'] == '/var/lib/rancher/k3s/agent/containerd'
    assert runtime['destination'] == '/mnt/files/homelab/runtime/containerd'
    assert runtime['strategy'] == 'cold-copy-then-bind-mount-original-path'
    assert runtime['delete_source_automatically'] is False
    assert runtime['minimum_destination_headroom_bytes'] >= 20 * 1024**3
    assert '/var/lib/rancher/k3s/server' in runtime['keep_on_ssd']
    assert plan['tiers']['default_for_socrat5_application_templates'] == 'local-hdd'
    assert plan['tiers']['cluster_default'] == 'nfs-shared'
    for gate in ['fresh-proxmox-physical-capacity-and-vm105-backing-identity',
                 'independent-live-etcd-quorum-and-surviving-api-health',
                 'explicit-owner-approved-downtime-window',
                 'cold-containerd-and-shim-shutdown-verified',
                 'rollback-copy-and-config-preimages-preserved']:
        assert gate in plan['maintenance_gates']


if __name__ == '__main__':
    validate(json.loads((ROOT / 'deploy/storage/plans/socrat5-hdd-first.json').read_text()))
    print('Cold migration contract OK; no runtime actions performed')
