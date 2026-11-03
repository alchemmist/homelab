#!/usr/bin/env python3
"""Provision the inactive silent session-maintenance workflow, never credentials."""
import json
from sync import api, CONFIG, BASE, render_workflow

def main():
    template=json.loads((BASE/'docs/n8n/yandex-session-maintenance.json').read_text())
    creds=json.loads((CONFIG/'calendar-credentials.json').read_text())
    w=render_workflow(template,creds,{})
    matches=[x for x in api('GET','workflows?limit=250')['data']if x['name']==w['name']]
    if len(matches)>1 or (matches and matches[0]['active']):
        raise RuntimeError('Ambiguous or active maintenance workflow; refusing to modify')
    result=api('PUT'if matches else 'POST','workflows/'+matches[0]['id']if matches else 'workflows',w)
    print('Session maintenance workflow:',result['id'],'active:',result.get('active',False))
if __name__=='__main__':main()
