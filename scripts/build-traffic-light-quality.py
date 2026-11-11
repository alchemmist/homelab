"""Add native quality panels only in approved empty TV cells; preserve owner layout."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'charts/monitoring-k3s/dashboards/traffic-light.json'
DS = {'type': 'prometheus', 'uid': 'prometheus'}
IDS = {930, 931, 932, 933, 934, 935}


def fresh_job(job):
    return f'(max(up{{job="{job}"}}) == 1) and on() (time() - max(timestamp(up{{job="{job}"}})) < 90)'


def fresh_metric(metric):
    return f'(time() - max(timestamp({metric})) < 90)'


def stat(pid, name, grid, expr, unit, description, trend=False, bands=None, decimals=0):
    mappings = {'-2': {'text': 'No telemetry', 'color': '#808080'},
                '-1': {'text': 'Low sample' if pid == 932 else 'Never succeeded', 'color': '#808080'},
                '-3': {'text': 'Job missing', 'color': '#808080'}}
    if pid in (931, 933):
        mappings = {'-2': mappings['-2']}
    elif pid == 932:
        mappings.pop('-3')
    defaults = {'displayName': name, 'unit': unit, 'decimals': decimals, 'min': 0,
                'noValue': 'No telemetry', 'color': {'mode': 'thresholds'} if bands else {'mode': 'fixed', 'fixedColor': '#5794F2'},
                'mappings': [{'type': 'value', 'options': mappings}],
                'thresholds': {'mode': 'absolute', 'steps': bands or [{'color': '#5794F2', 'value': None}]}}
    return {'id': pid, 'type': 'stat', 'title': '', 'transparent': False, 'datasource': DS,
            'description': description, 'gridPos': grid, 'fieldConfig': {'defaults': defaults, 'overrides': []},
            'options': {'colorMode': 'value', 'graphMode': 'area' if trend else 'none', 'justifyMode': 'center',
                        'orientation': 'vertical', 'textMode': 'value_and_name', 'wideLayout': False,
                        'text': {'titleSize': 13, 'valueSize': 30},
                        'reduceOptions': {'values': False, 'calcs': ['last'], 'fields': ''}},
            'timeFrom': '1h', 'hideTimeOverride': True, 'targets': [{'refId': 'A', 'datasource': DS, 'expr': expr,
             'legendFormat': name, 'format': 'time_series', 'instant': not trend, 'range': trend, 'interval': '15s'}]}


def panels():
    wait = 'vllm:num_requests_waiting{job="vllm"}'
    out = 'vllm:generation_tokens_total{job="vllm"}'
    count = 'vllm:time_to_first_token_seconds_count{job="vllm"}'
    bucket = 'vllm:time_to_first_token_seconds_bucket{job="vllm"}'
    wg = f'({fresh_job("vllm")}) and on() {fresh_metric(wait)}'
    og = f'({fresh_job("vllm")}) and on() {fresh_metric(out)}'
    tg = f'({fresh_job("vllm")}) and on() {fresh_metric(count)} and on() {fresh_metric(bucket)}'
    sample = f'sum(increase({count}[15m]))'
    quantile = f'histogram_quantile(0.95, sum by(le) (rate({bucket}[15m])))'
    ttft = f'((({quantile}) and on() ({sample} >= 20)) or (vector(-1) and on() ({sample} < 20))) and on() ({tg})'
    result = [
        stat(931, 'AI · waiting', {'x': 12, 'y': 14, 'w': 4, 'h': 4},
             f'(sum({wait}) and on() ({wg})) or vector(-2)', 'short',
             'Local vLLM waiting requests, not GPU utilization or remote LiteLLM queue. Current value with 1h trend; blue is informational, not an alert. Fresh up/sample guard90s. Missing latest data is explicit No telemetry (-2), never a healthy zero. last reducer keeps latest state, not lastNotNull.', True),
        stat(932, 'AI · first token p95', {'x': 16, 'y': 14, 'w': 4, 'h': 4},
             f'({ttft}) or vector(-2)', 's',
             'Local vLLM estimated time to first token p95 over15m, not full streamed-response duration or remote models. Require at least20 histogram observations; otherwise Low sample, not zero. Fresh count/bucket/up guards90s. Display bands10s/60s are visual guidance, not an agreed SLO or firing alert.',
             bands=[{'color': '#5794F2', 'value': None}, {'color': '#FFB357', 'value': 10}, {'color': '#F2495C', 'value': 60}], decimals=1),
        stat(933, 'AI · output tok/s', {'x': 20, 'y': 14, 'w': 4, 'h': 4},
             f'(sum(rate({out}[5m])) and on() ({og})) or vector(-2)', 'short',
             'Local vLLM aggregate generated tokens/s, rolling5m rate with1h trend. Not per-request speed, input tokens, concurrency or a billing measure. Zero while idle is valid only with fresh healthy telemetry; absent/down/stale produces No telemetry.', True, decimals=1),
    ]
    for pid, namespace, job, label, warning, limit in [
        (934, 'lms', 'lms-database-backup', 'LMS · backup age', 6*3600, 8*3600),
        (935, 'automation', 'n8n-backup', 'n8n · backup age', 24*3600, 26*3600),
    ]:
        selector = f'namespace="{namespace}",cronjob="{job}"'
        success = f'kube_cronjob_status_last_successful_time{{{selector}}}'
        info = f'kube_cronjob_info{{{selector}}}'
        exists = f'count({info}) > 0'
        guard = f'({fresh_job("kube-state-metrics")}) and on() {fresh_metric(info)}'
        age = f'(time() - max({success} > 0)) and on() {fresh_metric(success)}'
        # Existing job without a success is distinct from missing job and dead KSM.
        value = f'(({age}) or (vector(-1) unless on() count({success} > 0))) and on() ({exists})'
        expr = f'((({value}) and on() ({guard})) or (vector(-3) unless on() ({exists}))) and on() ({fresh_job("kube-state-metrics")})'
        result.append(stat(pid, label, {'x': 12 if pid == 934 else 18, 'y': 18, 'w': 6, 'h': 2},
                           f'({expr}) or vector(-2)', 's',
                           f'Age of last successful {namespace}/{job} CronJob. A successful Job is NOT proof of archive integrity, off-host copy or successful restore. Bands: warning{warning//3600}h, overdue{limit//3600}h. Missing job/never succeeded/no telemetry distinct; up and sample freshness90s.',
                           bands=[{'color': '#26783D', 'value': None}, {'color': '#FFB357', 'value': warning}, {'color': '#F2495C', 'value': limit}]))
    psi = 'socrat:node_pressure_waiting:ratio5m'
    node_up = 'max by(node) (label_replace(up{job="node-exporter"} * on(instance) group_left(nodename) node_uname_info{job="node-exporter"}, "node", "$1", "nodename", "(.+)")) == 1'
    pressure_ok = 'max by(node) (label_replace((node_scrape_collector_success{job="node-exporter",collector="pressure"} == 1) * on(instance) group_left(nodename) node_uname_info{job="node-exporter"}, "node", "$1", "nodename", "(.+)")) == 1'
    raw = f'({psi} and on(node) ({node_up}) and on(node) ({pressure_ok}) and on(node) (time() - socrat:node_exporter_last_success_timestamp_seconds < 90) and (time() - timestamp({psi}) < 90))'
    complete = f'count by(resource) ({raw}) == on() group_left count(count by(node) (kube_node_info{{job="kube-state-metrics"}}))'
    expr = f'topk by(resource) (1, ({raw}) and on(resource) ({complete})) and on() ({fresh_job("kube-state-metrics")}) and on() {fresh_metric("kube_node_info{job=\"kube-state-metrics\"}")}'
    expr = f'label_replace({expr}, "short_node", "$1", "node", "socrat-(.+)")'
    for resource, label in [('cpu', 'CPU'), ('memory', 'RAM'), ('io', 'I/O')]:
        expr = f'label_replace({expr}, "resource_label", "{label}", "resource", "{resource}")'
    result.append({'id': 930, 'type': 'bargauge', 'title': 'Resource wait', 'datasource': DS,
                   'description': 'Worst node per resource: CPU, memory and I/O PSI some waiting ratio averaged5m. This is time with at least one stalled task, NOT utilization, queue length or fraction of all tasks. Complete fresh node inventory required; no missing node silently excluded. Display amber follows existing contention boundaries25%CPU/10%memory+I/O; actual alert additionally requires10m. Names show resource and node digit (CPU · 4 = socrat-4); short labels avoid native name clipping on TV. No fixed node ordering.',
                   'gridPos': {'x': 12, 'y': 10, 'w': 4, 'h': 4},
                   'fieldConfig': {'defaults': {'unit': 'percentunit', 'min': 0, 'max': 1, 'decimals': 0, 'noValue': 'No telemetry', 'color': {'mode': 'thresholds'},
                   'thresholds': {'mode': 'absolute', 'steps': [{'color': '#5794F2', 'value': None}, {'color': '#FFB357', 'value': .10}]}},
                   'overrides': [{'matcher': {'id': 'byRegexp', 'options': '^CPU'}, 'properties': [{'id': 'thresholds', 'value': {'mode': 'absolute', 'steps': [{'color': '#5794F2', 'value': None}, {'color': '#FFB357', 'value': .25}]}}]}]},
                   'options': {'orientation': 'horizontal', 'displayMode': 'gradient', 'valueMode': 'color', 'namePlacement': 'left', 'showUnfilled': True,
                               'sizing': 'manual', 'minVizHeight': 0, 'minVizWidth': 0, 'maxVizHeight': 100, 'reduceOptions': {'values': False, 'calcs': ['last'], 'fields': ''}, 'text': {'titleSize': 10, 'valueSize': 14}},
                   'targets': [{'refId': 'A', 'datasource': DS, 'expr': expr, 'instant': True, 'range': False, 'format': 'time_series', 'legendFormat': '{{resource_label}} · {{short_node}}'}]})
    return result


def build(source=None):
    d = copy.deepcopy(source if source is not None else json.loads(SOURCE.read_text()))
    existing = {p['id']: p for p in d['panels']}
    additions = panels()
    occupied = set()
    for p in d['panels']:
        if p['id'] not in IDS:
            g = p['gridPos']
            occupied.update((x,y) for x in range(g['x'], g['x']+g['w']) for y in range(g['y'], g['y']+g['h']))
    for p in additions:
        if p['id'] in existing:
            p['gridPos'] = copy.deepcopy(existing[p['id']]['gridPos'])
        g = p['gridPos']
        for x in range(g['x'],g['x']+g['w']):
            for y in range(g['y'],g['y']+g['h']):
                if (x,y) in occupied or not(0 <= x < 24 and 0 <= y < 20):
                    raise ValueError('Quality panel overlaps owner layout; stop rather than move panels')
                occupied.add((x,y))
    d['panels'] = [p for p in d['panels'] if p['id'] not in IDS] + additions
    return d


if __name__ == '__main__':
    SOURCE.write_text(json.dumps(build(), ensure_ascii=False, indent=2)+'\n')
