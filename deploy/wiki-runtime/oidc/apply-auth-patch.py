import hashlib,json
from pathlib import Path
path=Path('/app/runtime/auth.py');source=path.read_text()
patch=json.loads(Path('/tmp/auth-edits.json').read_text())
if hashlib.sha256(source.encode()).hexdigest()!=patch['baseSha256']:raise SystemExit('Unexpected base auth module')
lines=source.splitlines(keepends=True)
for edit in sorted(patch['edits'],key=lambda e:e['start'],reverse=True):
    if ''.join(lines[edit['start']:edit['end']])!=edit['old']:raise SystemExit('Unexpected auth patch context')
    lines[edit['start']:edit['end']]=edit['new'].splitlines(keepends=True)
result=''.join(lines)
if hashlib.sha256(result.encode()).hexdigest()!=patch['resultSha256']:raise SystemExit('Patch result differs')
path.write_text(result)
