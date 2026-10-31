"""Deterministic boundary around an untrusted model. No credentials required."""
from __future__ import annotations
import datetime as dt
import json
import re

REPO = 'alchemmist/blog'
UPDATES = 'site/content/updates.md'
MAX_FILES = 200
MAX_INPUT_BYTES = 120_000
MAX_ENTRIES = 5

class UnsafeInput(ValueError):
    pass

def validate_event(event):
    if event.get('repository', {}).get('full_name') != REPO:
        raise UnsafeInput('Unexpected repository')
    if event.get('ref') != 'refs/heads/main' or event.get('deleted'):
        return False
    for key in ('before', 'after'):
        if not re.fullmatch(r'[0-9a-f]{40}', event.get(key, '')):
            raise UnsafeInput('Invalid commit SHA')
        if event[key] == '0' * 40:
            raise UnsafeInput('Branch creation/deletion needs manual review')
    return True

def prepare(compare, updates):
    files = compare.get('files', [])
    if not files or len(files) > MAX_FILES:
        raise UnsafeInput('Missing or oversized file list; do not silently truncate')
    # Github compare is limited to 300 files. Lower limit makes truncation fail closed.
    relevant = [f for f in files if f['filename'] != UPDATES and not
                f['filename'].startswith(('.github/', 'remark42/'))]
    if not relevant:
        return None
    candidates = []
    for f in relevant:
        name = f['filename']
        if f.get('status') in ('removed', 'renamed'):
            # Removals/renames still matter to the model, but are not new publications.
            pass
        binary_asset = name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.woff', '.woff2', '.mp4', '.pdf'))
        if 'patch' not in f and f.get('changes', 0) and not binary_asset:
            raise UnsafeInput('Missing text diff: ' + name)
        if binary_asset:
            candidates.append({'filename': name, 'status': f.get('status'), 'binary_asset': True})
            continue
        candidates.append({k: f[k] for k in
                           ('filename', 'previous_filename', 'status', 'additions', 'deletions', 'patch') if k in f})
    context = {'files': candidates, 'recent_updates': updates,
               'commits': [{'sha': c['sha'], 'message': c.get('commit', {}).get('message', '')}
                           for c in compare.get('commits', [])]}
    if len(json.dumps(context, ensure_ascii=False).encode()) > MAX_INPUT_BYTES:
        raise UnsafeInput('Analysis exceeds budget; manual review required')
    return context

def validate_decision(raw, context):
    """Model chooses a description, never a path to write or arbitrary Markdown."""
    if set(raw) != {'should_update', 'reason', 'entries'}:
        raise UnsafeInput('Unexpected model schema')
    if type(raw['should_update']) is not bool or not isinstance(raw['reason'], str):
        raise UnsafeInput('Invalid decision types')
    entries = raw['entries']
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise UnsafeInput('Invalid entries')
    if bool(entries) != raw['should_update']:
        raise UnsafeInput('Inconsistent decision')
    paths = {f['filename'] for f in context['files']}
    for entry in entries:
        if set(entry) != {'text', 'source_paths'}:
            raise UnsafeInput('Invalid entry schema')
        text = entry['text']
        if not isinstance(text, str) or not 1 <= len(text) <= 240:
            raise UnsafeInput('Invalid entry length')
        # All formatting is performed by code. No links supplied by model.
        if any(c in text for c in '\n\r<>[]`\\') or re.search(r'https?://', text):
            raise UnsafeInput('Unsafe Markdown')
        sources = entry['source_paths']
        if not isinstance(sources, list) or not sources or not all(isinstance(p, str) and p in paths for p in sources):
            raise UnsafeInput('Unsubstantiated entry')
    return raw

def render(updates, entries, timestamp):
    if not updates.startswith('---\n'):
        raise UnsafeInput('Missing front matter')
    end = updates.find('\n---\n', 4)
    if end == -1:
        raise UnsafeInput('Unterminated front matter')
    stamp = dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise UnsafeInput('Timestamp must include timezone')
    stamp = stamp.astimezone(dt.timezone(dt.timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')
    lines = [f'- [ ] *\\[{stamp}\\]* {e["text"]}' for e in entries]
    # Prevent exact duplicate descriptions, including manually added ones.
    existing = {re.sub(r'^- \[[ x]\] \*\\\[.*?\\\]\*\s*', '', l).strip()
                for l in updates.splitlines()}
    lines = [l for l, e in zip(lines, entries) if e['text'].strip() not in existing]
    if not lines:
        return updates
    offset = end + len('\n---\n')
    return updates[:offset] + '\n'.join(lines) + '\n' + updates[offset:]
