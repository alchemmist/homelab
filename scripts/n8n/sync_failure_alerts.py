#!/usr/bin/env python3
"""Bind a native error handler without changing workflow graphs/credentials/state.
No workflow execution, forced retries, SQL writes, credential creation or probes.
"""
import argparse
import copy
import json
from pathlib import Path
from native_api import api
ROOT=Path(__file__).resolve().parents[2]
NAME='Workflow Failure Alerts'
ALERTS_ID='b2TlucyOTiZP9CzN'


def graph(w):
    return {k:w.get(k) for k in ('nodes','connections')}


def guard(w, target):
    if w.get('settings',{}).get('errorWorkflow') not in (None,'',target):
        raise RuntimeError('Existing error handler differs; refusing overwrite')
    published=w.get('activeVersion')
    if w['active'] and (not published or graph(published)!=graph(w)):
        raise RuntimeError('Published graph differs from draft; refusing to publish unrelated changes')


def body(w):
    return {k:copy.deepcopy(w[k]) for k in ('name','nodes','connections','settings')}


def bind(api, before, target):
    # Fresh compare immediately before mutation; API has no documented CAS.
    fresh=api('GET','workflows/'+before['id'])
    for k in ('name','nodes','connections','settings','active','versionId','activeVersionId'):
        if fresh.get(k)!=before.get(k):raise RuntimeError('Concurrent workflow change; stop')
    guard(fresh,target)
    if fresh.get('settings',{}).get('errorWorkflow')==target:return fresh
    request=body(fresh);request['settings']['errorWorkflow']=target
    result=api('PUT','workflows/'+fresh['id'],request)
    check(before,result,target,verify_static=False)
    if before['active'] and result.get('activeVersionId')!=result['versionId']:
        # Reload timer/webhook registration with the identical graph and new settings.
        # No deactivate call, no manual execution; preserve existing active state.
        api('POST','workflows/'+before['id']+'/activate',{'versionId':result['versionId']})
    after=api('GET','workflows/'+before['id']);check(before,after,target)
    if before['active'] and after['activeVersionId']!=result['versionId']:
        raise RuntimeError('New settings version not published; stop')
    return after


def protected_static(w):
    # Native active-workflow updates delete/recreate GitHub subscriptions. Never
    # restore the obsolete signing secret or suppress drift in other node state.
    state=copy.deepcopy(w.get('staticData'))
    if not isinstance(state,dict):return state
    for node in w['nodes']:
        if node.get('type')!='n8n-nodes-base.githubTrigger':continue
        data=state.get('node:'+node['name'])
        if not isinstance(data,dict):continue
        for key in ('webhookId','webhookSecret'):
            if key in data:data[key]='<native-registration>'
    return state


def check(before,after,target,verify_static=True):
    if graph(before)!=graph(after) or before['name']!=after['name'] or before['active']!=after['active']:
        raise RuntimeError('Workflow graph/identity/state drift; stop')
    expected={**before['settings'],'errorWorkflow':target}
    if after['settings']!=expected:raise RuntimeError('Unexpected settings drift; stop')
    # PUT returns an entity whose hook staticData may be transient during native
    # registration. Only authoritative GET readback verifies durable state.
    if verify_static and protected_static(before)!=protected_static(after):
        raise RuntimeError('Protected workflow static data drift; stop')
    for key in ('id','shared','tags','pinData','meta'):
        if key in before and key in after and before[key]!=after[key]:
            raise RuntimeError('Protected workflow field drift; stop')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');args=p.parse_args()
    listing=api('GET','workflows?limit=250')
    if listing.get('nextCursor'):raise RuntimeError('Workflow enumeration incomplete')
    rows=[w for w in listing['data']if not w.get('isArchived')]
    matches=[w for w in rows if w['name']==NAME]
    if len(matches)>1:raise RuntimeError('Ambiguous handler identity')
    target=matches[0]['id']if matches else None
    targets=[api('GET','workflows/'+w['id'])for w in rows if w['id']!=target]
    for w in targets:guard(w,target)
    if not args.apply:
        print(json.dumps({'mode':'plan','workflows':len(targets),'existing_handler':target}));return
    alerts=next(w for w in targets if w['id']==ALERTS_ID)
    delivery=next(n for n in alerts['nodes']if n['name']=='Post Telegram Message')
    template=json.loads((ROOT/'docs/n8n/workflow-failure-alerts.json').read_text())
    template['nodes'][-1]['credentials']=copy.deepcopy(delivery['credentials'])
    if target:
        saved=api('GET','workflows/'+target)
        if (graph(saved)!=graph(template) or saved['name']!=NAME or saved['active']
            or saved['settings'].get('errorWorkflow')
            or any(saved['settings'].get(k)!=v for k,v in template['settings'].items())):
            raise RuntimeError('Handler drift; refusing replacement')
    else:
        saved=api('POST','workflows',body(template));target=saved['id']
        if saved['active'] or saved['settings'].get('errorWorkflow'):
            raise RuntimeError('Handler must have no recursive error target')
    # Error Trigger is called by native error hooks even while handler is inactive.
    # Persist only metadata receipt; never the raw failed-run payload/credential.
    result=[]
    for w in targets:
        a=bind(api,w,target);result.append({'id':a['id'],'active':a['active'],'errorWorkflow':target})
        print(json.dumps({'configured':a['id'],'active':a['active'],'handler':target}),flush=True)
    print(json.dumps({'handler':target,'covered':len(result),'manual_executions':0}))

if __name__=='__main__':main()
