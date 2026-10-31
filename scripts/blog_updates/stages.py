"""Four-node workflow backend: each endpoint performs exactly one semantic stage."""
import json
import os
from pathlib import Path
import urllib.request
from engine import validate_event, prepare, validate_decision, render, UnsafeInput
from github import GitHub

def context_for(event, github):
    if not validate_event(event):
        return None
    comparison = github.compare(event['before'], event['after'])
    updates, _ = github.read_updates(event['after'])
    context = prepare(comparison, updates)
    return (context, comparison, updates) if context else None

def model(system, data):
    req = urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',
        data=json.dumps({'model':'qwen3.8-27b','temperature':0.1,'max_tokens':1500,
                         'response_format':{'type':'json_object'},'messages':[
                             {'role':'system','content':system},
                             {'role':'user','content':json.dumps(data,ensure_ascii=False)}]}).encode(),
        headers={'Authorization':'Bearer '+os.environ['LITELLM_KEY'],'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=240) as r:
        return json.loads(json.load(r)['choices'][0]['message']['content'])

def stage(name, payload, github=None, call_model=None, write=False):
    github = github or GitHub(os.environ['GITHUB_TOKEN'])
    call_model = call_model or model
    event = payload if name == 'validate' else payload['event']
    snapshot = context_for(event, github)
    if snapshot is None:
        return []
    context, comparison, updates = snapshot
    if name == 'validate':
        prompt = Path(os.environ['PROMPT_FILE']).read_text()
        prompt += '\nThis is the VALIDATION stage. Select only worthwhile announcements. Entry text is a concise factual outline for a separate writer, not a final publication. Return the specified JSON schema.'
        decision = validate_decision(call_model(prompt, context), context)
        return [{'event':event,'selection':decision}] if decision['should_update'] else []
    if name == 'generate':
        selection = validate_decision(payload['selection'], context)
        if not selection['should_update']:
            return []
        prompt = Path(os.environ['PROMPT_FILE']).read_text()
        prompt += '\nThis is the GENERATION stage. Write final concise English announcement entries ONLY for the selected changes. Do not add other topics. Keep source_paths within the selected source_paths. Use the specified JSON schema; you may omit an unsupported selected item.'
        decision = validate_decision(call_model(prompt, {'context':context,'selected':selection}),context)
        allowed = {p for e in selection['entries'] for p in e['source_paths']}
        if any(p not in allowed for e in decision['entries'] for p in e['source_paths']):
            raise UnsafeInput('Generation introduced an unselected source')
        return [{'event':event,'decision':decision}] if decision['should_update'] else []
    if name != 'create-pr':
        raise UnsafeInput('Unknown stage')
    decision = validate_decision(payload['decision'],context)
    if not decision['should_update']:
        return []
    head = next((c for c in comparison['commits'] if c['sha']==event['after']),None)
    if not head:
        raise UnsafeInput('Missing head commit')
    content = render(updates,decision['entries'],head['commit']['committer']['date'])
    if content == updates:
        return [{'status':'no_change'}]
    if not write:
        return [{'status':'dry_run','entries':decision['entries'],'reason':decision['reason']}]
    return [github.propose(event['after'],content,decision['reason'])]
