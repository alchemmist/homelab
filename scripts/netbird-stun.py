#!/usr/bin/env python3
"""Render source-preserving, bounded STUN-only listener on existing socrat-2.

No apply, secret, TURN allocation, firewall or VPN mutation.
Host networking avoids kube-proxy externalIPs local-origin SNAT.
"""
import argparse
import json
from pathlib import Path
import yaml

NS = 'netbird-pilot'
PUBLIC_IP = '176.98.185.59'
LOCK = Path(__file__).resolve().parents[1] / 'deploy/netbird/images.lock.json'
PIN = 'sha256:a00afb5b4890de4df22bbe70379c6b316685dffee297d53cac1271dcb91fab93'


def image():
    item = json.loads(LOCK.read_text())['images']['stun']
    if item['repository'] != 'coturn/coturn' or item['tag'] != '4.7.0' or item['digest'] != PIN:
        raise ValueError('reviewed official STUN image pin drift')
    return item['repository'] + ':' + item['tag'] + '@' + item['digest']


def manifests():
    labels = {'app': 'netbird-stun'}
    return [
        {'apiVersion': 'apps/v1', 'kind': 'Deployment',
         'metadata': {'name': 'stun', 'namespace': NS},
         'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
                  'selector': {'matchLabels': labels},
                  'template': {'metadata': {'labels': labels}, 'spec': {
                      'nodeSelector': {'kubernetes.io/hostname': 'socrat-2'},
                      'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet',
                      'automountServiceAccountToken': False,
                      'securityContext': {'runAsNonRoot': True, 'runAsUser': 65534,
                                          'runAsGroup': 65534, 'seccompProfile': {'type': 'RuntimeDefault'}},
                      'containers': [{'name': 'stun', 'image': image(),
                          'command': ['/usr/bin/turnserver'],
                          'args': ['-n', '--stun-only', '--no-auth', '--no-tcp', '--no-tls',
                                   '--no-dtls', '--no-cli', '--no-tcp-relay', '--relay-threads=1',
                                   '--listening-port=3478', '--listening-ip=' + PUBLIC_IP,
                                   '--no-software-attribute', '--log-file=stdout', '--simple-log',
                                   '--pidfile=/tmp/turnserver.pid'],
                          'ports': [{'name': 'stun', 'containerPort': 3478, 'protocol': 'UDP'}],
                          'resources': {'requests': {'memory': '8Mi', 'cpu': '5m'},
                                        'limits': {'memory': '32Mi', 'cpu': '100m'}},
                          'securityContext': {'allowPrivilegeEscalation': False,
                                              'readOnlyRootFilesystem': True,
                                              # Official binary carries this file capability; retain
                                              # its bounding bit even though 3478 is unprivileged.
                                              'capabilities': {'drop': ['ALL'], 'add': ['NET_BIND_SERVICE']}},
                          'volumeMounts': [{'name': 'tmp', 'mountPath': '/tmp'}]}],
                      'volumes': [{'name': 'tmp', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '1Mi'}}]
                  }}}},
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.parse_args()
    print(yaml.safe_dump_all(manifests(), sort_keys=False), end='')


if __name__ == '__main__':
    main()
