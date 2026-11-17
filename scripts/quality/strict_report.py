"""Write the private full-tree strict report. Does not fix source or run tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from common import ROOT, command, failure, owned, report, tracked, use_project_tools
from strict_guard import partition, suppression_hits, verify_configuration

PRIVATE = Path.home() / "Library/Application Support/homelab/quality-strict"
TOOLS = [
    "python",
    "yaml",
    "shell",
    "workflow",
    "secrets",
    "docker",
    "javascript",
    "ansible",
    "dependencies",
]


def write_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o600)


def summarize(tool, payload):
    by_rule = {}
    by_partition = {}
    by_rule_partition = {}
    rows = []
    for item in payload.get("findings", []):
        rule = item["ruleId"]
        path = item["location"]["path"]
        part = partition(path)
        by_rule[rule] = by_rule.get(rule, 0) + 1
        by_partition[part] = by_partition.get(part, 0) + 1
        by_rule_partition.setdefault(rule, {})
        by_rule_partition[rule][part] = by_rule_partition[rule].get(part, 0) + 1
        rows.append(
            {
                "rule": rule,
                "path": path,
                "line": item["location"]["startLine"],
                "partition": part,
                "message": item["message"][:300],
            }
        )
    files = "0"
    for metric in payload.get("metrics", []):
        if metric["label"] == "Files / targets checked":
            files = metric["value"]
    return {
        "files": files,
        "status": payload.get("status"),
        "failureKind": payload.get("failureKind"),
        "blocking": len(payload.get("findings", [])),
        "byRule": dict(sorted(by_rule.items())),
        "byPartition": dict(sorted(by_partition.items())),
        "byRuleAndPartition": {
            rule: dict(sorted(parts.items())) for rule, parts in sorted(by_rule_partition.items())
        },
    }, rows


def run_tool(name):
    import lint

    findings, count = lint.check(name)
    output = ROOT / "reports" / f"{name}.json"
    report(name, findings, count, output)
    return json.loads(output.read_text())


def run_manifests():
    import charts

    findings, count, _inventory = charts.check(validate=True)
    output = ROOT / "reports/manifests.json"
    report("manifests", findings, count, output)
    return json.loads(output.read_text())


def suppression_payload(hits):
    from common import finding

    findings = []
    for hit in hits:
        path, line = hit.rsplit(":", 1)
        findings.append(
            finding(
                "inline-suppression",
                path,
                int(line),
                "Inline suppression is a blocking finding and does not waive the underlying rule.",
                hit,
            )
        )
    return {
        "reportVersion": 0,
        "status": "failed" if findings else "passed",
        "failureKind": "quality" if findings else None,
        "metrics": [{"label": "Files / targets checked", "value": str(len(hits))}],
        "findings": findings,
    }


def audit_exit_code(*, configuration_ready: bool, source_clean: bool) -> int:
    """Distinguish clean source, quality failures, and incomplete configuration."""
    if not configuration_ready:
        return 2
    return 0 if source_clean else 1


def main():
    use_project_tools()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    PRIVATE.chmod(0o700)
    summary = {
        "head": command(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "branch": command(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip(),
        "tools": {},
        "blockers": [],
        "sourceClean": False,
        "pendingPartitions": ["scripts", "tests", "ansible", "manifests", "workflows"],
    }
    try:
        verify_configuration()
    except Exception as error:
        summary["blockers"].append({"tool": "configuration", "error": type(error).__name__})
        summary["tools"]["configuration"] = {
            "status": "failed",
            "failureKind": "command",
            "blocking": None,
        }
        print(f"configuration: {type(error).__name__}: {error}", file=sys.stderr)
    hits = suppression_hits(owned(tracked()))
    stats, rows = summarize("suppressions", suppression_payload(hits))
    summary["tools"]["suppressions"] = stats
    write_private(
        PRIVATE / "suppressions.jsonl",
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
    )
    print(
        f"suppressions: status={stats['status']} blocking={stats['blocking']} "
        f"partitions={stats['byPartition']}"
    )
    runners = [(name, run_tool) for name in TOOLS]
    runners.append(("manifests", None))
    for name, runner in runners:
        try:
            payload = run_manifests() if name == "manifests" else runner(name)
        except Exception as error:
            failure(ROOT / "reports" / f"{name}.json", error)
            summary["blockers"].append({"tool": name, "error": type(error).__name__})
            summary["tools"][name] = {
                "status": "failed",
                "failureKind": "command",
                "blocking": None,
            }
            print(f"{name}: {type(error).__name__}; report blocked", file=sys.stderr)
            continue
        stats, rows = summarize(name, payload)
        summary["tools"][name] = stats
        write_private(
            PRIVATE / f"{name}.jsonl",
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        )
        print(
            f"{name}: status={stats['status']} blocking={stats['blocking']} "
            f"partitions={stats['byPartition']}"
        )
    ready = not summary["blockers"] and all(
        item.get("failureKind") != "command" for item in summary["tools"].values()
    )
    summary["configurationReady"] = ready
    summary["sourceClean"] = ready and all(
        (item.get("blocking") or 0) == 0 for item in summary["tools"].values()
    )
    write_private(PRIVATE / "summary.json", json.dumps(summary, indent=2) + "\n")
    print(f"configurationReady={str(ready).lower()}")
    print(f"sourceClean={str(summary['sourceClean']).lower()}")
    return audit_exit_code(configuration_ready=ready, source_clean=summary["sourceClean"])


if __name__ == "__main__":
    raise SystemExit(main())
