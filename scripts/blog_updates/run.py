#!/usr/bin/env python3
"""Analyze a GitHub push. Defaults to dry run; --write is explicit."""
import argparse
import os
import json
from pathlib import Path
import urllib.request
from engine import prepare, validate_decision, validate_event, render
from github import GitHub

def run(event, github, llm_url, llm_key, write=False):
    if not validate_event(event):
        return {'status': 'ignored'}
    compare = github.compare(event['before'], event['after'])
    updates, _ = github.read_updates(event['after'])
    context = prepare(compare, updates)
    if context is None:
        return {'status': 'ignored'}
    prompt = Path(os.environ.get('PROMPT_FILE', str(Path(__file__).absolute().parents[2] / 'docs/n8n/blog-updates/prompt.md'))).read_text()
    req = urllib.request.Request(llm_url.rstrip('/') + '/chat/completions',
        data=json.dumps({'model': 'qwen3.8-27b', 'temperature': 0.1, 'max_tokens': 1500,
            'response_format': {'type': 'json_object'}, 'messages': [
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}]}).encode(),
        headers={'Authorization': 'Bearer ' + llm_key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=240) as response:
        answer = json.load(response)
    decision = validate_decision(json.loads(answer['choices'][0]['message']['content']), context)
    if not decision['should_update']:
        return {'status': 'skipped', 'decision': decision}
    # Use the analyzed head commit's timestamp, never the model's invented date.
    commits = compare.get('commits', [])
    head = next((c for c in commits if c['sha'] == event['after']), None)
    if not head:
        raise ValueError('Missing head commit metadata')
    content = render(updates, decision['entries'], head['commit']['committer']['date'])
    if not write:
        return {'status': 'dry_run', 'decision': decision, 'proposed_updates': content}
    return github.propose(event['after'], content, decision['reason'])

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('event', type=Path)
    p.add_argument('--github-key', type=Path, required=True)
    p.add_argument('--llm-key', type=Path, required=True)
    p.add_argument('--llm-url', required=True)
    p.add_argument('--write', action='store_true')
    a = p.parse_args()
    print(json.dumps(run(json.loads(a.event.read_text()), GitHub(a.github_key.read_text().strip()),
                         a.llm_url, a.llm_key.read_text().strip(), a.write), ensure_ascii=False, indent=2))
