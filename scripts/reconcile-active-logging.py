#!/usr/bin/env python3
"""Reconcile metadata receipts with running regular containers / running host units.
Consumes metadata-only snapshots; never reads application logs.
"""
import argparse, collections, importlib.util, json, pathlib
p=argparse.ArgumentParser(); p.add_argument('--pods',required=True); p.add_argument('--metadata',required=True); p.add_argument('--host-prefix',required=True); p.add_argument('--output',required=True); a=p.parse_args()
spec=importlib.util.spec_from_file_location('coverage',pathlib.Path(__file__).with_name('logging-coverage.py')); c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
pods=json.load(open(a.pods)); metadata=json.load(open(a.metadata))
if metadata.get('failedQueries'): raise SystemExit('STOP: incomplete metadata queries')
sources=[]; excluded=collections.Counter()
for pod in pods['items']:
    running={s['name'] for s in pod.get('status',{}).get('containerStatuses',[]) if 'running' in s.get('state',{})}
    job=any(o['kind']=='Job' for o in pod['metadata'].get('ownerReferences',[]))
    for container in pod['spec']['containers']:
        if job or pod.get('status',{}).get('phase')!='Running' or container['name'] not in running:
            excluded['job_or_nonrunning_regular']+=1; continue
        sources.append(dict(kind='container',namespace=pod['metadata']['namespace'],pod=pod['metadata']['name'],container=container['name'],node=pod['spec'].get('nodeName',''),emission='unknown'))
    excluded['init_or_ephemeral']+=len(pod['spec'].get('initContainers',[]))+len(pod['spec'].get('ephemeralContainers',[]))
for n in range(4):
    text=pathlib.Path(a.host_prefix+str(n)+'.txt').read_text(); journal=json.loads(text.split('JOURNAL_COUNTS ',1)[1])
    for line in text.split('JOURNAL_COUNTS',1)[0].splitlines():
        unit=line.split()[0]
        if unit.endswith('.service'): sources.append(dict(kind='host',host=f'socrat-{n}',unit=unit,emission='unknown',journalVisibleCount600=journal.get(unit,0),journalVisibility='unprivileged-not-complete'))
rows=c.assess(sources,metadata['600'],metadata['3600'])
for r in rows:
    r['count600']=sum(v['count'] for v in {json.dumps(p['labels'],sort_keys=True):p for p in metadata['600'] if c.matches(r,p['labels'])}.values())
    r['count3600']=sum(v['count'] for v in {json.dumps(p['labels'],sort_keys=True):p for p in metadata['3600'] if c.matches(r,p['labels'])}.values())
    r['cause']='canonical-receipt' if r['canonical'] else 'legacy-labels' if r['fresh'] else 'hour-receipt-not-fresh' if r['deliveredInHour'] else 'no-receipt-emission-unproven'
    if r['kind']=='container' and r['pod'].startswith('otel-'): r['cause']='agent-self-logs-explicitly-excluded' if not r['fresh'] else r['cause']
    if r['kind']=='host' and r['journalVisibleCount600']>0 and not r['fresh']: r['cause']='journal-emission-without-fresh-matched-receipt-investigate-labels-checkpoint'
result=dict(observedAtUnix=metadata['observedAtUnix'],logBodiesFetchedOrSaved=False,denominator='running regular non-Job containers plus running system services',excluded=dict(excluded),summary=dict(collections.Counter(r['cause'] for r in rows)),sources=rows)
out=pathlib.Path(a.output); out.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
keys=['kind','host','unit','namespace','pod','container','node','count600','count3600','canonical','journalVisibleCount600','cause']
out.with_suffix('.tsv').write_text('\t'.join(keys)+'\n'+''.join('\t'.join(str(r.get(k,'')) for k in keys)+'\n' for r in rows))
print(json.dumps(result['summary']))
