"""Lint support for workflow CI scripts and SARIF tool output."""

from __future__ import annotations

import ast
import json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import yaml

from ci.quality.closed_root_backend import entries, plain, view, whole
from ci.quality.common import ROOT, command, finding

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from ci.quality.common import Finding

GITHUB_EXPR = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
SHELL_DIALECTS = ("bash", "sh", "dash", "ksh")


class LintToolError(RuntimeError):
    """Raised when a lint subprocess emits output that cannot be parsed."""


def sarif(data: Mapping[str, object], prefix: str = "") -> list[Finding]:
    """Convert a SARIF tool report into stable findings under the repo root."""
    result: list[Finding] = []
    for raw_run in entries(data["runs"]):
        run = view(raw_run)
        for raw_item in entries(run.get("results", [])):
            item = view(raw_item)
            location = view(view(entries(item["locations"])[0])["physicalLocation"])
            artifact = view(location["artifactLocation"])
            path = unquote(plain(artifact["uri"]))
            if path.startswith("file:"):
                path = urlparse(path).path
            if not Path(path).is_absolute() and not (ROOT / path).is_file():
                path = str(Path(prefix) / path)
            rule = plain(item["ruleId"])
            region = location.get("region")
            line = 1 if region is None else whole(view(region)["startLine"])
            result.append(finding(rule, path, line, f"{rule}: inspect this source location."))
    return result


def shell_dialect(spec: str) -> str | None:
    """Classify a workflow `shell:` spec into a shellcheck dialect or python."""
    token = spec.split(maxsplit=1)[0]
    if token in SHELL_DIALECTS:
        return token
    if token in {"python", "python3"}:
        return "python"
    return None


def walk_runs(node: object, shell: str = "bash") -> Iterator[tuple[str, str]]:
    """Yield every inline `run:` script with the shell dialect declared around it."""
    if isinstance(node, dict):
        current = node["shell"] if isinstance(node.get("shell"), str) else shell
        script = node.get("run")
        if isinstance(script, str) and script.strip():
            yield current, script
        for key, value in node.items():
            if key != "run":
                yield from walk_runs(value, current)
    elif isinstance(node, list):
        for item in node:
            yield from walk_runs(item, shell)


def workflow_runs(names: list[str]) -> list[tuple[str, str, str]]:
    """Collect inline run scripts from active GitHub workflow files."""
    result: list[tuple[str, str, str]] = []
    for name in names:
        if not name.startswith(".github/") or not name.endswith((".yml", ".yaml")):
            continue
        if "/templates/" in name:
            continue
        try:
            document: object = yaml.safe_load((ROOT / name).read_text())
        except yaml.YAMLError:
            continue
        for spec, script in walk_runs(document):
            result.append((name, spec, script))
    return result


def workflow_files(names: list[str]) -> list[str]:
    """List the first-party workflow files among the passed tracked names."""
    return [
        p for p in names if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    ]


def workflow_script_findings(names: list[str], kind: str) -> list[Finding]:
    """Lint inline workflow scripts with their pinned parser (shellcheck or ast)."""
    result: list[Finding] = []
    grouped: dict[str, list[str]] = {dialect: [] for dialect in SHELL_DIALECTS}
    with tempfile.TemporaryDirectory(prefix="homelab-shellcheck-") as temp:
        labels: dict[str, str] = {}
        for name, spec, script in workflow_runs(names):
            dialect = shell_dialect(spec)
            if dialect == "python":
                if kind != "python":
                    continue
                try:
                    ast.parse(script)
                except SyntaxError as error:
                    result.append(
                        finding(
                            "python-syntax",
                            name,
                            error.lineno or 1,
                            "Inline workflow Python was rejected by the parser.",
                            script,
                        )
                    )
                continue
            if kind != "shell":
                continue
            if dialect is None:
                result.append(
                    finding(
                        "workflow-shell-unreviewed",
                        name,
                        1,
                        "Inline workflow script has no pinned parser: " + spec.split()[0],
                        spec + "\n" + script,
                    )
                )
                continue
            sanitized = GITHUB_EXPR.sub("GH_EXPR", script)
            path = Path(temp) / f"script-{len(labels)}.sh"
            path.write_text(sanitized)
            labels[str(path)] = name
            grouped[dialect].append(str(path))
        for dialect, paths in grouped.items():
            if not paths:
                continue
            process = command(
                [
                    "shellcheck",
                    "--norc",
                    "--enable=all",
                    "--shell",
                    dialect,
                    "--format=json",
                    *paths,
                ],
                allowed=(0, 1),
                timeout=180,
            )
            report: object = json.loads(process.stdout.strip() or "[]")
            rows = report if isinstance(report, list) else []
            for raw_report in rows:
                item = view(raw_report)
                source = labels.get(
                    str(Path(plain(item["file"])).resolve()),
                    labels.get(plain(item["file"]), plain(item["file"])),
                )
                result.append(
                    finding(
                        "SC" + str(item["code"]),
                        source,
                        1,
                        f"Inline workflow script line {item['line']}: {item['message']}",
                        source + "\n" + plain(item["message"]),
                    )
                )
    return result
