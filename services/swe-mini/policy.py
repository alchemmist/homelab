"""Trusted publication boundaries. No repository-supplied code is executed here."""
import base64
import gzip
import json
from pathlib import PurePosixPath

LANES = {
    "backend": "Find and reproduce a backend correctness bug; add a regression test and a small fix.",
    "frontend": "Find a frontend correctness, accessibility, or UI consistency defect; reproduce with tests/browser and fix narrowly.",
    "security": "Inspect authentication, authorization, input handling and dependencies. Reproduce a security defect ONLY in your isolated local checkout with synthetic fixtures, then fix and test it. Never probe production or third parties.",
    "polish": "Find one concrete small usability or API error-handling inconsistency, demonstrate it and make a minimal tested improvement. No speculative features or wholesale refactors.",
    "tests": "Find a real untested edge case across frontend/backend, reproduce a defect and add regression coverage plus a minimal fix.",
}
MAX_BYTES = 350_000


def validate_changes(changes):
    if not changes or len(changes) > 20:
        raise ValueError("Expected 1..20 changed files")
    total = 0
    for item in changes:
        path = item["path"]
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts or "\\" in path or str(p) != path:
            raise ValueError("Unsafe path")
        # Do not let an untrusted patch alter CI, release, dependencies, agent instructions or tooling.
        if not path.startswith(("server/app/", "server/tests/", "web/src/", "web/tests/", "common/")):
            raise ValueError("Path outside publication allowlist: " + path)
        if any(part.startswith(".") for part in p.parts) or p.name in {"AGENTS.md", "CLAUDE.md"}:
            raise ValueError("Protected path")
        if item.get("mode", "100644") != "100644":
            raise ValueError("Only regular non-executable files")
        data = base64.b64decode(item["content"], validate=True)
        data.decode("utf-8")
        total += len(data)
        if total > MAX_BYTES or b"\x00" in data:
            raise ValueError("Oversize or binary patch")
    if len({item['path'] for item in changes}) != len(changes):
        raise ValueError("Duplicate paths")
    return changes


def encode_result(result):
    raw = json.dumps(result).encode()
    if len(raw) > 900_000:
        raise ValueError("Result too large")
    return "SWE_RESULT:" + base64.b64encode(gzip.compress(raw)).decode()


def decode_result(log):
    lines = [line.removeprefix("SWE_RESULT:") for line in log.splitlines() if line.startswith("SWE_RESULT:")]
    if len(lines) != 1:
        raise ValueError("Missing or ambiguous result")
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(lines[0], validate=True))) as f:
        raw = f.read(900_001)
    if len(raw) > 900_000:
        raise ValueError("Result exceeds limit")
    return json.loads(raw)
