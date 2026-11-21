#!/usr/bin/env python3
"""Operator-only native daily demo schedule, inactive by default. No model calls.

Default lists the matching owned schedule only. --apply configures it INACTIVE.
Uses the image-pinned installed SDK, not a fresh unpinned pip install each run.
Does not alter other schedules; drift, duplicates and active runs block changes.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    desired=json.loads((ROOT/'services/openhands/the-loop-demo/schedule.json').read_text())
    code='''import json,sys,pathlib,urllib.request,importlib.metadata
request=json.load(sys.stdin);desired=request['desired'];key=pathlib.Path('/home/openhands/.openhands/agent-canvas/api-key.txt').read_text().strip()
def api(path,body=None,method=None):
 r=urllib.request.Request('http://127.0.0.1:8000'+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={'X-Session-API-Key':key,'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=60) as response:return json.load(response)
base='/api/automation/v1';profile=api('/api/agent-profiles/socrat-the-loop')['profile']
listing=api(base+'?limit=100');assert listing['total']<=len(listing['automations']), 'Incomplete automation listing'
matches=[x for x in listing['automations'] if x['name']==desired['name']]
assert len(matches)<=1, 'Ambiguous schedule name'
existing=matches[0] if matches else None
if existing:
 assert existing['agent_profile_id']==profile['id'] and existing['description']==desired['description'] and existing['prompt']==desired['prompt'], 'Schedule ownership/config drift; no adoption'
if not request['apply']:
 print(json.dumps({'exists':bool(existing),'id':existing['id'] if existing else None,'state':existing['state'] if existing else None,'would_activate':False}));sys.exit(0)
for package in ['openhands-sdk','openhands-tools','openhands-workspace']:
 assert importlib.metadata.version(package)=='1.62.0', 'Image SDK version drift; review runtime'
body={k:v for k,v in desired.items() if k!='runtime'};body['agent_profile_id']=profile['id']
if existing:
 runs=api(base+'/'+existing['id']+'/runs')['runs'];assert all(x['status'] not in ['PENDING','RUNNING'] for x in runs), 'Active run; do not change execution configuration'
 result=api(base+'/'+existing['id'],{**body,**desired['runtime'],'state':'INACTIVE'},'PATCH')
else:
 result=api(base+'/preset/prompt',body)
 result=api(base+'/'+result['id'],{**desired['runtime'],'state':'INACTIVE'},'PATCH')
assert result['state']=='INACTIVE' and result['setup_script_path'] is None and result['entrypoint']=='python main.py'
print(json.dumps({'id':result['id'],'state':result['state'],'trigger':result['trigger'],'model_calls_started':False}))
'''
    subprocess.run(['kubectl','-n','openhands','exec','-i','openhands-0','--','python','-c',code],input=json.dumps({'desired':desired,'apply':a.apply}),text=True,check=True)


if __name__=='__main__':main()
