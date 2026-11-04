#!/usr/bin/env python3
"""Root-run local host gate; no log bodies or environment values are printed."""
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request

UNIT = 'homelab-otel-agent.service'

def metrics():
    with urllib.request.urlopen('http://127.0.0.1:8888/metrics', timeout=10) as response:
        text = response.read().decode()
    result = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        key, value = line.rsplit(' ', 1)
        try:
            result[key] = float(value)
        except ValueError:
            pass
    return result

def total(data, prefix):
    base = prefix.removesuffix('_total')
    names = {k.split('{')[0] for k in data if k.split('{')[0] in (base, base + '_total')}
    if len(names) > 1:
        raise ValueError('Ambiguous counter metric suffix: ' + base)
    return sum(v for k, v in data.items() if k.split('{')[0] in names)

if __name__ != '__main__':
    pass
elif sys.argv[1] == 'validate':
    environment = os.environ.copy()
    values = subprocess.check_output(['systemctl', 'show', UNIT, '--property=Environment', '--value'], text=True)
    environment.update(dict(v.split('=', 1) for v in shlex.split(values)))
    environment['OTEL_TLS_DIR'] = '/var/lib/homelab-otel/tls'
    outcome = subprocess.run(['/usr/local/lib/homelab-otel/otelcol-contrib', 'validate', '--config=' + sys.argv[2]], env=environment, capture_output=True)
    print(json.dumps({'configValidated': outcome.returncode == 0}))
    sys.exit(outcome.returncode)
elif sys.argv[1] == 'baseline':
    with open(sys.argv[2], 'w') as output:
        json.dump(metrics(), output)
    os.chmod(sys.argv[2], 0o600)
elif sys.argv[1] == 'health':
    # Compare two fresh post-restart samples: cumulative counters reset on restart.
    first = metrics()
    time.sleep(40)
    last = metrics()
    report = {'freshMetrics': True}
    for name in ['otelcol_exporter_sent_metric_points_total', 'otelcol_exporter_sent_log_records_total']:
        report[name] = total(last, name) - total(first, name)
    report['failedLogsDelta'] = total(last, 'otelcol_exporter_send_failed_log_records_total') - total(first, 'otelcol_exporter_send_failed_log_records_total')
    report['refusedLogsDelta'] = total(last, 'otelcol_receiver_refused_log_records') - total(first, 'otelcol_receiver_refused_log_records')
    report['enqueueFailedLogsDelta'] = total(last, 'otelcol_exporter_enqueue_failed_log_records') - total(first, 'otelcol_exporter_enqueue_failed_log_records')
    report['queueStart'] = total(first, 'otelcol_exporter_queue_size')
    report['queueSize'] = total(last, 'otelcol_exporter_queue_size')
    report['queueCapacity'] = total(last, 'otelcol_exporter_queue_capacity')
    report['active'] = subprocess.run(['systemctl', 'is-active', '--quiet', UNIT]).returncode == 0
    report['queueGrowth'] = report['queueSize'] - report['queueStart']
    ok = report['active'] and all(report[n] == 0 for n in ['failedLogsDelta', 'refusedLogsDelta', 'enqueueFailedLogsDelta']) and all(report[n] > 0 for n in ['otelcol_exporter_sent_metric_points_total', 'otelcol_exporter_sent_log_records_total']) and report['queueSize'] < max(report['queueCapacity'], 1) * .5 and report['queueGrowth'] < max(report['queueCapacity'], 1) * .01
    report['passed'] = ok
    print(json.dumps(report, sort_keys=True))
    sys.exit(0 if ok else 1)
