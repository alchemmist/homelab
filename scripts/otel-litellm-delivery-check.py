"""Read-only per-pod native metric/log delivery counts, never fetches log bodies."""
import argparse
import json
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path


def run(pod, application='litellm'):
    if application not in ('litellm', 'vllm') or not re.fullmatch(application + r'-[a-z0-9-]+', pod):
        raise ValueError('Expected one exact allowlisted application SDK pod identity')
    root = Path('/var/lib/homelab-otel/tls')
    context = ssl.create_default_context(cafile=str(root / 'ca.crt'))
    context.load_cert_chain(str(root / 'client.crt'), str(root / 'client.key'))
    def get(url, tls=None):
        with urllib.request.urlopen(url, context=tls, timeout=4) as response:
            result = json.load(response)
        if result.get('status') != 'success' or result.get('warnings'):
            raise ValueError('Native query failed or returned partial/warning evidence')
        return result['data']['result']
    metrics = get('http://10.43.147.125:9090/api/v1/query?' + urllib.parse.urlencode({
        'query': 'up{namespace="llm",pod="' + pod + '"}', 'partial_response': 'false'}))
    logs = get('https://10.250.0.3:3100/loki/api/v1/query?' + urllib.parse.urlencode({
        'query': 'sum(count_over_time({k8s_namespace_name="llm"} | k8s_pod_name="' + pod + '" | k8s_container_name="' + application + '" [10m]))'}), context)
    ready = bool(metrics) and all(float(point['value'][1]) == 1 for point in metrics)
    count = sum(float(point['value'][1]) for point in logs)
    result = {'success': ready and count > 0, 'pod': pod, 'nativeMetricTargets': len(metrics),
              'allSelectedTargetsUp': ready, 'individualPodContainerLogEntriesLast10m': count,
              'logBodiesFetchedOrSaved': False, 'allApplicationLogCoverageComplete': False}
    if application in ('litellm', 'vllm'):
        private_logs = get('https://10.250.0.3:3100/loki/api/v1/query?' + urllib.parse.urlencode({
            'query': 'sum(count_over_time({k8s_namespace_name="llm"} | k8s_pod_name="' + pod + '" | k8s_container_name="' + application + '" |= "OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED" [2h]))'}), context)
        private_count = sum(float(point['value'][1]) for point in private_logs)
        result.update(syntheticPromptLogEntriesLast2h=private_count, syntheticPromptAbsentFromApplicationLogs=private_count == 0)
        result['success'] = result['success'] and private_count == 0
    print(json.dumps(result))
    if not result['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pod', required=True)
    parser.add_argument('--application', choices=['litellm', 'vllm'], default='litellm')
    args = parser.parse_args()
    run(args.pod, args.application)
