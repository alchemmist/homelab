"""Portable static linters; subprocesses only parse source, never run operational code."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import sys
from urllib.parse import unquote, urlparse

from common import ROOT, command, failure, finding, owned, report, tracked


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
            # Rule IDs are useful; do not echo source snippets or guessed credentials.
            result.append(finding(rule, path, line, f"{rule}: inspect this source location."))
    return result


def nonsecret_tokenizer_option(path, item):
    # DL3064 matches TOKENIZERS as though it were a credential. This exact
    # public runtime option line contains no secret; any edit loses the exception.
    if path != "services/spi-tokenizer/Dockerfile" or item["code"] != "DL3064":
        return False
    line = (ROOT / path).read_text().splitlines()[item["line"] - 1]
    return line == "ENV TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1 PYTHONPATH=/app"


def check(tool):
    names = owned(tracked())
    if tool == "workflow":
        security, count = check("actions")
        expressions, _ = check("actionlint")
        return security + expressions, count
    if tool == "python":
        files = [p for p in names if p.endswith(".py")]
        data = json.loads(
            command(
                [
                    "ruff",
                    "check",
                    "--config",
                    "quality/ruff.toml",
                    "--output-format",
                    "json",
                    *files,
                ],
                allowed=(0, 1),
            ).stdout
        )
        result = [
            finding(i["code"], i["filename"], i["location"]["row"], i["message"]) for i in data
        ]
        # Formatting is strict for the maintained CI implementation, not mass
        # rewriting unrelated operational files to appease a new formatter.
        for path in files:
            if (
                path.startswith(("scripts/quality/", "tests/kubernetes/"))
                or path == "tests/test_quality_system.py"
            ):
                formatted = command(
                    ["ruff", "format", "--check", "--config", "quality/ruff.toml", path],
                    allowed=(0, 1),
                )
                if formatted.returncode:
                    result.append(
                        finding("ci-format", path, 1, "CI implementation needs Ruff formatting")
                    )
        return result, len(files)
    if tool == "yaml":
        from yamllint import linter
        from yamllint.config import YamlLintConfig

        config = YamlLintConfig(file=str(ROOT / "quality/yamllint.yaml"))
        files = [p for p in names if p.endswith((".yml", ".yaml")) and "/templates/" not in p]
        result = []
        for path in files:
            for i in linter.run((ROOT / path).read_text(), config, filepath=path):
                result.append(
                    finding(
                        "yaml-" + (i.rule or "syntax"),
                        path,
                        i.line,
                        "YAML " + (i.rule or "syntax") + ": " + i.desc,
                    )
                )
        return result, len(files)
    if tool == "shell":
        files = [p for p in names if p.endswith(".sh")]
        data = json.loads(
            command(["shellcheck", "--norc", "--format=json", *files], allowed=(0, 1)).stdout
        )
        return [
            finding("SC" + str(i["code"]), i["file"], i["line"], i["message"]) for i in data
        ], len(files)
    if tool == "actions":
        return sarif(
            json.loads(
                command(
                    ["zizmor", "--offline", "--format", "sarif", ".github/workflows"],
                    allowed=(0, 1),
                ).stdout
            ),
            ".github/workflows",
        ), 5
    if tool == "actionlint":
        process = command(
            ["actionlint", "-shellcheck=", "-pyflakes=", "-format", "{{json .}}"],
            allowed=(0, 1),
        )
        result = []
        for i in json.loads(process.stdout):
            result.append(finding(i["kind"], i["filepath"], i["line"], i["message"]))
        return result, len([p for p in names if p.startswith(".github/workflows/")])
    if tool == "ansible":
        os.environ["ANSIBLE_CONFIG"] = str(ROOT / "ansible/ansible.cfg")
        os.environ["ANSIBLE_COLLECTIONS_PATH"] = str(ROOT / ".quality-tools/collections")
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
                    *[
                        str(ROOT / p)
                        for p in names
                        if p.startswith("ansible/") and p.endswith((".yml", ".yaml"))
                    ],
                ],
                allowed=(0, 2),
            ).stdout
        )
        return sarif(data), len(
            [p for p in names if p.startswith("ansible/") and p.endswith((".yml", ".yaml"))]
        )
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
                finding(i["code"], path, i["line"], i["message"])
                for i in data
                if not nonsecret_tokenizer_option(path, i)
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
                [
                    "pip-audit",
                    "--local",
                    "--format",
                    "json",
                ],
                allowed=(0, 1),
                timeout=180,
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
        # A disposable tracked-file tree avoids scanning .git, .venv and private evidence.
        with tempfile.TemporaryDirectory(prefix="homelab-secret-scan-") as temp:
            stage = Path(temp) / "source"
            for name in tracked():
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
            return result, len(tracked())
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
    parser.add_argument("--record-debt", metavar="REVIEW_REASON")
    parser.add_argument("--review-secret-false-positives", metavar="REVIEW_REASON")
    args = parser.parse_args()
    output = ROOT / f"reports/{args.tool}.json"
    try:
        if args.tool == "secrets" and args.record_debt:
            raise ValueError("Secrets cannot be recorded as technical debt")
        if args.review_secret_false_positives and args.tool != "secrets":
            raise ValueError("Secret exception review is only for the secret scanner")
        findings, count = check(args.tool)
        return report(
            args.tool,
            findings,
            count,
            output,
            record_reason=args.review_secret_false_positives or args.record_debt,
        )
    except Exception as error:
        failure(output, error)
        print(
            f"{args.tool}: {type(error).__name__}; tool failure, NOT an accepted lint result",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
