"""Trusted publication boundaries. No repository-supplied code is executed here."""
import base64
import gzip
import hashlib
import hmac
import json
import re
from pathlib import PurePosixPath

LANES = {
    "backend": "Find and reproduce a backend correctness bug; add a regression test and a small fix.",
    "frontend": "Find a frontend correctness, accessibility, or UI consistency defect; reproduce with tests/browser and fix narrowly.",
    "security": "Inspect authentication, authorization, input handling and dependencies. Reproduce a security defect ONLY in your isolated local checkout with synthetic fixtures, then fix and test it. Never probe production or third parties.",
    "polish": "Find one concrete small usability or API error-handling inconsistency, demonstrate it and make a minimal tested improvement. No speculative features or wholesale refactors.",
    "tests": "Find a real untested edge case across frontend/backend, reproduce a defect and add regression coverage plus a minimal fix.",
}
MAX_BYTES = 600_000
DEPENDENCY_PATHS = {"web/package.json", "web/package-lock.json"}


def validate_changes(changes):
    if not changes or len(changes) > 20:
        raise ValueError("Expected 1..20 changed files")
    if any(i["path"] in DEPENDENCY_PATHS for i in changes) and not dependency_repair(changes):
        raise ValueError("Dependency files cannot mix with source changes")
    total = 0
    for item in changes:
        path = item["path"]
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts or "\\" in path or str(p) != path:
            raise ValueError("Unsafe path")
        # Do not let an untrusted patch alter CI, release, dependencies, agent instructions or tooling.
        if path not in DEPENDENCY_PATHS and not path.startswith(("server/app/", "server/tests/", "web/src/", "web/tests/", "common/")):
            raise ValueError("Path outside publication allowlist: " + path)
        if any(part.startswith(".") for part in p.parts) or p.name in {"AGENTS.md", "CLAUDE.md"}:
            raise ValueError("Protected path")
        if item.get("mode", "100644") != "100644":
            raise ValueError("Only regular non-executable files")
        data = base64.b64decode(item["content"], validate=True)
        data.decode("utf-8")
        total += len(data)
        if total > (MAX_BYTES if dependency_repair(changes) else 350_000) or b"\x00" in data:
            raise ValueError("Oversize or binary patch")
    if len({item['path'] for item in changes}) != len(changes):
        raise ValueError("Duplicate paths")
    return changes


def encode_result(result, key=None):
    raw = json.dumps(result).encode()
    if len(raw) > 900_000:
        raise ValueError("Result too large")
    payload = base64.b64encode(gzip.compress(raw)).decode()
    if key:
        payload += '.' + hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return "SWE_RESULT:" + payload


def decode_result(log, key=None):
    lines = [line.removeprefix("SWE_RESULT:") for line in log.splitlines() if line.startswith("SWE_RESULT:")]
    if len(lines) != 1:
        raise ValueError("Missing or ambiguous result")
    payload = lines[0]
    if key:
        payload, signature = payload.rsplit('.', 1)
        expected = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('Unauthenticated worker result')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(payload, validate=True))) as f:
        raw = f.read(900_001)
    if len(raw) > 900_000:
        raise ValueError("Result exceeds limit")
    return json.loads(raw)


def dependency_repair(changes):
    return {item['path'] for item in changes} == DEPENDENCY_PATHS


def validate_dependency_update(changes, original):
    if not dependency_repair(changes):
        raise ValueError('Dependency repair must contain exactly manifest and lock, no source changes')
    files = {i['path']: json.loads(base64.b64decode(i['content'])) for i in changes}
    updated = files['web/package.json']
    groups = {'dependencies', 'devDependencies'}
    if {k:v for k,v in original.items() if k not in groups} != {k:v for k,v in updated.items() if k not in groups}:
        raise ValueError('Dependency repair cannot modify scripts, engines, metadata or tooling')
    changed = False
    for group in groups:
        before, after = original.get(group, {}), updated.get(group, {})
        if before.keys() != after.keys():
            raise ValueError('No dependency additions/removals')
        for name, version in after.items():
            if version != before[name]:
                changed = True
                if not isinstance(version, str) or not re.fullmatch(r'[~^]?\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
                    raise ValueError('Only registry semantic version changes')
    if not changed:
        raise ValueError('No dependency version change')
    lock = files['web/package-lock.json']
    if lock.get('lockfileVersion') != 3:
        raise ValueError('Unexpected lockfile format')
    for entry in lock.get('packages', {}).values():
        url = entry.get('resolved', '')
        if url and not url.startswith('https://registry.npmjs.org/'):
            raise ValueError('Nonstandard dependency registry')
    return changes
