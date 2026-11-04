#!/usr/bin/env python3
"""Bounded metadata-only retention observation through a local Prometheus port-forward.
Does not mutate the cluster, query log bodies, or assert infinite reliability.
"""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import urlopen

QUERIES = {
    'targetUp': 'min(up{job="otel-loki",scrape_owner="otel-cluster"})',
    'sampleAgeSeconds': 'max(time() - timestamp(loki_compactor_apply_retention_last_successful_run_timestamp_seconds{job="otel-loki"}))',
    'lastSuccessAgeSeconds': 'max(time() - loki_compactor_apply_retention_last_successful_run_timestamp_seconds{job="otel-loki"})',
    'retentionSuccesses': 'sum(loki_compactor_apply_retention_operation_total{job="otel-loki",status="success"})',
    'retentionFailures': 'sum(loki_compactor_apply_retention_operation_total{job="otel-loki",status="failure"})',
    'markerFiles': 'sum(loki_boltdb_shipper_retention_sweeper_marker_files_current{job="otel-loki"})',
    'sweptMarkers': 'sum(loki_boltdb_shipper_retention_sweeper_marker_files_deleted_total{job="otel-loki"})',
    'processStart': 'min(process_start_time_seconds{job="otel-loki"})',
    'retentionAlerts': 'count(ALERTS{alertname=~"LokiRetention.*",alertstate="firing"})',
}


def sample(base):
    result = {'observedAtUnix': time.time(), 'metadataOnly': True, 'metrics': {}}
    for name, query in QUERIES.items():
        with urlopen(base.rstrip('/') + '/api/v1/query?' + urlencode({'query': query}), timeout=10) as response:
            value = json.load(response)
        if value.get('status') != 'success':
            raise ValueError('Prometheus query unsuccessful')
        result['metrics'][name] = [row['value'] for row in value['data']['result']]
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prometheus', default='http://127.0.0.1:18099')
    p.add_argument('--duration-seconds', type=int, default=86400)
    p.add_argument('--interval-seconds', type=int, default=300)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 0 <= args.duration_seconds <= 86400 or args.interval_seconds < 60:
        p.error('duration must be 0..86400 and interval at least60 seconds')
    deadline = time.monotonic() + args.duration_seconds
    with args.output.open('x') as output:
        while True:
            try:
                row = sample(args.prometheus)
            except Exception as error:
                row = {'observedAtUnix': time.time(), 'errorType': type(error).__name__, 'metadataOnly': True}
            line = json.dumps(row, separators=(',', ':')) + '\n'
            if output.tell() + len(line.encode()) > 2 * 1024 * 1024:
                raise RuntimeError('2MiB observation budget reached')
            output.write(line)
            output.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(args.interval_seconds, remaining))


if __name__ == '__main__':
    main()
