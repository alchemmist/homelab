"""Run inside Canvas via `kubectl -n openhands exec -i openhands-0 -- python -`.
Creates/activates a dedicated native agent profile; no LLM key or global edit.
"""
import json,pathlib,urllib.request
key=pathlib.Path.home().joinpath('.openhands/agent-canvas/api-key.txt').read_text().strip()
def api(path,body=None,method=None) -> object:
    req=urllib.request.Request('http://127.0.0.1:8000/api/'+path,headers={'X-Session-API-Key':key,'Content-Type':'application/json'},data=None if body is None else json.dumps(body).encode(),method=method)
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
name='socrat-compact-code';profile={'agent_kind':'openhands','llm_profile_ref':'v-deepseek-uc','tools':[{'name':'terminal'},{'name':'file_editor'}],'mcp_server_refs':[],'secret_refs':[],'integration_refs':[],'public_skills':[],'condenser':{'enabled':True,'max_size':32,'max_tokens':9000,'keep_first':1},'system_message_suffix':'Keep tool output short. For Monori issue 509 read /home/openhands/workspace/MONORI_PUBLISHER.md. Do not request tokens or merge. Keep progress in workspace files.'}
if __name__=='__main__':
    profiles_doc: object = api('profiles')
    if not isinstance(profiles_doc, dict):
        reason = "profile list response is not an object"
        raise SystemExit(reason)
    profile_rows = profiles_doc.get('profiles')
    if not isinstance(profile_rows, list) or not all(isinstance(row, dict) for row in profile_rows):
        raise SystemExit('profile list response has invalid entries')
    assert any(p.get('name')==profile['llm_profile_ref'] for p in profile_rows)
    doc: object = api('agent-profiles')
    if not isinstance(doc, dict):
        reason = "agent profile list response is not an object"
        raise SystemExit(reason)
    profiles=doc.get('profiles')
    if not isinstance(profiles, list) or not all(isinstance(row, dict) for row in profiles):
        raise SystemExit('agent profile list response has invalid entries')
    p=next((p for p in profiles if p.get('name')==name),None)
    if p:
        existing_doc: object = api('agent-profiles/'+name)
        if not isinstance(existing_doc, dict):
            reason = "existing agent profile response is not an object"
            raise SystemExit(reason)
        existing=existing_doc.get('profile')
        if not isinstance(existing, dict):
            raise SystemExit('existing agent profile payload is invalid')
        condenser=existing.get('condenser'); tools=existing.get('tools')
        if not isinstance(condenser, dict) or not isinstance(tools, list) or not all(isinstance(t, dict) for t in tools):
            raise SystemExit('existing agent profile fields are invalid')
        assert existing.get('llm_profile_ref')==profile['llm_profile_ref'] and condenser.get('max_tokens')==9000 and [t.get('name') for t in tools]==['terminal','file_editor'], 'Existing compact profile drift'
    else:api('agent-profiles/'+name,profile)
    active_doc: object = api('agent-profiles/'+name)
    if not isinstance(active_doc, dict):
        reason = "agent profile response is not an object"
        raise SystemExit(reason)
    p=active_doc.get('profile')
    if not isinstance(p, dict) or not isinstance(p.get('id'), str):
        raise SystemExit('active agent profile payload is invalid')
    api('agent-profiles/'+p['id']+'/activate',{});print('Active',name,p['id'])
