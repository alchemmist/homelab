"""Check python."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.quality.common import Finding

import ast
import re
from pathlib import Path

from ci.quality.common import ROOT, command, finding
from ci.quality.lint_support import LintToolError, workflow_script_findings
from ci.quality.runner import run

MYPY_ERROR = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:\d+:)? (?P<level>error|warning): "
    r"(?P<message>.*?)(?:\s+\[(?P<code>[A-Za-z0-9_-]+)\])?$"
)


def parse_mypy(text):
    """Execute parse_mypy."""
    result = []
    for line in text.splitlines():
        match = MYPY_ERROR.match(line)
        if not match:
            continue
        result.append(
            finding(
                match.group("code") or "mypy",
                match.group("path"),
                int(match.group("line")),
                match.group("message"),
            )
        )
    return result


def mypy_argv(files):
    """Execute mypy_argv."""
    return [
        "mypy",
        "--config-file",
        "quality/mypy.ini",
        "--no-error-summary",
        "--no-pretty",
        "--no-color-output",
        "--hide-error-context",
        "--show-error-codes",
        "--follow-imports=silent",
        "--no-incremental",
        *files,
    ]


def mypy_status(parsed, code, text):
    """Separate a finished type-check from a fatal run that did not cover its files."""
    if any(
        marker in text
        for marker in (
            "Duplicate module",
            "Traceback (most recent call last)",
            "INTERNAL ERROR",
        )
    ):
        return "incomplete"
    if code in (0, 1):
        return "complete"
    if code == 2 and parsed and all(item["ruleId"] == "syntax" for item in parsed):
        return "syntax"
    return "incomplete"


def mypy_invoke(files, timeout):
    """Execute mypy_invoke."""
    process = command(mypy_argv(files), allowed=(0, 1, 2), timeout=timeout)
    parsed = parse_mypy(process.stdout) + parse_mypy(process.stderr)
    text = process.stdout + "\n" + process.stderr
    return parsed, mypy_status(parsed, process.returncode, text)


def python_syntax_findings(files):
    """Real parser failures. They must not abort type-checking of every other file."""
    findings = []
    clean = []
    for name in files:
        source = (ROOT / name).read_text()
        try:
            ast.parse(source, filename=name)
        except (SyntaxError, ValueError) as error:
            line = error.lineno if isinstance(error, SyntaxError) and error.lineno else 1
            findings.append(
                finding(
                    "python-syntax",
                    name,
                    line,
                    "Python parser rejected this file before type checking.",
                )
            )
        else:
            clean.append(name)
    return findings, clean


def mypy_on(files, timeout):
    """Execute mypy_on."""
    if not files:
        return []
    parsed, status = mypy_invoke(files, timeout)
    if status == "complete":
        return parsed
    if len(files) == 1:
        if status == "syntax":
            return parsed
        raise RuntimeError("mypy coverage incomplete")
    groups = {}
    for name in files:
        groups.setdefault(str(Path(name).parent), []).append(name)
    if len(groups) == 1 or len(groups) == len(files):
        result = []
        for name in files:
            result.extend(mypy_on([name], min(timeout, 180)))
        return result
    result = []
    for group in groups.values():
        result.extend(mypy_on(group, min(timeout, 600)))
    return result


def mypy_findings(files):
    """Execute mypy_findings."""
    syntax, remaining = python_syntax_findings(files)
    syntax_names = {item["location"]["path"] for item in syntax}
    if syntax_names | set(remaining) != set(files) or syntax_names & set(remaining):
        raise RuntimeError("mypy coverage incomplete")
    # Exit 2 is a fatal mypy stop. Retry smaller sets instead of keeping a partial report.
    return syntax + mypy_on(remaining, 2400)


def format_findings(files):
    """Execute format_findings."""
    process = command(
        ["ruff", "format", "--check", "--config", "quality/ruff.toml", *files],
        allowed=(0, 1, 2),
        timeout=300,
    )
    result = []
    for line in process.stderr.splitlines():
        marker = "Failed to parse "
        if marker not in line:
            continue
        detail = line.split(marker, 1)[1]
        path, separator, rest = detail.partition(":")
        line_no, _, message = rest.partition(":")
        if not separator or not line_no.isdigit():
            continue
        result.append(
            finding(
                "ruff-syntax",
                path.strip(),
                int(line_no),
                message.strip() or "Ruff could not parse this file",
            )
        )
    if process.returncode:
        for line in process.stdout.splitlines():
            prefix = "Would reformat: "
            if line.startswith(prefix):
                result.append(
                    finding(
                        "ruff-format",
                        line.removeprefix(prefix).strip(),
                        1,
                        "Ruff format check failed",
                    )
                )
    if process.returncode not in (0, 1) and not result:
        raise RuntimeError("ruff format failed without a file list")
    return result


def check_python(names: list[str]) -> tuple[list[Finding], int]:
    """Run the python linter and return findings and target count."""
    files = [p for p in names if p.endswith(".py")]
    process = command(
        [
            "ruff",
            "check",
            "--config",
            "quality/ruff.toml",
            "--output-format",
            "json",
            *files,
        ],
        allowed=(0, 1, 2),
        timeout=300,
    )
    try:
        data = json.loads(process.stdout or "[]")
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, list):
        raise LintToolError("ruff failed")
    result = [
        finding(
            item.get("code") or "ruff-syntax",
            item["filename"],
            item["location"]["row"],
            item["message"],
        )
        for item in data
    ]
    result.extend(format_findings(files))
    result.extend(mypy_findings(files))
    result.extend(workflow_script_findings(names, "python"))
    return result, len(files)


if __name__ == "__main__":
    raise SystemExit(run("python", check_python))
