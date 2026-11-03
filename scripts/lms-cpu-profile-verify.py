#!/usr/bin/env python3
"""Explicit, bounded authenticated traffic; persist only profile summary, not data.

Creates a temporary synthetic teacher, 10 GET/s for 20 seconds, deletes its
session/identity in finally. No real users, grants, submissions or Authentik login.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('trace_verify', ROOT/'scripts/lms-observability-verify.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
PROFILE = 'process_cpu:cpu:nanoseconds:cpu:nanoseconds'


def post(grafana, method, body):
    req = urllib.request.Request(grafana.rstrip('/')+'/api/datasources/proxy/uid/pyroscope/querier.v1.QuerierService/'+method,
        data=json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def run(args):
    if not args.create_canary_session:
        raise ValueError('Explicit --create-canary-session is required')
    issuer, subject = 'urn:homelab:lms-cpu-canary', str(uuid.uuid4())
    result = None
    try:
        session = helper.kubepython(f'''
from app.config import Settings
from app.store import Store, digest
import json, time
store = Store(Settings.from_env().database_url)
cookie = store.create_session({issuer!r}, {subject!r}, 'CPU profile canary', '', role='teacher')
with store.connect() as db:
    db.execute('UPDATE sessions SET expires_at=%s WHERE token_hash=%s', (int(time.time())+300, digest(cookie)))
print(json.dumps(dict(cookie=cookie)))
''')
        url = args.lms_url.rstrip('/')+'/basics/znakomstvo-so-sredoi/textbook/'
        start_ms = int(time.time()*1000)
        stop = time.monotonic()+20
        count = 0
        durations = []
        while time.monotonic()<stop:
            began=time.monotonic()
            req=urllib.request.Request(url, headers={'Cookie':'__Host-lms_session='+session['cookie'], 'User-Agent':'homelab-cpu-profile-canary'})
            with urllib.request.urlopen(req,timeout=10) as response:
                if response.status != 200 or response.geturl()!=url:
                    raise RuntimeError('Canary failed to open real lesson; response suppressed')
                if len(response.read())<1000:
                    raise RuntimeError('Unexpected lesson response')
            durations.append((time.monotonic()-began)*1000)
            count+=1
            time.sleep(max(0,0.1-(time.monotonic()-began)))
        for attempt in range(18):
            end_ms=int(time.time()*1000)
            data=post(args.grafana_url,'SelectMergeStacktraces',{
                'profileTypeID':PROFILE,'labelSelector':'{service_name="lms-backend"}',
                'start':start_ms-20000,'end':end_ms,'maxNodes':8192})
            graph=data.get('flamegraph',{})
            names=graph.get('names',[])
            application=[n for n in names if any(word in n for word in ['read_render','render_navigation','hide_closed_lessons','create_app.<locals>.static'])]
            if int(graph.get('total',0))>0 and application:
                break
            time.sleep(5)
        else:
            raise RuntimeError('No nonzero CPU profile with actual application frames received')
        result={
            'verifiedAt':datetime.now(timezone.utc).isoformat(), 'success':True,
            'service':'lms-backend','profileTypeId':PROFILE,
            'cpuProfileTotalNanoseconds':int(graph['total']),
            'functionCount':len(names),'stackDepth':len(graph.get('levels',[])),
            'applicationFrames':application,'realLessonRequests':count,
            'requestLatencyMedianMs':round(sorted(durations)[len(durations)//2],2),
            'dashboardUrl':args.grafana_url.rstrip('/')+'/d/service-cpu-profiling',
            'selectedIntervalUrl':args.grafana_url.rstrip('/')+'/d/service-cpu-profiling?var-service=lms-backend&from='+str(start_ms-20000)+'&to='+str(end_ms),
            'sampling':'49 Hz GIL-held on-CPU Python stacks',
            'boundedCanary':'20 seconds, at most 10 requests/second, sequential, no retries on HTTP errors',
            'secretsSaved':False,'rawProfilesSaved':False,'authentikLoginTested':False,
        }
    finally:
        # UUID reserved before creation: clean up even after partial creation.
        cleanup=helper.kubepython(f'''
from app.config import Settings
from app.store import Store
import json
store=Store(Settings.from_env().database_url)
with store.connect() as db:
    db.execute('DELETE FROM users WHERE issuer=%s AND subject=%s', ({issuer!r}, {subject!r}))
    remaining=db.execute('SELECT count(*) AS n FROM users WHERE issuer=%s AND subject=%s', ({issuer!r}, {subject!r})).fetchone()['n']
print(json.dumps(dict(deleted=remaining==0)))
''')
        if not cleanup['deleted']:
            raise RuntimeError('Temporary profile identity cleanup failed')
        if result is not None:
            result['syntheticProfileDeleted']=True
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create-canary-session',action='store_true')
    parser.add_argument('--grafana-url',default='https://grafana.socrat.alchemmist.xyz')
    parser.add_argument('--lms-url',default='https://lms.alchemmist.xyz')
    parser.add_argument('--output',type=Path)
    run(parser.parse_args())
