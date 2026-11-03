"""Live browser -> LMS -> mTLS collector -> Tempo -> Grafana/Loki verification.

Explicit --create-canary-session creates a short-lived synthetic teacher profile,
not an impersonation of a real user or an Authentik login. It is deleted in finally.
No session value, Secret, private key or student content is saved or printed.
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def ready_canary_pod(pods, nodes):
    ready_nodes = {node['metadata']['name'] for node in nodes['items']
                   if any(c['type']=='Ready' and c['status']=='True' for c in node['status'].get('conditions', []))}
    candidates = [pod for pod in pods['items']
                  if not pod['metadata'].get('deletionTimestamp')
                  and pod['spec'].get('nodeName') in ready_nodes
                  and pod['status'].get('phase')=='Running'
                  and any(c['type']=='Ready' and c['status']=='True' for c in pod['status'].get('conditions', []))]
    if not candidates:
        raise RuntimeError('No active ready LMS pod available for canary')
    return max(candidates, key=lambda pod: pod['metadata'].get('creationTimestamp', ''))['metadata']['name']


def kubepython(code):
    def inspect(command):
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', 'socrat-0', command],
                                text=True, capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Canary pod discovery failed; sensitive output suppressed')
        return json.loads(result.stdout)
    # exec deploy/lms can select a stale Ready/Terminating pod on a lost node.
    pod = ready_canary_pod(inspect('kubectl -n lms get pods -l app.kubernetes.io/name=lms -o json'),
                           inspect('kubectl get nodes -o json'))
    command = ['ssh', '-o', 'BatchMode=yes', 'socrat-0',
               'kubectl -n lms exec -i ' + pod + ' -- python -']
    result = subprocess.run(command, input=code, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('LMS canary operation failed; sensitive output suppressed')
    return json.loads(result.stdout)


def get_json(url):
    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def hex_id(value):
    if len(value) in (16, 32) and all(c in '0123456789abcdef' for c in value):
        return value
    return base64.b64decode(value).hex()


def summarize_trace(document):
    records = []
    for batch in document.get('batches', document.get('resourceSpans', [])):
        for scope in batch.get('scopeSpans', batch.get('instrumentationLibrarySpans', [])):
            for span in scope.get('spans', []):
                records.append({'name': span['name'], 'id': hex_id(span['spanId']),
                                'parent': hex_id(span['parentSpanId']) if span.get('parentSpanId') else None,
                                'durationMs': (int(span['endTimeUnixNano']) - int(span['startTimeUnixNano'])) / 1e6})
    return records


def run(args):
    if not args.create_canary_session:
        raise ValueError('Explicit --create-canary-session required; temporary privileged test identity will be deleted')
    issuer, subject = 'urn:homelab:lms-telemetry-canary', str(uuid.uuid4())
    cookie = None
    try:
        result = kubepython(f'''
from app.config import Settings
from app.store import Store, digest
import json, time
store = Store(Settings.from_env().database_url)
cookie = store.create_session({issuer!r}, {subject!r}, 'Telemetry canary', '', role='teacher')
with store.connect() as db:
    db.execute('UPDATE sessions SET expires_at=%s WHERE token_hash=%s', (int(time.time())+900, digest(cookie)))
print(json.dumps(dict(cookie=cookie)))
''')
        cookie = result['cookie']
        env = {**os.environ, 'LMS_CHECKOUT': str(args.lms_checkout.resolve()),
               'LMS_CANARY_URL': args.lms_url.rstrip('/'), 'LMS_CANARY_SESSION': cookie}
        browser = subprocess.run(['node', str(ROOT/'scripts/lms-browser-trace-canary.mjs')],
                                 env=env, text=True, capture_output=True, timeout=100)
        if browser.returncode:
            raise RuntimeError('Browser canary failed: ' + browser.stderr[-2500:])
        observation = json.loads(browser.stdout)
        trace_id = observation['pageTrace'].split('-')[1]
        if observation['apiContext'].split('-')[1] != trace_id:
            raise ValueError('Browser and backend trace IDs differ')
        trace = None
        # Existing tail sampler waits 30 seconds; backend visibility is eventual.
        for attempt in range(36):
            try:
                trace = get_json(args.grafana_url + '/api/datasources/proxy/uid/tempo/api/traces/' + trace_id)
                if summarize_trace(trace):
                    break
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
            time.sleep(5)
        if trace is None:
            raise ValueError('Production Tempo did not receive the browser trace')
        records = summarize_trace(trace)
        page = next(s for s in records if s['name']=='browser.page')
        api_id = observation['apiContext'].split('-')[2]
        server = next(s for s in records if s['id']==api_id)
        # Production Traefik adds GET + ReverseProxy between browser and LMS.
        # Verify the ancestry rather than incorrectly requiring a direct edge.
        by_id = {s['id']: s for s in records}
        api = server
        seen = set()
        proxy_names = []
        while api['name'] != 'browser.api':
            if api['id'] in seen or api['parent'] not in by_id:
                raise ValueError('Waterfall parent relationships are broken')
            seen.add(api['id'])
            api = by_id[api['parent']]
            if api['name'] != 'browser.api':
                proxy_names.append(api['name'])
        if api['parent'] != page['id']:
            raise ValueError('Browser API span is not a child of the page')
        names = {s['name'] for s in records}
        if not {'content.read_render', 'db.connect', 'db.transaction'} <= names:
            raise ValueError('Real backend operation spans missing')
        query = '{k8s_namespace_name="lms"} |= "' + trace_id + '"'
        logs = get_json(args.grafana_url + '/api/datasources/proxy/uid/loki/loki/api/v1/query_range?' +
                        urllib.parse.urlencode({'query': query, 'limit': 20, 'since': '15m'}))
        count = sum(len(stream['values']) for stream in logs['data']['result'])
        if count < 2:
            raise ValueError('Correlated real LMS Loki log lines missing')
        dashboard = get_json(args.grafana_url + '/api/dashboards/uid/lms-performance')
        if dashboard['dashboard']['uid'] != 'lms-performance':
            raise ValueError('Dashboard not provisioned')
        dashboard_url = args.grafana_url + dashboard['meta']['url'] + '?var-trace_id=' + trace_id
        ui_env = {**os.environ, 'LMS_CHECKOUT': str(args.lms_checkout.resolve()),
                  'LMS_DASHBOARD_URL': dashboard_url, 'LMS_TRACE_ID': trace_id, 'LMS_SPAN_COUNT': str(len(records))}
        ui = subprocess.run(['node', str(ROOT/'scripts/lms-grafana-canary.mjs')],
                            env=ui_env, text=True, capture_output=True, timeout=150)
        if ui.returncode:
            raise RuntimeError('Live Grafana browser verification failed: ' + ui.stderr[-2500:])
        ui_proof = json.loads(ui.stdout)
        loki = get_json(args.grafana_url + '/api/datasources/uid/loki')
        derived = loki.get('jsonData', {}).get('derivedFields', [])
        link_verified = any(field.get('name')=='TraceID' and field.get('datasourceUid')=='tempo'
                            and field.get('url')=='${__value.raw}' for field in derived)
        if not link_verified:
            raise ValueError('Loki-to-Tempo derived link not provisioned')
        report = {'verifiedAt': datetime.now(timezone.utc).isoformat(), 'success': True,
                  'traceId': trace_id, 'browser': observation, 'spanCount': len(records),
                  'operationNames': sorted(names), 'waterfallParentIdsVerified': True, 'intermediateProxySpans': proxy_names,
                  'spanTimingsNonnegative': all(s['durationMs'] >= 0 for s in records),
                  'correlatedLokiLines': count,
                  'dashboardUrl': dashboard_url, 'dashboardBrowser': ui_proof, 'lokiToTempoLinkVerified': link_verified,
                  'productionMtlsDeliveryVerified': True, 'secretsSaved': False,
                  'syntheticProfileDeleted': False, 'authentikLoginTested': False}
    finally:
        cleanup = kubepython(f'''
from app.config import Settings
from app.store import Store
import json
store=Store(Settings.from_env().database_url)
with store.connect() as db:
    db.execute('DELETE FROM users WHERE issuer=%s AND subject=%s', ({issuer!r}, {subject!r}))
    count=db.execute('SELECT count(*) AS n FROM users WHERE issuer=%s AND subject=%s', ({issuer!r}, {subject!r})).fetchone()['n']
print(json.dumps(dict(deleted=count==0)))
''')
        if not cleanup['deleted']:
            raise RuntimeError('Canary profile cleanup failed')
    report['syntheticProfileDeleted'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--create-canary-session', action='store_true')
    parser.add_argument('--lms-checkout', type=Path, default=ROOT.parent/'lms')
    parser.add_argument('--lms-url', default='https://lms.alchemmist.xyz')
    parser.add_argument('--grafana-url', default='https://grafana.socrat.alchemmist.xyz')
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
