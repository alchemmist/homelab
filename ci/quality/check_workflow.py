"""Check workflow."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tokenize
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from ci.quality.common import Finding

from ci.quality.common import ROOT, command, finding
from ci.quality.lint_support import LintToolError, sarif, shell_dialect, workflow_files
from ci.quality.runner import run


def check_actions(names: list[str]) -> tuple[list[Finding], int]:
    """Run the actions linter and return findings and target count."""
    files = workflow_files(names)
    return sarif(
        json.loads(
            command(
                [
                    "zizmor",
                    "--no-config",
                    "--strict-collection",
                    "--persona",
                    "auditor",
                    "--format",
                    "sarif",
                    *files,
                ],
                allowed=(0, 1),
                timeout=180,
            ).stdout
        ),
        ".github/workflows",
    ), len(files)


def _suppression_offset(source: str, script: yaml.ScalarNode, token: tokenize.TokenInfo) -> int:
    """Offset one noqa comment inside its YAML scalar, folding-aware."""
    if script.style == "|":
        return token.start[0]
    # Folding/quoting can remove physical newlines. If the comment has a
    # unique verbatim spelling inside this scalar, report its source line.
    # Escaped/ambiguous spellings can only be attributed reliably to the
    # scalar as a whole.
    raw = source[script.start_mark.index : script.end_mark.index]
    comment = token.string.rstrip()
    return raw[: raw.index(comment)].count("\n") if raw.count(comment) == 1 else 0


def _fields(node: yaml.Node | None) -> dict[str, yaml.Node]:
    """Flatten one YAML mapping node to its scalar-keyed fields."""
    if not isinstance(node, yaml.MappingNode):
        return {}
    return {key.value: value for key, value in node.value if isinstance(key, yaml.ScalarNode)}


def _shell(node: yaml.Node | None, fallback: str) -> str:
    """Take the scalar string held by a node, or the fallback."""
    return node.value if isinstance(node, yaml.ScalarNode) else fallback


def _default_shell(mapping: dict[str, yaml.Node], fallback: str) -> str:
    """Resolve the inherited defaults.run shell for one mapping."""
    run = _fields(_fields(mapping.get("defaults")).get("run"))
    return _shell(run.get("shell"), fallback)


def python_directive_lines(source: str) -> set[int]:
    """Find noqa comment tokens in Python run steps, not YAML prose or shell data."""
    document = _fields(yaml.compose(source, Loader=yaml.SafeLoader))
    lines = set()
    for job in _fields(document.get("jobs")).values():
        config = _fields(job)
        steps = config.get("steps")
        if not isinstance(steps, yaml.SequenceNode):
            continue
        inherited = _default_shell(config, _default_shell(document, "bash"))
        for step in steps.value:
            values = _fields(step)
            script = values.get("run")
            if (
                not isinstance(script, yaml.ScalarNode)
                or shell_dialect(_shell(values.get("shell"), inherited)) != "python"
            ):
                continue
            for token in tokenize.generate_tokens(io.StringIO(script.value).readline):
                if token.type == tokenize.COMMENT and re.match(
                    r"#\s*noqa(?:\s*:|\s*$)", token.string, re.IGNORECASE
                ):
                    if script.style == "|":
                        offset = token.start[0]
                    else:
                        # Folding/quoting can remove physical newlines. If the
                        # comment has a unique verbatim spelling inside this scalar,
                        # report its source line. Escaped/ambiguous spellings can
                        # only be attributed reliably to the scalar as a whole.
                        raw = source[script.start_mark.index : script.end_mark.index]
                        comment = token.string.rstrip()
                        offset = (
                            raw[: raw.index(comment)].count("\n") if raw.count(comment) == 1 else 0
                        )
                    lines.add(script.start_mark.line + 1 + offset)
    return lines


def workflow_directives(name: str) -> list[Finding]:
    """Reject inline audit waivers without treating shell/YAML data as Python."""
    source = (ROOT / name).read_text()
    lines = python_directive_lines(source)
    for number, line in enumerate(source.splitlines(), 1):
        if re.search(r"#\s*(?:zizmor:\s*ignore|shellcheck\s+disable=)", line, re.IGNORECASE):
            lines.add(number)
    return [
        finding(
            "workflow-suppression",
            name,
            number,
            "Workflow lint suppression is not allowed.",
        )
        for number in sorted(lines)
    ]


def check_actionlint(names: list[str]) -> tuple[list[Finding], int]:
    """Run the actionlint linter and return findings and target count."""
    files = workflow_files(names)
    for helper in ("shellcheck", "pyflakes"):
        if shutil.which(helper) is None:
            msg = f"Missing required actionlint helper: {helper}"
            raise LintToolError(msg)
    process = command(
        ["actionlint", "-config-file", os.devnull, "-format", "{{json .}}", *files],
        allowed=(0, 1),
        timeout=180,
    )
    data = json.loads(process.stdout or "[]")
    result: list[Finding] = [
        finding(item["kind"], item["filepath"], item["line"], item["message"]) for item in data
    ]
    return result, len(files)


def check_workflow(names: list[str]) -> tuple[list[Finding], int]:
    """Combine workflow scanners without dropping inline directives."""
    security, count = check_actions(names)
    expressions, _ = check_actionlint(names)
    directives = [item for name in workflow_files(names) for item in workflow_directives(name)]
    return security + expressions + directives, count


if __name__ == "__main__":
    raise SystemExit(run("workflow", check_workflow))
