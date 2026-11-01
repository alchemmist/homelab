"""Bounded native Loki per-source delivery counters; never fetch log bodies.

Observed counts are delivery evidence, not SDK coverage or explanations for
missing sources. Join against the independently captured source registry.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import ssl
import time
import urllib.parse
import urllib.request

QUERIES = {
    'podContainers': 'sum by (k8s_namespace_name,audit_pod,audit_container) (count_over_time({k8s_namespace_name!=""} | label_format audit_pod="{{.k8s_pod_name}}", audit_container="{{.k8s_container_name}}" [1h]))',
    'hostUnits': 'sum by (host_name,service_name) (count_over_time({host_name!=""} [1h]))',
}


def select_counts(document):
    if document.get('status') != 'success' or document.get('warnings') or document['data'].get('resultType') != 'vector':
        raise ValueError('Native count query failed/partial/wrong type')
    results = document['data']['result']
    if len(results) > 3000:
        raise ValueError('Metadata-only delivery matrix exceeds source budget')
    for point in results:
        count = float(point['value'][1])
        if not math.isfinite(count) or count < 0:
            raise ValueError('Invalid log count')
        for key, value in point.get('metric', {}).items():
            if key not in {'k8s_namespace_name', 'audit_pod', 'audit_container', 'host_name', 'service_name'} or not re.fullmatch(r'[A-Za-z0-9_.@:-]{0,253}', value):
                raise ValueError('Unexpected metadata label or value')
    return results


def run(output):
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Root-only native client credential access required')
    root = Path('/var/lib/homelab-otel/tls')
    context = ssl.create_default_context(cafile=str(root / 'ca.crt'))
    context.load_cert_chain(str(root / 'client.crt'), str(root / 'client.key'))
    result = {'observedAtUnix': time.time(), 'windowSeconds': 3600, 'logBodiesFetchedOrSaved': False,
              'fullSourceCoverageAccepted': False, 'missingSourceClassificationStillRequired': True}
    for name, query in QUERIES.items():
        url = 'https://10.250.0.3:3100/loki/api/v1/query?' + urllib.parse.urlencode({'query': query})
        with urllib.request.urlopen(url, context=context, timeout=4) as response:
            data = response.read(4 * 1024**2 + 1)
        if len(data) > 4 * 1024**2:
            raise ValueError('Metadata response exceeded budget')
        result[name] = select_counts(json.loads(data))
    with output.open('x') as target:
        target.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
