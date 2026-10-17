import importlib.util
import json
import math
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('monitoring_checks', ROOT / 'scripts/check-monitoring.py')
MONITORING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MONITORING)
HOST = 'socrat-0'
JOBS = {'vllm', 'litellm', 'llm-switcher'}


def main():
    deadline = time.monotonic() + 120
    while True:
        targets = [t for t in MONITORING.prometheus(HOST, 'targets')['activeTargets'] if t['labels'].get('job') in JOBS]
        if {t['labels']['job'] for t in targets} == JOBS and all(t['health'] == 'up' for t in targets):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('LLM scrape targets are missing or unhealthy')
        time.sleep(5)
    print('PASS: authenticated LiteLLM, vLLM and switcher scrape targets are UP')
    for expression in [
        'socrat_gpu_temperature_celsius', 'socrat_gpu_utilization_ratio',
        'socrat_gpu_memory_used_bytes', 'socrat_gpu_memory_total_bytes',
        'socrat_gpu_power_watts', 'socrat_gpu_fan_speed_ratio',
        'vllm:num_requests_running{job="vllm"}', 'vllm:num_requests_waiting{job="vllm"}',
        'vllm:kv_cache_usage_perc{job="vllm"}', 'llm_switcher_requests_waiting',
        'llm_switcher_requests_running', 'litellm_in_flight_requests{job="litellm"}',
    ]:
        values = MONITORING.query(HOST, expression)
        MONITORING.require(bool(values) and all(math.isfinite(float(x['value'][1])) for x in values), expression + ' is available')
    for expression in [
        'socrat_gpu_collection_success * on(instance) ((time() - socrat_gpu_collection_timestamp_seconds) < bool 60)',
        'llm_switcher_scrape_success',
    ]:
        values = MONITORING.query(HOST, expression)
        MONITORING.require(bool(values) and all(float(x['value'][1]) == 1 for x in values), expression + ' is healthy')
    dashboard = MONITORING.kubectl(HOST, 'get', '--raw', '/api/v1/namespaces/cattle-monitoring-system/services/http:kube-prometheus-stack-grafana:80/proxy/api/dashboards/uid/socrat-llm')['dashboard']
    source = json.loads((ROOT / 'charts/monitoring-k3s/dashboards/llm.json').read_text())
    MONITORING.require(dashboard['title'] == 'LLM' and len(dashboard['panels']) == len(source['panels']), 'LLM dashboard is provisioned')
    MONITORING.require([t['expr'] for p in dashboard['panels'] for t in p.get('targets', [])] == [t['expr'] for p in source['panels'] for t in p.get('targets', [])], 'Provisioned queries match the repository')
    count = 0
    empty = set()
    for panel in dashboard['panels']:
        for target in panel.get('targets', []):
            expr = target['expr'].replace('${model:regex}', '.*').replace('$model', '.*').replace('$__rate_interval', '5m').replace('$__range', '3h')
            values = MONITORING.query(HOST, expr)
            count += 1
            if not values or not any(math.isfinite(float(x['value'][1])) for x in values):
                empty.add(panel['title'])
    print('PASS:', count, 'dashboard queries execute without PromQL errors')
    if empty:
        print('Panels without recent observations:', ', '.join(sorted(empty)))


if __name__ == '__main__':
    main()
