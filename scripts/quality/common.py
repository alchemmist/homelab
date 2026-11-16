"""Data-only reports, tracked ownership inventory and a no-new-debt ratchet."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]


def command(argv, *, stdin=None, allowed=(0,), timeout=120):
    process = subprocess.run(  # noqa: S603 -- fixed tool/test argv, no shell or operational execution
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


def owned(names):
    vendors = json.loads((ROOT / "deploy/contracts/vendors.json").read_text())
    prefixes = [tree["path"] + "/" for tree in vendors["trees"]]
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


def report(check, findings, files, output, *, record_reason=None):
    findings = unique(findings)
    baseline_path = ROOT / (
        "quality/secret-false-positives.json"
        if check == "secrets"
        else f"quality/debt/{check}.json"
    )
    if record_reason is not None:
        import os

        if os.environ.get("CI") or len(record_reason.strip()) < 20:
            raise ValueError("Recording debt requires a review reason and is forbidden in CI")
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "reason": record_reason,
                    "findings": [
                        {
                            "id": f["id"],
                            "path": f["location"]["path"],
                            "rule": f["ruleId"],
                        }
                        for f in findings
                    ],
                },
                indent=2,
            )
            + "\n"
        )
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {"findings": []}
    known = {f["id"] for f in baseline["findings"]}
    if len(known) != len(baseline["findings"]):
        raise ValueError("Duplicate debt identities")
    active = {f["id"] for f in findings}
    new = [f for f in findings if f["id"] not in known]
    payload = {
        "reportVersion": 0,
        "status": "failed" if new else "passed",
        "metrics": [
            {"label": "Files / targets checked", "value": str(files)},
            {"label": "New blocking findings", "value": str(len(new))},
            {
                "label": "Reviewed non-secret matches"
                if check == "secrets"
                else "Known quality debt (NOT fixed)",
                "value": str(len(active & known)),
            },
            {"label": "Resolved debt entries", "value": str(len(known - active))},
        ],
        "findings": new,
        "notes": [
            f"Full-tree check. Reviewed exceptions/debt: {baseline_path.relative_to(ROOT)}. "
            "No automatic repair, suppression or baseline update in CI."
        ],
    }
    if new:
        payload["failureKind"] = "quality"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"{check}: {files} targets, {len(new)} NEW findings, {len(active & known)} known debt")
    return bool(new)


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
