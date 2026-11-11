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
                '-1': {'text': 'Never succeeded', 'color': '#808080'},
                '-3': {'text': 'Job missing', 'color': '#808080'}}
    defaults = {'displayName': name, 'unit': unit, 'decimals': decimals, 'min': 0,
                'noValue': 'No telemetry', 'color': {'mode': 'thresholds'} if bands else {'mode': 'fixed', 'fixedColor': '#CCA470'},
                'mappings': [{'type': 'value', 'options': mappings}],
                'thresholds': {'mode': 'absolute', 'steps': bands or [{'color': '#CCA470', 'value': None}]}}
    return {'id': pid, 'type': 'stat', 'title': '', 'transparent': False, 'datasource': DS,
            'description': description, 'gridPos': grid, 'fieldConfig': {'defaults': defaults, 'overrides': []},
            'options': {'colorMode': 'value', 'graphMode': 'area' if trend else 'none', 'justifyMode': 'center',
                        'orientation': 'vertical', 'textMode': 'value_and_name', 'wideLayout': False,
                        'text': {'titleSize': 13, 'valueSize': 30},
                        'reduceOptions': {'values': False, 'calcs': ['last'], 'fields': ''}},
            'targets': [{'refId': 'A', 'datasource': DS, 'expr': expr,
             'legendFormat': name, 'format': 'time_series', 'instant': not trend, 'range': trend, 'interval': '15s'}]}


def traffic(pid, name, namespace, pod, color):
    # cAdvisor exports pod network once on the sandbox (no container label here).
    # Byte rates include protocol/probe traffic: NEVER call these object/OCI counts.
    labels = f'namespace="{namespace}",pod=~"{pod}",interface="eth0",job="kubelet"'
    metric = '{__name__=~"container_network_(receive|transmit)_bytes_total",'+labels+'}'
    metric = f'label_join({metric}, "d", "", "__name__")'
    up = 'up{job="kubelet",metrics_path="/metrics/cadvisor"}'
    info = f'kube_pod_info{{namespace="{namespace}",pod=~"{pod}"}}'
    current = f'({info} and (time()-timestamp({info})<90))'
    live = f'({metric} and (time()-timestamp({metric})<90) and on(instance) ({up}==1) and on(namespace,pod) {current})'
    coverage = f'count({live}) == on() (2*count({current}))'
    rates = []
    for direction, alias in [('receive', 'RX'), ('transmit', 'TX')]:
        rates.append(f'label_replace(rate(container_network_{direction}_bytes_total{{{labels}}}[5m]), "direction", "{alias}", "pod", ".+")')
    expr = f'(sum by(direction)(({rates[0]} or {rates[1]}) and ignoring(direction,d) {live}) and on() ({coverage})) and on() ({fresh_job("kube-state-metrics")})'
    missing = ' or '.join(f'label_replace(vector(-2), "direction", "{d}", "__name__", ".*")' for d in ['RX','TX'])
    expr = f'({expr}) or on(direction) ({missing})'
    targets = [{'refId': 'A', 'datasource': DS, 'expr': expr, 'legendFormat': '{{direction}}',
                'format': 'time_series', 'instant': False, 'range': True, 'interval': '15s'}]
    return {'id': pid, 'type': 'stat', 'title': '', 'datasource': DS,
            'description': f'{name} '+('storage pod' if pid == 931 else 'registry pod only')+' RX/TX bytes/s5m, last1h; includes internal traffic/overhead, NOT object or OCI counts/availability. Fresh cAdvisor/current Pod coverage90s. Latest missing=-2/No telemetry, never zero. Independent sparkline scales: compare numbers, not heights.',
            'gridPos': {'x': 12 if pid == 931 else 18, 'y': 14, 'w': 6, 'h': 4},
            'timeFrom': '1h', 'hideTimeOverride': True,
            'fieldConfig': {'defaults': {'displayName': f'{name} · ${{__field.labels.direction}}', 'unit': 'Bps', 'min': 0, 'decimals': 0, 'noValue': 'No telemetry',
                'color': {'mode': 'fixed', 'fixedColor': color},
                'mappings': [{'type':'value','options':{'-2':{'text':'No telemetry','color':'#808080'}}}]},
                'overrides': []},
            'options': {'colorMode': 'value', 'graphMode': 'area', 'justifyMode': 'center',
                        'orientation': 'vertical', 'wideLayout': False, 'textMode': 'value_and_name',
                        'text': {'titleSize': 12, 'valueSize': 26},
                        'reduceOptions': {'values': False, 'calcs': ['last'], 'fields': ''}}, 'targets': targets}


def ai_quality():
    wait = 'vllm:num_requests_waiting{job="vllm"}'
    count = 'vllm:time_to_first_token_seconds_count{job="vllm"}'
    bucket = 'vllm:time_to_first_token_seconds_bucket{job="vllm"}'
    queue = f'sum({wait} and (time()-timestamp({wait})<90) and on(instance) (up{{job="vllm"}}==1))'
    queue = f'({queue} and on() ({fresh_job("vllm")})) or vector(-2)'
    sample = f'sum(increase({count}[15m]))'
    q = f'histogram_quantile(0.95,sum by(le)(rate({bucket}[15m])))'
    valid = f'(({q}) >= 0) and (({q}) < +Inf)'
    latency = f'(({valid}) and on() ({sample}>=20)) or (vector(-1) and on() ({sample}<20))'
    guard = f'({fresh_job("vllm")}) and on() {fresh_metric(count)} and on() {fresh_metric(bucket)}'
    latency = f'(({latency}) and on() ({guard})) or vector(-2)'
    return {'id': 930, 'type': 'stat', 'title': '', 'datasource': DS,
            'description': 'Local vLLM: current waiting requests + estimated first-token p95 over15m, NOT full streamed-response duration or remote LiteLLM models. Require20 histogram observations; otherwise Low sample, not0. Up/sample freshness90s; absent/invalid=No telemetry. Pink informational, no invented SLO.',
            'gridPos': {'x':12,'y':10,'w':4,'h':4},
            'fieldConfig': {'defaults': {'unit':'short','min':0,'decimals':0,'noValue':'No telemetry',
                'color': {'mode':'fixed','fixedColor':'#E0A6DC'},
                'mappings': [{'type':'value','options':{'-2':{'text':'No telemetry','color':'#808080'},'-1':{'text':'Low sample','color':'#808080'}}}]},
                'overrides': [{'matcher':{'id':'byName','options':'AI · TTFT p95'},'properties':[{'id':'unit','value':'s'},{'id':'decimals','value':1}]}]},
            'options': {'colorMode':'value','graphMode':'none','justifyMode':'center','orientation':'horizontal',
                'wideLayout':False,'textMode':'value_and_name','text':{'titleSize':11,'valueSize':22},
                'reduceOptions':{'values':False,'calcs':['last'],'fields':''}},
            'targets': [{'refId':ref,'datasource':DS,'expr':expr,'instant':True,'range':False,'format':'time_series','legendFormat':name}
                for ref,expr,name in [('A',queue,'AI · queue'),('B',latency,'AI · TTFT p95')]]}


def panels():
    result = [traffic(931, 'RustFS', 'rustfs', 'rustfs-.*', '#B877D9'),
              traffic(932, 'Harbor', 'harbor', 'harbor-registry-.*', '#2EBFA5'),
              ai_quality()]
    for pid, namespace, job, label, warning, limit in [
        (934, 'lms', 'lms-database-backup', 'LMS · backup age', 6*3600, 8*3600),
        (935, 'automation', 'n8n-backup', 'n8n · backup age', 24*3600, 26*3600),
    ]:
        selector = f'namespace="{namespace}",cronjob="{job}"'
        success = f'kube_cronjob_status_last_successful_time{{{selector}}}'
        info = f'kube_cronjob_info{{{selector}}}'
        exists = f'count({info}) > 0'
        guard = fresh_metric(info)
        age = f'(time() - max({success} > 0)) and on() {fresh_metric(success)}'
        # Existing job without a success is distinct from missing job and dead KSM.
        value = f'(({age}) or (vector(-1) unless on() count({success} > 0))) and on() ({exists})'
        expr = f'((({value}) and on() ({guard})) or (vector(-3) unless on() ({exists}))) and on() ({fresh_job("kube-state-metrics")})'
        result.append(stat(pid, label, {'x': 12 if pid == 934 else 18, 'y': 18, 'w': 6, 'h': 2},
                           f'({expr}) or vector(-2)', 's',
                           f'Last successful {namespace}/{job} age; NOT proof of archive integrity/offhost copy/restore. Bands{warning//3600}/{limit//3600}h. Missing/never succeeded/no telemetry distinct; up/sample fresh90s.',
                           bands=[{'color': '#26783D', 'value': None}, {'color': '#FFB357', 'value': warning}, {'color': '#F2495C', 'value': limit}]))
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


def write(d):
    SOURCE.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    write(build())
