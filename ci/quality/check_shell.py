"""Check shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.quality.common import Finding


import json
import re
from pathlib import Path

from ci.quality.closed_root_backend import entries, plain, view, whole
from ci.quality.common import ROOT, command, finding
from ci.quality.lint_support import workflow_script_findings
from ci.quality.runner import run


def shell_targets(names: list[str]) -> list[str]:
    """Execute shell_targets."""
    result: list[str] = []
    for name in names:
        if "/templates/" in name or name.endswith(".j2"):
            continue
        if name.endswith(".sh"):
            result.append(name)
            continue
        if Path(name).suffix:
            continue
        try:
            first = (ROOT / name).read_text(errors="ignore").splitlines()[:1]
        except OSError:
            continue
        if first and first[0].startswith("#!") and re.search(r"(?:bash|dash|ksh|\bsh)\b", first[0]):
            result.append(name)
    return result


def shellcheck_files(files: list[str]) -> list[Finding]:
    """Execute shellcheck_files."""
    if not files:
        return []
    process = command(
        ["shellcheck", "--norc", "--enable=all", "--format=json", *files],
        allowed=(0, 1),
        timeout=180,
    )
    rows = entries(json.loads(process.stdout.strip() or "[]"))
    return [
        finding(
            "SC" + str(view(item)["code"]),
            plain(view(item)["file"]),
            whole(view(item)["line"]),
            plain(view(item)["message"]),
        )
        for item in rows
    ]


def check_shell(names: list[str]) -> tuple[list[Finding], int]:
    """Run the shell linter and return findings and target count."""
    files = shell_targets(names)
    result = shellcheck_files(files)
    result.extend(workflow_script_findings(names, "shell"))
    return result, len(files)


if __name__ == "__main__":
    raise SystemExit(run("shell", check_shell))
