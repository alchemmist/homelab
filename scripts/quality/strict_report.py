"""Write the private full-tree strict report. Does not fix source or run tests."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import TypedDict

import lint
from common import ROOT, command, failure, finding, owned, report, tracked, use_project_tools
from strict_guard import partition, suppression_hits, verify_configuration

import charts

LOGGER = logging.getLogger(__name__)

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


class _ToolStats(TypedDict, total=False):
    tool: str
    files: str
    status: str | None
    failureKind: str | None
    blocking: int | None
    byRule: dict[str, int]
    byPartition: dict[str, int]
    byRuleAndPartition: dict[str, dict[str, int]]


class _AuditSummary(TypedDict):
    head: str
    branch: str
    evidenceDirectory: str
    worktreeCleanAtStart: bool
    worktreeCleanAtEnd: bool
    headAtEnd: str | None
    snapshotStable: bool
    collectionFinished: bool
    configurationReady: bool
    tools: dict[str, _ToolStats]
    blockers: list[dict[str, str]]
    sourceClean: bool
    pendingPartitions: list[str]


def write_private(path: Path, text: str) -> None:
    """Reject symlink destinations; publish atomically from an initially0600file."""
    if path.is_symlink() or path.parent.is_symlink():
        message = "Evidence path must not be a symlink"
        raise ValueError(message)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".strict-evidence-")
    scratch = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        scratch.replace(path)
    finally:
        scratch.unlink(missing_ok=True)


def create_evidence_directory(base: Path, head: str) -> Path:
    """Create an isolated private run; reruns never overwrite prior evidence."""
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head) is None:
        message = "Invalid source commit for evidence directory"
        raise ValueError(message)
    for directory in (base, base / "runs"):
        if directory.is_symlink():
            message = "Evidence directory must not be a symlink"
            raise ValueError(message)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    directory = base / "runs" / (head[:12] + "-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    return directory


def source_snapshot() -> tuple[str, bool]:
    """Record the commit and whether source has any staged/untracked changes."""
    head = command(["git", "rev-parse", "HEAD"]).stdout.strip()
    status = command(["git", "status", "--porcelain=v1", "--untracked-files=normal"]).stdout
    return head, not status


def snapshot_is_stable(start: tuple[str, bool], end: tuple[str, bool]) -> bool:
    """Admit evidence only for the same clean source snapshot at both boundaries."""
    return start[1] and end[1] and start[0] == end[0]


def summarize(tool, payload):
    """Partition genuine findings without interpreting collection as acceptance."""
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
        "tool": tool,
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
    """Collect the actual linter result and its native report."""
    findings, count = lint.check(name)
    output = ROOT / "reports" / f"{name}.json"
    report(name, findings, count, output)
    return json.loads(output.read_text())


def run_manifests():
    """Render and validate actual chart outputs without a production cluster."""
    findings, count, _inventory = charts.check(validate=True)
    output = ROOT / "reports/manifests.json"
    report("manifests", findings, count, output)
    return json.loads(output.read_text())


def suppression_payload(hits):
    """Keep every forbidden suppression visible as a blocking finding."""
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


def main() -> int:
    """Collect a run-bound audit; findings exit1and incomplete evidence exits2."""
    use_project_tools()
    start = source_snapshot()
    run_directory = create_evidence_directory(PRIVATE, start[0])
    summary: _AuditSummary = {
        "head": start[0],
        "evidenceDirectory": str(run_directory),
        "worktreeCleanAtStart": start[1],
        "worktreeCleanAtEnd": False,
        "headAtEnd": None,
        "snapshotStable": False,
        "collectionFinished": False,
        "configurationReady": False,
        "branch": command(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip(),
        "tools": {},
        "blockers": [],
        "sourceClean": False,
        "pendingPartitions": ["scripts", "tests", "ansible", "manifests", "workflows"],
    }
    # Replace the latest index with an explicitly incomplete current run before
    # collection. A crash cannot leave an older clean summary posing as this run.
    write_private(run_directory / "summary.json", json.dumps(summary, indent=2) + "\n")
    write_private(PRIVATE / "summary.json", json.dumps(summary, indent=2) + "\n")
    sys.stdout.write(f"evidenceDirectory={run_directory}\n")
    try:
        verify_configuration()
    except Exception as error:
        summary["blockers"].append({"tool": "configuration", "error": type(error).__name__})
        summary["tools"]["configuration"] = {
            "status": "failed",
            "failureKind": "command",
            "blocking": None,
        }
        # Never log arbitrary exception values: parsers may include source data.
        LOGGER.exception(
            "configuration: %s; report blocked",
            type(error).__name__,
            exc_info=(RuntimeError, RuntimeError(type(error).__name__), None),
        )
    for name in ("suppressions", *TOOLS, "manifests"):
        try:
            if name == "suppressions":
                payload = suppression_payload(suppression_hits(owned(tracked())))
            elif name == "manifests":
                payload = run_manifests()
            else:
                payload = run_tool(name)
        except Exception as error:
            failure(ROOT / "reports" / f"{name}.json", error)
            summary["blockers"].append({"tool": name, "error": type(error).__name__})
            summary["tools"][name] = {
                "status": "failed",
                "failureKind": "command",
                "blocking": None,
            }
            LOGGER.exception(
                "%s: %s; report blocked",
                name,
                type(error).__name__,
                exc_info=(RuntimeError, RuntimeError(type(error).__name__), None),
            )
            continue
        stats, rows = summarize(name, payload)
        summary["tools"][name] = stats
        write_private(
            run_directory / f"{name}.jsonl",
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        )
        write_private(run_directory / f"{name}.report.json", json.dumps(payload, indent=2) + "\n")
        sys.stdout.write(
            f"{name}: status={stats['status']} blocking={stats['blocking']} "
            f"partitions={stats['byPartition']}\n"
        )
    end = source_snapshot()
    summary["worktreeCleanAtEnd"] = end[1]
    summary["headAtEnd"] = end[0]
    summary["snapshotStable"] = snapshot_is_stable(start, end)
    if not summary["snapshotStable"]:
        summary["blockers"].append({"tool": "source-snapshot", "error": "UnstableSourceSnapshot"})
    ready = not summary["blockers"] and all(
        item.get("failureKind") != "command" for item in summary["tools"].values()
    )
    summary["configurationReady"] = ready
    summary["sourceClean"] = ready and all(
        item.get("status") == "passed" and (item.get("blocking") or 0) == 0
        for item in summary["tools"].values()
    )
    summary["collectionFinished"] = True
    write_private(run_directory / "summary.json", json.dumps(summary, indent=2) + "\n")
    write_private(PRIVATE / "summary.json", json.dumps(summary, indent=2) + "\n")
    sys.stdout.write(f"configurationReady={str(ready).lower()}\n")
    sys.stdout.write(f"sourceClean={str(summary['sourceClean']).lower()}\n")
    return audit_exit_code(configuration_ready=ready, source_clean=summary["sourceClean"])


if __name__ == "__main__":
    raise SystemExit(main())
