#!/usr/bin/env python3
"""Explicit operator bootstrap of OpenHands' native settings; never prints secrets.

Requires kubectl access. Creates a distinct LiteLLM venice-deepseek-only virtual
key, NOT a personal Pi key. Uses the already running native settings API; model
credentials and policy are persisted by OpenHands, not a custom runtime service.
"""
import base64
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


def kube_secret(ns, name):
    return json.loads(subprocess.check_output(['kubectl', '-n', ns, 'get', 'secret', name, '-o', 'json'], stderr=subprocess.DEVNULL))


def main():
    current = kube_secret('openhands', 'openhands-model')
    if current['metadata'].get('annotations', {}).get('homelab/key-alias') != 'openhands-monori':
        master = base64.b64decode(kube_secret('llm', 'litellm-env')['data']['LITELLM_MASTER_KEY']).decode().strip()
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
        forward = subprocess.Popen(['kubectl', '-n', 'llm', 'port-forward', 'svc/litellm', f'{port}:4000'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        created = None
        try:
            for _ in range(40):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=1): break
                except OSError: time.sleep(.25)
            headers = {'Authorization': 'Bearer ' + master, 'Content-Type': 'application/json'}
            request = urllib.request.Request(f'http://127.0.0.1:{port}/key/generate', headers=headers,
                data=json.dumps({'key_alias':'openhands-monori','models':['venice-deepseek'],'max_parallel_requests':1,
                                 'metadata':{'purpose':'owner-approved OpenHands; no paid fallback'}}).encode())
            created = json.load(urllib.request.urlopen(request, timeout=30))['key']
            payload = {'apiVersion':'v1','kind':'Secret','metadata':{'name':'openhands-model','namespace':'openhands',
                'annotations':{'homelab/key-alias':'openhands-monori'}},'type':'Opaque',
                'data':{'api-key':base64.b64encode(created.encode()).decode()}}
            subprocess.run(['kubectl','apply','-f','-'],input=json.dumps(payload),text=True,check=True,stdout=subprocess.DEVNULL)
        except Exception:
            if created:
                request = urllib.request.Request(f'http://127.0.0.1:{port}/key/delete',headers=headers,data=json.dumps({'keys':[created]}).encode())
                urllib.request.urlopen(request,timeout=30).close()
            raise RuntimeError('Scoped model provisioning failed; values withheld') from None
        finally:
            forward.terminate(); forward.wait(timeout=10)
    key = base64.b64decode(kube_secret('openhands','openhands-model')['data']['api-key']).decode()
    policy = Path(__file__).resolve().parents[1].joinpath('services/openhands/READY_TO_REVIEW.md').read_text()
    settings = {'agent_settings_diff':{'agent_kind':'openhands','llm':{
        'model':'openai/venice-deepseek','base_url':'http://litellm.llm.svc.cluster.local:4000/v1',
        'api_key':key,'api_mode':'chat','native_tool_calling':True,
        'max_input_tokens':30000,'max_output_tokens':4096,'num_retries':0,'timeout':900,
        'reasoning_effort':None,'enable_encrypted_reasoning':False,'caching_prompt':False,
        'prompt_cache_retention':None,'input_cost_per_token':0,'output_cost_per_token':0},
        'agent_context':{'system_message_suffix':policy},
        'condenser':{'max_size':40,'max_tokens':20000}},
        'conversation_settings_diff':{'max_iterations':200}}
    # Input travels on a private exec stream, not argv, logs, chat or Git.
    code = '''import json,sys,pathlib,urllib.request
settings=json.load(sys.stdin)
key=pathlib.Path('/home/openhands/.openhands/agent-canvas/api-key.txt').read_text().strip()
r=urllib.request.Request('http://127.0.0.1:8000/api/settings',method='PATCH',data=json.dumps(settings).encode(),headers={'X-Session-API-Key':key,'Content-Type':'application/json'})
with urllib.request.urlopen(r,timeout=30) as response:
 d=json.load(response);print('Native settings configured; model:',d['agent_settings']['llm']['model'],'key_set:',d['llm_api_key_is_set'])
'''
    subprocess.run(['kubectl','-n','openhands','exec','-i','openhands-0','--','python','-c',code],input=json.dumps(settings),text=True,check=True)


if __name__ == '__main__':
    main()
