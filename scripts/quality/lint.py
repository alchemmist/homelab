"""Portable static linters; subprocesses only parse source, never run operational code."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import sys
from urllib.parse import unquote, urlparse

from common import ROOT, command, failure, finding, owned, report, tracked, use_project_tools

MYPY_ERROR = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:\d+:)? (?P<level>error|warning): "
    r"(?P<message>.*?)(?:\s+\[(?P<code>[A-Za-z0-9_-]+)\])?$"
)
GITHUB_EXPR = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)


def sarif(data, prefix=""):
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


def nonsecret_tokenizer_option(path, item):
    # DL3064 matches TOKENIZERS as though it were a credential. This exact
    # public runtime option line contains no secret; any edit loses the exception.
    if path != "services/spi-tokenizer/Dockerfile" or item["code"] != "DL3064":
        return False
    line = (ROOT / path).read_text().splitlines()[item["line"] - 1]
    return line == "ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app"


def yaml_targets(names):
    # Helm and Ansible templates are Go/Jinja text, not YAML documents.
    return [
        p
        for p in names
        if p.endswith((".yml", ".yaml")) and "/templates/" not in p and not p.endswith(".j2")
    ]


def shell_targets(names):
    result = []
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


def shell_dialect(spec):
    token = spec.split()[0]
    if token in {"bash", "sh", "dash", "ksh"}:
        return token
    if token in {"python", "python3"}:
        return "python"
    return None


def walk_runs(node, shell="bash"):
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
    return [
        p for p in names if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))
    ]


def parse_mypy(text):
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
    syntax, remaining = python_syntax_findings(files)
    syntax_names = {item["location"]["path"] for item in syntax}
    if syntax_names | set(remaining) != set(files) or syntax_names & set(remaining):
        raise RuntimeError("mypy coverage incomplete")
    # Exit 2 is a fatal mypy stop. Retry smaller sets instead of keeping a partial report.
    return syntax + mypy_on(remaining, 2400)


def format_findings(files):
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


def shellcheck_files(files):
    if not files:
        return []
    process = command(
        ["shellcheck", "--norc", "--enable=all", "--format=json", *files],
        allowed=(0, 1),
        timeout=180,
    )
    data = json.loads(process.stdout.strip() or "[]")
    return [
        finding("SC" + str(item["code"]), item["file"], item["line"], item["message"])
        for item in data
    ]


def workflow_script_findings(names, kind):
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
                    str(Path(item["file"]).resolve()), labels.get(item["file"], item["file"])
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


def check(tool):
    use_project_tools()
    names = owned(tracked())
    if tool == "workflow":
        security, count = check("actions")
        expressions, _ = check("actionlint")
        return security + expressions, count
    if tool == "python":
        files = [p for p in names if p.endswith(".py")]
        process = command(
            ["ruff", "check", "--config", "quality/ruff.toml", "--output-format", "json", *files],
            allowed=(0, 1, 2),
            timeout=300,
        )
        try:
            data = json.loads(process.stdout or "[]")
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, list):
            raise RuntimeError("ruff failed")
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
    if tool == "yaml":
        from yamllint import linter
        from yamllint.config import YamlLintConfig

        config = YamlLintConfig(file=str(ROOT / "quality/yamllint.yaml"))
        files = yaml_targets(names)
        result = []
        for path in files:
            for item in linter.run((ROOT / path).read_text(), config, filepath=path):
                result.append(
                    finding(
                        "yaml-" + (item.rule or "syntax"),
                        path,
                        item.line,
                        "YAML " + (item.rule or "syntax") + ": " + item.desc,
                    )
                )
        return result, len(files)
    if tool == "shell":
        files = shell_targets(names)
        result = shellcheck_files(files)
        result.extend(workflow_script_findings(names, "shell"))
        return result, len(files)
    if tool == "actions":
        files = workflow_files(names)
        return sarif(
            json.loads(
                command(
                    [
                        "zizmor",
                        "--offline",
                        "--persona",
                        "auditor",
                        "--format",
                        "sarif",
                        ".github/workflows",
                    ],
                    allowed=(0, 1),
                    timeout=180,
                ).stdout
            ),
            ".github/workflows",
        ), len(files)
    if tool == "actionlint":
        files = workflow_files(names)
        process = command(
            ["actionlint", "-shellcheck=", "-pyflakes=", "-format", "{{json .}}"],
            allowed=(0, 1),
            timeout=180,
        )
        result = []
        for item in json.loads(process.stdout or "[]"):
            result.append(finding(item["kind"], item["filepath"], item["line"], item["message"]))
        return result, len(files)
    if tool == "ansible":
        os.environ["ANSIBLE_CONFIG"] = str(ROOT / "ansible/ansible.cfg")
        os.environ["ANSIBLE_COLLECTIONS_PATH"] = str(ROOT / ".quality-tools/collections")
        files = [p for p in names if p.startswith("ansible/") and p.endswith((".yml", ".yaml"))]
        data = json.loads(
            command(
                [
                    "ansible-lint",
                    "--offline",
                    "--project-dir",
                    str(ROOT),
                    "--config-file",
                    str(ROOT / "quality/ansible-lint.yaml"),
                    "--format",
                    "sarif",
                    *[str(ROOT / p) for p in files],
                ],
                allowed=(0, 2),
                timeout=1800,
            ).stdout
        )
        return sarif(data), len(files)
    if tool == "docker":
        files = [p for p in names if Path(p).name == "Dockerfile"]
        result = []
        for path in files:
            data = json.loads(
                command(
                    ["hadolint", "--config", "quality/hadolint.yaml", "--format", "json", path],
                    allowed=(0, 1),
                ).stdout
            )
            result.extend(
                finding(item["code"], path, item["line"], item["message"])
                for item in data
                if not nonsecret_tokenizer_option(path, item)
            )
        return result, len(files)
    if tool == "javascript":
        files = [p for p in names if p.endswith(".js")]
        result = []
        for path in files:
            process = command(["node", "--check", path], allowed=(0, 1))
            if process.returncode:
                from common import digest

                result.append(
                    finding(
                        "javascript-syntax",
                        path,
                        1,
                        "JavaScript parser rejected this source; code was not executed.",
                        digest((ROOT / path).read_text()),
                    )
                )
        return result, len(files)
    if tool == "dependencies":
        data = json.loads(
            command(
                ["pip-audit", "--local", "--format", "json"], allowed=(0, 1), timeout=300
            ).stdout
        )
        result = []
        seen = set()
        for item in data["dependencies"]:
            for vuln in item.get("vulns", []):
                identity = (item["name"], vuln["id"])
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(
                    finding(
                        vuln["id"],
                        "uv.lock",
                        1,
                        item["name"] + ": " + vuln["id"],
                        item["name"] + ":" + vuln["id"],
                    )
                )
        return result, len(data["dependencies"])
    if tool == "secrets":
        with tempfile.TemporaryDirectory(prefix="homelab-secret-scan-") as temp:
            stage = Path(temp) / "source"
            tracked_names = tracked()
            for name in tracked_names:
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            out = Path(temp) / "redacted.json"
            command(
                [
                    "gitleaks",
                    "dir",
                    str(stage),
                    "--redact=100",
                    "--no-banner",
                    "--report-format",
                    "json",
                    "--report-path",
                    str(out),
                ],
                allowed=(0, 1),
                timeout=240,
            )
            data = json.loads(out.read_text())
            result = []
            for item in data:
                path = (
                    Path(item["File"]).relative_to(stage)
                    if Path(item["File"]).is_absolute()
                    else Path(item["File"])
                )
                result.append(
                    finding(
                        item["RuleID"],
                        path,
                        item["StartLine"],
                        "Potential secret: inspect privately; do not paste its value into reports.",
                    )
                )
            return result, len(tracked_names)
    raise ValueError("Unknown linter")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tool",
        choices=[
            "workflow",
            "python",
            "yaml",
            "shell",
            "actions",
            "actionlint",
            "ansible",
            "docker",
            "secrets",
            "javascript",
            "dependencies",
        ],
    )
    args = parser.parse_args()
    output = ROOT / f"reports/{args.tool}.json"
    try:
        findings, count = check(args.tool)
        return report(args.tool, findings, count, output)
    except Exception as error:
        failure(output, error)
        print(
            f"{args.tool}: {type(error).__name__}; tool failure, NOT an accepted lint result",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
