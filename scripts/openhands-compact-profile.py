"""Run inside Canvas via `kubectl -n openhands exec -i openhands-0 -- python -`.
Creates/activates a dedicated native agent profile; no LLM key or global edit.
"""
import json,pathlib,urllib.request
key=pathlib.Path.home().joinpath('.openhands/agent-canvas/api-key.txt').read_text().strip()
def api(path,body=None,method=None):
    req=urllib.request.Request('http://127.0.0.1:8000/api/'+path,headers={'X-Session-API-Key':key,'Content-Type':'application/json'},data=None if body is None else json.dumps(body).encode(),method=method)
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
name='socrat-compact-code';profile={'agent_kind':'openhands','llm_profile_ref':'v-deepseek-uc','tools':[{'name':'terminal'},{'name':'file_editor'}],'mcp_server_refs':[],'secret_refs':[],'integration_refs':[],'public_skills':[],'condenser':{'enabled':True,'max_size':32,'max_tokens':9000,'keep_first':1},'system_message_suffix':'Keep tool output short. For Monori issue 509 read /home/openhands/workspace/MONORI_PUBLISHER.md. Do not request tokens or merge. Keep progress in workspace files.'}
if __name__=='__main__':
    assert any(p['name']==profile['llm_profile_ref'] for p in api('profiles')['profiles'])
    profiles=api('agent-profiles')['profiles'];p=next((p for p in profiles if p['name']==name),None)
    if p:
        existing=api('agent-profiles/'+name)['profile'];assert existing['llm_profile_ref']==profile['llm_profile_ref'] and existing['condenser']['max_tokens']==9000 and [t['name'] for t in existing['tools']]==['terminal','file_editor'], 'Existing compact profile drift'
    else:api('agent-profiles/'+name,profile)
    p=api('agent-profiles/'+name)['profile'];api('agent-profiles/'+p['id']+'/activate',{});print('Active',name,p['id'])
