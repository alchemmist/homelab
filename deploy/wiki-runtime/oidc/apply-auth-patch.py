"""Apply a hash-verified edit patch to the wiki runtime auth module."""
import hashlib, json
from pathlib import Path

path = Path("/app/runtime/auth.py")
source = path.read_text()
patch = json.loads(Path("/tmp/auth-edits.json").read_text())
if hashlib.sha256(source.encode()).hexdigest() != patch["baseSha256"]:
    message = "Unexpected base auth module"
    raise SystemExit(message)
lines = source.splitlines(keepends=True)
for edit in sorted(patch["edits"], key=lambda e: e["start"], reverse=True):
    if "".join(lines[edit["start"] : edit["end"]]) != edit["old"]:
        message = "Unexpected auth patch context"
        raise SystemExit(message)
    lines[edit["start"] : edit["end"]] = edit["new"].splitlines(keepends=True)
result = "".join(lines)
if hashlib.sha256(result.encode()).hexdigest() != patch["resultSha256"]:
    message = "Patch result differs"
    raise SystemExit(message)
path.write_text(result)
