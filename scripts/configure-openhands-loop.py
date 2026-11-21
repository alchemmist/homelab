#!/usr/bin/env python3
"""Explicit operator setup of native MCP/profile; no new identity or credentials.

Installs pinned official filesystem MCP from tracked lockfile with lifecycle
scripts/audit disabled into the existing PVC. Native API stores settings/profile.
Does not overwrite demo code/results, create schedules or launch model calls.
"""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEST = "/home/openhands/.openhands/tools/filesystem"
WORKSPACE = "/home/openhands/workspace/the-loop-demo"


def main():
    files = {n:(ROOT/"tools/openhands-mcp"/n).read_text() for n in ["package.json","package-lock.json"]}
    stage = """import pathlib,json,sys
files=json.load(sys.stdin);p=pathlib.Path('/home/openhands/.openhands/tools/filesystem');p.mkdir(parents=True,exist_ok=True)
for n,v in files.items():
 f=p/n
 if f.is_symlink():raise RuntimeError('Unsafe npm manifest path')
 f.write_text(v)
pathlib.Path('/home/openhands/workspace/the-loop-demo').mkdir(parents=True,exist_ok=True)
"""
    subprocess.run(["kubectl","-n","openhands","exec","-i","openhands-0","--","python","-c",stage],input=json.dumps(files),text=True,check=True)
    subprocess.run(["kubectl","-n","openhands","exec","openhands-0","--","npm","ci","--prefix",DEST,"--ignore-scripts","--no-audit","--no-fund"],check=True)
    policy = (ROOT/"services/openhands/READY_TO_REVIEW.md").read_text()+"\n\n"+(ROOT/"services/openhands/THE_LOOP.md").read_text()
    code = """import json,sys,pathlib,urllib.request
policy=json.load(sys.stdin)['policy'];key=pathlib.Path('/home/openhands/.openhands/agent-canvas/api-key.txt').read_text().strip()
def api(path,body=None,method=None):
 r=urllib.request.Request('http://127.0.0.1:8000'+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={'X-Session-API-Key':key,'Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=60) as response:return json.load(response)
server={'command':'node','args':['/home/openhands/.openhands/tools/filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js','/home/openhands/workspace/the-loop-demo']}
test=api('/api/mcp/test',{'name':'socrat-workspace','server':{'type':'stdio',**server},'timeout':20,'tool_call':{'name':'list_allowed_directories','arguments':{}}})
assert test.get('ok') and not test.get('tool_result',{}).get('is_error'), 'MCP tools/list/read check failed'
# Negative check uses a benign file, never a credential filename.
negative=api('/api/mcp/test',{'name':'socrat-workspace','server':{'type':'stdio',**server},'timeout':20,'tool_call':{'name':'read_text_file','arguments':{'path':'/etc/hostname'}}})
assert negative.get('tool_result',{}).get('is_error'), 'MCP directory boundary not enforced'
settings={**server,'transport':'stdio','enabled':True,'description':'Official filesystem MCP2.4.0; only the-loop-demo; no external credentials.'}
current=api('/api/settings')['agent_settings'].get('mcp_config') or {}
# PATCH only this known owned entry; never adopt an unrelated server by name.
if 'socrat-workspace' in current:
 old=current['socrat-workspace']
 assert old.get('command')==server['command'] and old.get('args')==server['args'], 'Owned MCP entry drift; stop'
 api('/api/settings/mcp/socrat-workspace',settings,'PATCH')
else:api('/api/settings/mcp/socrat-workspace',settings)
api('/api/agent-profiles/socrat-the-loop',{'agent_kind':'openhands','llm_profile_ref':'socrat-deepseek','mcp_server_refs':['socrat-workspace'],'secret_refs':[],'integration_refs':[],'system_message_suffix':policy,'condenser':{'max_size':240,'max_tokens':24000}})
p=api('/api/agent-profiles/socrat-the-loop')['profile'];api('/api/agent-profiles/'+p['id']+'/activate',{})
print(json.dumps({'profile':p['name'],'id':p['id'],'mcp_tools':len(test['tools']),'outside_workspace_denied':True}))
"""
    subprocess.run(["kubectl","-n","openhands","exec","-i","openhands-0","--","python","-c",code],input=json.dumps({"policy":policy}),text=True,check=True)


if __name__ == "__main__": main()
