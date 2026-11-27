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

MYPY_COMPLETE_EXIT_CODES = (0, 1)
MYPY_SYNTAX_EXIT = 2

MYPY_ERROR = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:\d+:)? (?P<level>error|warning): "
    r"(?P<message>.*?)(?:\s+\[(?P<code>[A-Za-z0-9_-]+)\])?$"
)


def parse_mypy(text: str) -> list[Finding]:
    """Turn raw mypy output lines into stable findings, defaulting the rule to mypy."""
    result: list[Finding] = []
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


def mypy_argv(files: list[str]) -> list[str]:
    """Build the reviewed strict-mypy command line for the given files."""
    return [
        "mypy",
        "--config-file",
        "ci/quality/mypy.ini",
        "--no-error-summary",
        "--no-pretty",
        "--no-color-output",
        "--hide-error-context",
        "--show-error-codes",
        "--follow-imports=silent",
        "--no-incremental",
        *files,
    ]


FATAL_OUTPUT_MARKERS = (
    "Duplicate module",
    "Traceback (most recent call last)",
    "INTERNAL ERROR",
)


def mypy_status(parsed: list[Finding], code: int, text: str) -> str:
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
    if code in MYPY_COMPLETE_EXIT_CODES:
        return "complete"
    if code == MYPY_SYNTAX_EXIT and parsed and all(item["ruleId"] == "syntax" for item in parsed):
        return "syntax"
    return "incomplete"


def mypy_invoke(files: list[str], timeout: int) -> tuple[list[Finding], str]:
    """Run mypy once and classify its run as complete, syntax-only, or incomplete."""
    process = command(mypy_argv(files), allowed=(0, 1, 2), timeout=timeout)
    parsed = parse_mypy(process.stdout) + parse_mypy(process.stderr)
    text = process.stdout + "\n" + process.stderr
    return parsed, mypy_status(parsed, process.returncode, text)


def python_syntax_findings(files: list[str]) -> tuple[list[Finding], list[str]]:
    """Real parser failures. They must not abort type-checking of every other file."""
    findings: list[Finding] = []
    clean: list[str] = []
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


def mypy_on(files: list[str], timeout: int) -> list[Finding]:
    """Type-check files, retrying smaller groups instead of keeping a partial report."""
    if not files:
        return []
    parsed, status = mypy_invoke(files, timeout)
    if status == "complete":
        return parsed
    if len(files) == 1:
        if status == "syntax":
            return parsed
        msg = "mypy coverage incomplete"
        raise RuntimeError(msg)
    groups: dict[str, list[str]] = {}
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


def mypy_findings(files: list[str]) -> list[Finding]:
    """Combine syntax findings with a full type-check of every remaining file."""
    syntax, remaining = python_syntax_findings(files)
    syntax_names = {item["location"]["path"] for item in syntax}
    if syntax_names | set(remaining) != set(files) or syntax_names & set(remaining):
        msg = "mypy coverage incomplete"
        raise RuntimeError(msg)
    # Exit 2 is a fatal mypy stop. Retry smaller sets instead of keeping a partial report.
    return syntax + mypy_on(remaining, 2400)


def format_findings(files: list[str]) -> list[Finding]:
    """Report ruff format parse failures and would-reformat files."""
    process = command(
        ["ruff", "format", "--check", "--config", "ci/quality/ruff.toml", *files],
        allowed=(0, 1, 2),
        timeout=300,
    )
    result: list[Finding] = []
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
        msg = "ruff format failed without a file list"
        raise RuntimeError(msg)
    return result


def check_python(names: list[str]) -> tuple[list[Finding], int]:
    """Run the python linter and return findings and target count."""
    files = [p for p in names if p.endswith(".py")]
    process = command(
        [
            "ruff",
            "check",
            "--config",
            "ci/quality/ruff.toml",
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
        msg = "ruff failed"
        raise LintToolError(msg)
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
