"""Lint support."""

from __future__ import annotations

import ast
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from ci.quality.common import ROOT, command, finding

GITHUB_EXPR = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


class LintToolError(RuntimeError):
    """Raised when a lint subprocess emits output that cannot be parsed."""


def sarif(data, prefix=""):
    """Execute sarif."""
    result = []
    for run in data["runs"]:
        for item in run.get("results", []):
            location = item.get("locations", [])[0]["physicalLocation"]
            path = unquote(location["artifactLocation"]["uri"])
            if path.startswith("file:"):
                path = urlparse(path).path
            if not Path(path).is_absolute() and not (ROOT / path).is_file():
                path = str(Path(prefix) / path)
            rule = item["ruleId"]
            line = location.get("region", {}).get("startLine", 1)
            result.append(finding(rule, path, line, f"{rule}: inspect this source location."))
    return result


def shell_dialect(spec):
    """Execute shell_dialect."""
    token = spec.split()[0]
    if token in {"bash", "sh", "dash", "ksh"}:
        return token
    if token in {"python", "python3"}:
        return "python"
    return None


def walk_runs(node, shell="bash"):
    """Execute walk_runs."""
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


def workflow_runs(names):
    """Execute workflow_runs."""
    import yaml

    result = []
    for name in names:
        if not name.startswith(".github/") or not name.endswith((".yml", ".yaml")):
            continue
        if "/templates/" in name:
            continue
        try:
            document = yaml.safe_load((ROOT / name).read_text())
        except yaml.YAMLError:
            continue
        for spec, script in walk_runs(document):
            result.append((name, spec, script))
    return result


def workflow_files(names):
    """Execute workflow_files."""
    return [
        p for p in names if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    ]


def workflow_script_findings(names, kind):
    """Execute workflow_script_findings."""
    result = []
    grouped = {"bash": [], "sh": [], "dash": [], "ksh": []}
    with tempfile.TemporaryDirectory(prefix="homelab-shellcheck-") as temp:
        labels = {}
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
            for item in json.loads(process.stdout.strip() or "[]"):
                source = labels.get(
                    str(Path(item["file"]).resolve()),
                    labels.get(item["file"], item["file"]),
                )
                result.append(
                    finding(
                        "SC" + str(item["code"]),
                        source,
                        1,
                        f"Inline workflow script line {item['line']}: {item['message']}",
                        source + "\n" + item["message"],
                    )
                )
    return result
