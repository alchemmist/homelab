"""Data-only reports, tracked ownership inventory and strict success decisions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]


def use_project_tools():
    """Prefer this worktree's pinned virtualenv and checksum-locked tool binaries."""
    prefix = os.pathsep.join((str(ROOT / ".venv/bin"), str(ROOT / ".quality-tools/bin")))
    current = os.environ.get("PATH", "")
    if current.split(os.pathsep)[:2] != prefix.split(os.pathsep):
        os.environ["PATH"] = prefix + (os.pathsep + current if current else "")


def command(argv, *, stdin=None, allowed=(0,), timeout=120):
    process = subprocess.run(
        argv,
        input=stdin,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=timeout,
        check=False,
    )
    if process.returncode not in allowed:
        # Never publish arbitrary tool stdout/stderr: it can contain Secret values.
        raise RuntimeError(f"{Path(argv[0]).name} failed (exit {process.returncode}); no fallback")
    return process


def tracked():
    names = command(["git", "ls-files", "-z"]).stdout.split("\0")
    result = []
    for name in names:
        if not name:
            continue
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError("Tracked path escapes the repository")
        if path.is_file() and not path.is_symlink():
            result.append(name)
    return sorted(set(result))


def vendor_prefixes():
    vendors = json.loads((ROOT / "deploy/contracts/vendors.json").read_text())
    prefixes = []
    for tree in vendors["trees"]:
        path = str(tree["path"]).strip("/")
        if not path or path == "." or ".." in Path(path).parts:
            raise ValueError("Unsafe vendor path")
        prefixes.append(path + "/")
    return tuple(prefixes)


def owned(names):
    prefixes = vendor_prefixes()
    return [p for p in names if not any(p.startswith(prefix) for prefix in prefixes)]


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def finding(rule, path, line, message, context=None):
    path = Path(path)
    if path.is_absolute():
        path = path.relative_to(ROOT)
    if ".." in path.parts:
        raise ValueError("Unsafe finding path")
    name = path.as_posix()
    if context is None:
        lines = (ROOT / path).read_text().splitlines()
        context = lines[line - 1].strip() if line <= len(lines) else ""
    return {
        "id": digest(f"{rule}\0{name}\0{context}"),
        "ruleId": rule,
        "severity": "error",
        "message": message[:1000],
        "location": {"path": name, "startLine": max(1, line), "endLine": max(1, line)},
    }


def unique(findings):
    # Repeated identical contexts remain separate findings, without line-number identity.
    counts = Counter()
    result = []
    for item in findings:
        item = dict(item)
        base = item["id"]
        counts[base] += 1
        item["id"] = base + f".{counts[base]}"
        result.append(item)
    return result


def historical_debt_count(check):
    path = ROOT / "quality/debt" / f"{check}.json"
    if not path.is_file():
        return 0
    data = json.loads(path.read_text())
    if data.get("acceptance") is not False:
        raise ValueError("Historical debt file is not marked non-accepting")
    return len(data.get("findings", []))


def reviewed_secret_index():
    path = ROOT / "quality/secret-false-positives.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    index = {}
    for item in data["findings"]:
        if item["id"] in index:
            raise ValueError("Duplicate secret false-positive identity")
        index[item["id"]] = item
    return index


def classify(check, findings):
    findings = unique(findings)
    if check != "secrets":
        return findings, []
    index = reviewed_secret_index()
    blocking = []
    reviewed = []
    for item in findings:
        prior = index.get(item["id"])
        if (
            prior
            and prior["path"] == item["location"]["path"]
            and prior["rule"] == item["ruleId"]
        ):
            reviewed.append(item)
        else:
            blocking.append(item)
    return blocking, reviewed


def report(check, findings, files, output, *, record_reason=None):
    if record_reason is not None:
        raise ValueError(
            "Baseline regeneration is forbidden. Historical debt cannot decide success."
        )
    blocking, reviewed = classify(check, findings)
    historical = historical_debt_count(check)
    payload = {
        "reportVersion": 0,
        "status": "failed" if blocking else "passed",
        "metrics": [
            {"label": "Files / targets checked", "value": str(files)},
            {"label": "Blocking findings", "value": str(len(blocking))},
            {"label": "Reviewed non-secret matches", "value": str(len(reviewed))},
            {
                "label": "Historical debt entries ignored for success",
                "value": str(historical),
            },
        ],
        "findings": blocking,
        "notes": [
            "Full-tree check. Historical quality/debt files do not decide success "
            "and cannot be regenerated. Reviewed secret false positives are exact "
            "id/path/rule matches only."
        ],
    }
    if blocking:
        payload["failureKind"] = "quality"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"{check}: {files} targets, {len(blocking)} blocking findings, "
        f"{len(reviewed)} reviewed non-secrets, {historical} historical entries ignored"
    )
    return bool(blocking)


def failure(output, error):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "reportVersion": 0,
                "status": "failed",
                "failureKind": "command",
                "diagnostics": [
                    {
                        "kind": "command",
                        "message": type(error).__name__,
                        "detail": "Quality tool/setup/protocol failed. No debt baseline or approval can hide it.",
                    }
                ],
            }
        )
    )
