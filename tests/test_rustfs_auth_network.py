"""Actual ingress DNAT contract; offline Helm only, no production authentication."""
import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def render(enabled):
    raw = subprocess.check_output([
        'helm', 'template', 'rustfs', str(ROOT / 'charts/rustfs'),
        '--namespace', 'rustfs', '-f', str(ROOT / 'charts/rustfs/values-foundation-live.yaml'),
        '--set', 'authViaTraefik=' + str(enabled).lower(),
    ], text=True)
    return {(r['kind'], r['metadata'].get('namespace', 'rustfs'), r['metadata']['name']): r
            for r in yaml.safe_load_all(raw) if r}


class AuthNetworkTests(unittest.TestCase):
    def test_only_two_policies_change_no_pod_or_stateful_resource(self):
        before, after = render(False), render(True)
        self.assertEqual(set(before), set(after))
        changed = {k for k in before if before[k] != after[k]}
        self.assertEqual(changed, {
            ('NetworkPolicy', 'rustfs', 'rustfs-isolation'),
            ('NetworkPolicy', 'identity', 'rustfs-gateway-isolation'),
        })

    def test_both_real_https_dnat_hops_are_narrowly_selected(self):
        for key, obj in render(True).items():
            if key[0] != 'NetworkPolicy' or key[2] not in ('rustfs-isolation', 'rustfs-gateway-isolation'):
                continue
            rows = obj['spec']['egress']
            peers = [r for r in rows if any('podSelector' in p and p['podSelector']['matchLabels'].get('app.kubernetes.io/name') == 'traefik' for p in r.get('to', []))]
            self.assertEqual(len(peers), 1)
            self.assertEqual(peers[0]['ports'], [{'port': 8443, 'protocol': 'TCP'}])
            lbs = [r for r in rows if any(p.get('podSelector', {}).get('matchLabels', {}).get('svccontroller.k3s.cattle.io/svcname') == 'traefik' for p in r.get('to', []))]
            self.assertEqual(len(lbs), 1)
            self.assertEqual(lbs[0]['ports'], [{'port': 443, 'protocol': 'TCP'}])
            for row in peers + lbs:
                self.assertEqual(row['to'][0]['namespaceSelector']['matchLabels'], {'kubernetes.io/metadata.name': 'kube-system'})
            self.assertNotIn('0.0.0.0/0', str(rows))
