#!/usr/bin/env python3
"""Render scoped identity-namespace NetBird TLS entry. Does not apply or enroll.

The old netbird-edge renderer stays inert. No CRD, watch, RBAC or chart changes.
Apply only after private connector/localAuthDisabled/PAT acceptance. Request the
Certificate before publishing the two Ingresses; never bypass certificate checks.
"""
import importlib.util
import json
from pathlib import Path
import sys
import yaml
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nb', ROOT/'scripts/netbird-pilot.py')
nb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nb)
NAME = 'netbird-edge-forwarder'
HOST = 'netbird.socrat.alchemmist.xyz'
TLS = 'netbird-pilot-tls'


def manifests():
    c = {'management_fqdn': HOST, 'ingress_class': 'traefik', 'tls_secret_name': TLS}
    docs = nb.edge_manifests(c)
    for d in docs:
        d['metadata']['namespace'] = 'identity'
        if d['metadata']['name'] == 'edge-forwarder':
            d['metadata']['name'] = NAME
        if d['kind'] == 'Deployment':
            pod = d['spec']['template']['spec']
            pod['volumes'][0]['configMap']['name'] = NAME
            pod['nodeSelector'] = {'kubernetes.io/hostname': 'socrat-0'}
        if d['kind'] == 'Ingress':
            for rule in d['spec']['rules']:
                for path in rule['http']['paths']:
                    path['backend']['service']['name'] = NAME
    # Only management HTTP Services: no NodePort, UDP/STUN, runtime secret exposure.
    for app in ['server', 'dashboard']:
        docs.append({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {
            'name': app, 'namespace': 'netbird-pilot'}, 'spec': {
            'selector': {'app': 'netbird-'+app}, 'ports': [{'name': 'http', 'port': 80, 'targetPort': 'http'}]}})
    docs.append({'apiVersion': 'cert-manager.io/v1', 'kind': 'Certificate', 'metadata': {
        'name': TLS, 'namespace': 'identity'}, 'spec': {'secretName': TLS, 'dnsNames': [HOST],
        'issuerRef': {'name': 'letsencrypt-http01', 'kind': 'ClusterIssuer'}}})
    # Only these forwarder pods in identity may enter management/dashboard HTTP.
    # Retain the established kubelet/loopback probe paths, not arbitrary cluster pods.
    sources = [{'ipBlock': {'cidr': cidr}} for cidr in ['192.168.0.23/32', '10.42.2.0/32', '10.42.2.1/32']]
    docs.append({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {
        'name': 'deny-cluster-signup', 'namespace': 'netbird-pilot'}, 'spec': {
        'podSelector': {}, 'policyTypes': ['Ingress'], 'ingress': [
            {'from': sources, 'ports': [{'protocol': 'TCP', 'port': 80}, {'protocol': 'TCP', 'port': 9000}]},
            {'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'identity'}},
                       'podSelector': {'matchLabels': {'app': NAME}}}],
             'ports': [{'protocol': 'TCP', 'port': 80}]}]}})
    return docs


if __name__ == '__main__':
    yaml.safe_dump_all(manifests(), sys.stdout, sort_keys=False)
