"""Write the private full-tree strict report. Does not fix source or run tests."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import uuid
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from ci.quality import charts
from ci.quality.common import (
    ROOT,
    command,
    failure,
    finding,
    owned,
    report,
    tracked,
    use_project_tools,
)
from ci.quality.strict_guard import partition, suppression_hits, verify_configuration

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from ci.quality.common import Finding

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
_MESSAGE_LIMIT = 300


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


class _FindingRow(TypedDict):
    rule: str
    path: str
    line: int
    partition: str
    message: str


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


def _json_object(value: object) -> dict[str, object]:
    """Copy a JSON object without dropping keys or reordering them."""
    if not isinstance(value, dict):
        message = "Expected a JSON object"
        raise TypeError(message)
    parsed: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            message = "JSON object keys must be strings"
            raise TypeError(message)
        parsed[key] = item
    return parsed


def _require_finding(value: object) -> Finding:
    """Return the finding fields the summary reads, leaving the original payload intact."""
    if not isinstance(value, dict):
        message = "Finding must be an object"
        raise TypeError(message)
    identity = value.get("id")
    rule_id = value.get("ruleId")
    severity = value.get("severity")
    text = value.get("message")
    location = value.get("location")
    if (
        not isinstance(identity, str)
        or not isinstance(rule_id, str)
        or not isinstance(severity, str)
        or not isinstance(text, str)
        or not isinstance(location, dict)
    ):
        message = "Finding fields have an unexpected shape"
        raise TypeError(message)
    path = location.get("path")
    start_line = location.get("startLine")
    end_line = location.get("endLine")
    if (
        not isinstance(path, str)
        or not isinstance(start_line, int)
        or isinstance(start_line, bool)
        or not isinstance(end_line, int)
        or isinstance(end_line, bool)
    ):
        message = "Finding location has an unexpected shape"
        raise TypeError(message)
    checked: Finding = {
        "id": identity,
        "ruleId": rule_id,
        "severity": severity,
        "message": text,
        "location": {"path": path, "startLine": start_line, "endLine": end_line},
    }
    return checked


def _string_or_absent(value: object, label: str) -> str | None:
    """Accept a string field or a missing JSON null, and reject other shapes."""
    if value is None or isinstance(value, str):
        return value
    message = label + " must be a string or absent"
    raise TypeError(message)


def _require_partition(part: object) -> str:
    """Validate even a faulty or substituted provider at the runtime boundary."""
    if not isinstance(part, str) or not part:
        message = "Finding partition must be a non-empty string"
        raise TypeError(message)
    return part


def _partition_name(path: str) -> str:
    """Use the shared ownership partition without treating it as acceptance."""
    return _require_partition(partition(path))


def _lint_check_result(findings: object, count: object) -> tuple[list[Finding], int]:
    """Narrow one linter return value to the report writer contract."""
    if not isinstance(count, int) or isinstance(count, bool):
        message = "Linter target count must be an integer"
        raise TypeError(message)
    if not isinstance(findings, list):
        message = "Linter findings must be a list"
        raise TypeError(message)
    return [_require_finding(item) for item in findings], count


def summarize(tool: str, payload: Mapping[str, object]) -> tuple[_ToolStats, list[_FindingRow]]:
    """Partition genuine findings without interpreting collection as acceptance."""
    by_rule: dict[str, int] = {}
    by_partition: dict[str, int] = {}
    by_rule_partition: dict[str, dict[str, int]] = {}
    rows: list[_FindingRow] = []
    raw_findings = payload.get("findings", [])
    if not isinstance(raw_findings, list):
        message = "Report findings must be a list"
        raise TypeError(message)
    for item in raw_findings:
        checked = _require_finding(item)
        rule = checked["ruleId"]
        path = checked["location"]["path"]
        part = _partition_name(path)
        by_rule[rule] = by_rule.get(rule, 0) + 1
        by_partition[part] = by_partition.get(part, 0) + 1
        by_rule_partition.setdefault(rule, {})
        by_rule_partition[rule][part] = by_rule_partition[rule].get(part, 0) + 1
        rows.append(
            {
                "rule": rule,
                "path": path,
                "line": checked["location"]["startLine"],
                "partition": part,
                "message": checked["message"][:_MESSAGE_LIMIT],
            }
        )
    files = "0"
    raw_metrics = payload.get("metrics", [])
    if not isinstance(raw_metrics, list):
        message = "Report metrics must be a list"
        raise TypeError(message)
    for metric in raw_metrics:
        if not isinstance(metric, dict):
            message = "Report metric must be an object"
            raise TypeError(message)
        if metric["label"] != "Files / targets checked":
            continue
        value = metric["value"]
        if not isinstance(value, str):
            message = "Files metric must be a string"
            raise TypeError(message)
        files = value
    stats: _ToolStats = {
        "tool": tool,
        "files": files,
        "status": _string_or_absent(payload.get("status"), "Report status"),
        "failureKind": _string_or_absent(payload.get("failureKind"), "Report failure kind"),
        "blocking": len(raw_findings),
        "byRule": dict(sorted(by_rule.items())),
        "byPartition": dict(sorted(by_partition.items())),
        "byRuleAndPartition": {
            rule: dict(sorted(parts.items())) for rule, parts in sorted(by_rule_partition.items())
        },
    }
    return stats, rows


def run_tool(name: str) -> dict[str, object]:
    """Collect the actual linter result and its native report."""
    use_project_tools()
    module = import_module(f"ci.quality.check_{name}")
    raw_findings, raw_count = getattr(module, f"check_{name}")(owned(tracked()))
    findings, count = _lint_check_result(raw_findings, raw_count)
    output = ROOT / "reports" / f"{name}.json"
    report(name, findings, count, output)
    return _json_object(json.loads(output.read_text()))


def run_manifests() -> dict[str, object]:
    """Render and validate actual chart outputs without a production cluster."""
    raw_findings, raw_count, _inventory = charts.check(validate=True)
    findings, count = _lint_check_result(raw_findings, raw_count)
    output = ROOT / "reports/manifests.json"
    report("manifests", findings, count, output)
    return _json_object(json.loads(output.read_text()))


def _suppression_hit_list(hits: object) -> list[str]:
    """Narrow suppression hits to the path:line strings the payload records."""
    if not isinstance(hits, list):
        message = "Suppression hits must be a list"
        raise TypeError(message)
    typed: list[str] = []
    for hit in hits:
        if not isinstance(hit, str):
            message = "Suppression hit must be a string"
            raise TypeError(message)
        typed.append(hit)
    return typed


def suppression_payload(hits: Collection[str]) -> dict[str, object]:
    """Keep every forbidden suppression visible as a blocking finding."""
    findings: list[Finding] = []
    detail = "Inline suppression is a blocking finding and does not waive the underlying rule."
    for hit in hits:
        path, line = hit.rsplit(":", 1)
        findings.append(
            finding(
                "inline-suppression",
                path,
                int(line),
                detail,
                hit,
            )
        )
    payload: dict[str, object] = {
        "reportVersion": 0,
        "status": "failed" if findings else "passed",
        "failureKind": "quality" if findings else None,
        "metrics": [{"label": "Files / targets checked", "value": str(len(hits))}],
        "findings": findings,
    }
    return payload


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
                hits = _suppression_hit_list(suppression_hits(owned(tracked())))
                payload = suppression_payload(hits)
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
