"""Fail closed when strict policy, ownership, or suppression controls drift."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import yaml

from ci.quality.common import (
    ROOT,
    command,
    frozen_source_files,
    owned,
    tracked,
    use_project_tools,
    vendor_prefixes,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


class RuffPolicy(TypedDict):
    """Ruff settings pinned by the strict policy."""

    ignore: list[str]
    perFileIgnores: dict[str, list[str]]


class MypyPolicy(TypedDict):
    """Extra mypy strict flags and required error codes."""

    extra: list[str]
    errorCodes: list[str]


class YamllintPolicy(TypedDict):
    """Yamllint rules the policy disables or configures."""

    disabled: dict[str, object]
    enabled: dict[str, dict[str, object]]


class AnsiblePolicy(TypedDict):
    """Ansible-lint rule partition pinned by the policy."""

    excluded: list[str]
    profileMin: list[str]
    enable: list[str]


class KubeLinterPolicy(TypedDict):
    """kube-linter checks the policy includes and deliberately omits."""

    include: list[str]
    omitted: list[str]


class GeneratedWorkflows(TypedDict):
    """Contract for the quality graph's generated publisher workflow."""

    trusted: bool
    waiver: bool
    blocker: str
    publisher: str
    triggers: dict[str, object]
    topPermissions: dict[str, str]
    jobs: dict[str, dict[str, object]]
    zizmor: list[str]


class StrictPolicy(TypedDict):
    """Keys of ci/quality/strict-policy.json consumed by the strict guard."""

    ruff: RuffPolicy
    mypy: MypyPolicy
    yamllint: YamllintPolicy
    ansible: AnsiblePolicy
    kubeLinter: KubeLinterPolicy
    vendorPaths: list[str]
    reviewedExceptionDigest: str
    generatedWorkflows: GeneratedWorkflows


def marker(*parts: str) -> str:
    """Execute marker."""
    return "".join(parts)


SUPPRESSION = re.compile(
    "|".join(
        [
            r"(?i:#\s*(?:(?:ruff|flake8):\s*)?noqa\b|#\s*ruff:\s*disable\b)",
            r"#\s*" + marker("type:") + r"\s*" + marker("ignore") + r"\b",
            r"#\s*" + marker("pyright:") + r"\s*" + marker("ignore") + r"\b",
            r"#\s*" + marker("no", "sec") + r"\b",
            r"\b" + marker("hadolint") + r"\s+" + marker("ignore") + r"\b",
            marker("kube-linter:") + marker("ignore"),
            marker("ignore-check.") + marker("kube-linter.io"),
            r"\b" + marker("shellcheck") + r"\s+" + marker("disable") + r"\b",
            r"\b" + marker("yamllint") + r"\s+" + marker("disable") + r"\b",
            r"#\s*" + marker("no", "lint") + r"\b",
            marker("ansible-lint:") + r"\s*(?:" + marker("skip") + "|" + marker("disable") + ")",
        ]
    )
)
CODE_SUFFIXES = {".py", ".pyi", ".sh", ".bash", ".yml", ".yaml", ".js", ".ts", ".tsx", ".j2"}


def policy():
    """Execute policy."""
    return json.loads((ROOT / "ci/quality/strict-policy.json").read_text())


def line_is_suppression(line: str) -> bool:
    """Execute line_is_suppression."""
    return bool(SUPPRESSION.search(line))


def suppression_paths(names: Iterable[str]) -> list[str]:
    """Execute suppression_paths."""
    selected = []
    for name in names:
        path = Path(name)
        if path.suffix in CODE_SUFFIXES or path.name.startswith("Dockerfile"):
            selected.append(name)
            continue
        if path.suffix:
            continue
        try:
            first = (ROOT / name).read_text(errors="ignore").splitlines()[:1]
        except OSError:
            continue
        if first and first[0].startswith("#!") and re.search(r"(?:bash|dash|ksh|\bsh)\b", first[0]):
            selected.append(name)
    return selected


def suppression_hits(names: Iterable[str]) -> list[str]:
    """Execute suppression_hits."""
    hits = []
    for name in suppression_paths(names):
        for number, line in enumerate((ROOT / name).read_text(errors="ignore").splitlines(), 1):
            if line_is_suppression(line):
                hits.append(f"{name}:{number}")
    return hits


def partition(path: str) -> str:
    """Execute partition."""
    for prefix in vendor_prefixes():
        if path.startswith(prefix):
            return "vendor"
    if path.startswith("ci/") or path in {"qg.yaml", "pyproject.toml"}:
        return "quality-policy"
    top = path.split("/", 1)[0]
    return {
        "scripts": "scripts",
        "tests": "tests",
        "ansible": "ansible",
        "charts": "manifests",
        "deploy": "manifests",
        "services": "services",
        ".github": "workflows",
    }.get(top, "other-owned")


def discovered_ansible_rules() -> set[str]:
    """Execute discovered_ansible_rules."""
    import ansiblelint

    root = Path(ansiblelint.__file__).parent / "rules"
    found = set()
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "id"
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)
                    ):
                        found.add(stmt.value.value)
    return found


def listed_ansible_rules() -> set[str]:
    """Execute listed_ansible_rules."""
    use_project_tools()
    process = command(
        ["ansible-lint", "-L", "-f", "brief", "--offline", "--nocolor"],
        timeout=180,
    )
    found = set()
    for line in process.stdout.splitlines():
        if line.startswith("- "):
            found.add(line.split()[1])
    if len(found) < 40:
        msg = "ansible-lint rule catalog was not parsed"
        raise ValueError(msg)
    return found


def verify_ruff_policy(data: StrictPolicy) -> None:
    """Fail if ruff config diverges from the strict policy."""
    ruff = tomllib.loads((ROOT / "ci/quality/ruff.toml").read_text())
    lint = ruff.get("lint", {})
    if "exclude" in ruff or "extend-exclude" in ruff or "exclude" in lint:
        msg = "Ruff exclude hides files"
        raise ValueError(msg)
    if lint.get("select") != ["ALL"]:
        msg = "Ruff must select ALL"
        raise ValueError(msg)
    if "extend-ignore" in lint or lint.get("ignore") != data["ruff"]["ignore"]:
        msg = "Ruff ignore list drifted from the strict policy"
        raise ValueError(msg)
    if (
        "extend-per-file-ignores" in lint
        or lint.get("per-file-ignores") != data["ruff"]["perFileIgnores"]
    ):
        msg = "Ruff per-file ignores drifted"
        raise ValueError(msg)


def verify_mypy_policy(data: StrictPolicy) -> None:
    """Fail if mypy strict config or required flags drifted."""
    mypy = (ROOT / "ci/quality/mypy.ini").read_text()
    if (
        "strict = true" not in mypy
        or "disable_error_code" in mypy
        or "ignore_missing_imports" in mypy
    ):
        msg = "mypy strict mode drifted"
        raise ValueError(msg)
    if "follow_imports" in mypy:
        msg = "mypy must not skip imports from the config file"
        raise ValueError(msg)
    for flag in data["mypy"]["extra"]:
        if f"{flag} = true" not in mypy:
            msg = "Missing mypy strict flag"
            raise ValueError(msg)
    for code in data["mypy"]["errorCodes"]:
        if code not in mypy:
            msg = "Missing mypy error code"
            raise ValueError(msg)


def verify_yamllint_contract(data: StrictPolicy) -> None:
    """Fail if yamllint enabled/disabled rules drifted from the policy."""
    from yamllint.config import YamlLintConfig

    yamllint_rules = YamlLintConfig(file=str(ROOT / "ci/quality/yamllint.yaml")).rules
    for name, reason in data["yamllint"]["disabled"].items():
        if not isinstance(reason, str) or len(reason) < 20:
            msg = "Yamllint disable reason is missing"
            raise ValueError(msg)
        if yamllint_rules[name] is not False:
            raise ValueError("Yamllint rule was not disabled: " + name)
    for name, options in data["yamllint"]["enabled"].items():
        verify_yamllint_rule(yamllint_rules[name], name, options)


def verify_yamllint_rule(actual: object, name: str, options: dict[str, object]) -> None:
    """Fail if an enabled yamllint rule's options drifted from the policy."""
    if isinstance(actual, dict):
        for key, value in options.items():
            if actual.get(key) != value:
                raise ValueError("Yamllint option drifted: " + name + " " + key)
        return
    raise ValueError("Yamllint rule is not enabled: " + name)


def verify_yamllint_text(data: StrictPolicy) -> None:
    """Fail if yamllint truthy, line-length or disables drifted."""
    yamllint_text = (ROOT / "ci/quality/yamllint.yaml").read_text()
    if "disable" in yamllint_text:
        disabled_names = set(data["yamllint"]["disabled"])
        for line in yamllint_text.splitlines():
            if "disable" not in line:
                continue
            named = line.split(":", 1)[0].strip()
            if named not in disabled_names:
                msg = "Yamllint disables a rule that has no contract"
                raise ValueError(msg)
    yamllint = yaml.safe_load(yamllint_text)
    if yamllint["rules"]["truthy"]["allowed-values"] != ["true", "false"]:
        msg = "YAML truthy values drifted"
        raise ValueError(msg)
    if yamllint["rules"]["truthy"].get("check-keys") is not False:
        msg = "YAML truthy key exception drifted"
        raise ValueError(msg)
    if yamllint["rules"]["line-length"]["max"] != 100:
        msg = "YAML line length drifted from the repository length"
        raise ValueError(msg)


def verify_ansible_policy(data: StrictPolicy) -> None:
    """Fail if the ansible-lint partition drifted from the policy."""
    ansible = yaml.safe_load((ROOT / "ci/quality/ansible-lint.yaml").read_text())
    if set(ansible) != {"profile", "offline", "strict", "enable_list"}:
        msg = "Ansible lint config has an unexpected key"
        raise ValueError(msg)
    if (
        ansible["profile"] != "min"
        or ansible["offline"] is not True
        or ansible["strict"] is not True
    ):
        msg = "Ansible lint mode drifted"
        raise ValueError(msg)
    enable = set(ansible["enable_list"])
    excluded = set(data["ansible"]["excluded"])
    profile_min = set(data["ansible"]["profileMin"])
    if enable != set(data["ansible"]["enable"]):
        msg = "Ansible enable list drifted"
        raise ValueError(msg)
    if enable & excluded or enable & profile_min or excluded & profile_min:
        msg = "Ansible rule partition overlaps"
        raise ValueError(msg)


def verify_ansible_catalog(data: StrictPolicy) -> None:
    """Fail if the ansible-lint catalog is not exactly partitioned."""
    enable = set(data["ansible"]["enable"])
    excluded = set(data["ansible"]["excluded"])
    profile_min = set(data["ansible"]["profileMin"])
    catalog = listed_ansible_rules()
    if catalog != enable | excluded | profile_min:
        missing = catalog - (enable | excluded | profile_min)
        extra = (enable | excluded | profile_min) - catalog
        msg = f"Ansible rule partition does not cover the installed catalog {missing or extra}"
        raise ValueError(msg)
    unknown = discovered_ansible_rules() - catalog
    if unknown:
        msg = "Unreviewed ansible-lint rule"
        raise ValueError(msg)


def verify_kube_linter_policy(data: StrictPolicy) -> None:
    """Fail if kube-linter defaults or includes drifted."""
    kube = yaml.safe_load((ROOT / "ci/quality/kube-linter.yaml").read_text())
    checks = kube["checks"]
    if checks.get("doNotAutoAddDefaults") is not False or "exclude" in checks:
        msg = "kube-linter defaults were disabled"
        raise ValueError(msg)
    if checks["include"] != data["kubeLinter"]["include"]:
        msg = "kube-linter include list drifted"
        raise ValueError(msg)
    omitted = set(data["kubeLinter"]["omitted"])
    if set(checks["include"]) & omitted:
        msg = "kube-linter include overlaps an omission"
        raise ValueError(msg)


def verify_hadolint_policy() -> None:
    """Fail if hadolint strict threshold drifted."""
    hadolint = yaml.safe_load((ROOT / "ci/quality/hadolint.yaml").read_text())
    if hadolint.get("ignored") or hadolint.get("failure-threshold") != "style":
        msg = "hadolint strict threshold drifted"
        raise ValueError(msg)


def verify_vendor_provenance(data: StrictPolicy) -> None:
    """Fail if vendored tree provenance drifted."""
    vendors = json.loads((ROOT / "deploy/contracts/vendors.json").read_text())
    if sorted(tree["path"] for tree in vendors["trees"]) != sorted(data["vendorPaths"]):
        msg = "Vendor provenance drifted"
        raise ValueError(msg)
    if [item.rstrip("/") for item in vendor_prefixes()] != [
        tree["path"] for tree in vendors["trees"]
    ]:
        msg = "Vendor prefix adapter drifted"
        raise ValueError(msg)


def verify_secret_list(data: StrictPolicy) -> None:
    """Fail if the secret false-positive list changed without review."""
    secret_path = ROOT / "ci/quality/secret-false-positives.json"
    digest = hashlib.sha256(secret_path.read_bytes()).hexdigest()
    if digest != data["reviewedExceptionDigest"]:
        msg = "Secret false-positive list changed without a policy review"
        raise ValueError(msg)


def verify_quality_tooling() -> None:
    """Fail if debt regeneration or baseline acceptance returned."""
    for name in [
        *(ROOT / "ci/quality").glob("check_*.py"),
        ROOT / "ci/quality/runner.py",
        ROOT / "ci/quality/charts.py",
    ]:
        if "--record-debt" in (ROOT / name).read_text():
            msg = "Debt regeneration flag returned"
            raise ValueError(msg)
    common = (ROOT / "ci/quality/common.py").read_text()
    if "not in known" in common or "Baseline regeneration is forbidden" not in common:
        msg = "Debt baseline can decide success again"
        raise ValueError(msg)


def verify_generated_publisher(data: StrictPolicy) -> None:
    """Fail if generated workflow trust or permissions drifted."""
    publisher = data["generatedWorkflows"]
    if publisher["trusted"] is not False or publisher["waiver"] is not False:
        msg = "Generated workflows were marked trusted"
        raise ValueError(msg)
    if len(publisher["blocker"]) < 20:
        msg = "Generated workflow blocker is missing"
        raise ValueError(msg)
    document = yaml.safe_load((ROOT / publisher["publisher"]).read_text())
    if document.get("on") != publisher["triggers"]:
        msg = "Generated publisher triggers drifted"
        raise ValueError(msg)
    if document.get("permissions") != publisher["topPermissions"]:
        msg = "Generated publisher top permissions drifted"
        raise ValueError(msg)
    for job, permissions in publisher["jobs"].items():
        if document["jobs"][job].get("permissions") != permissions:
            msg = "Generated publisher job permissions drifted"
            raise ValueError(msg)
    header = (ROOT / publisher["publisher"]).read_text().splitlines()[0]
    if not header.startswith("# Generated by Quality Graph. DO NOT EDIT MANUALLY."):
        msg = "Generated publisher header drifted"
        raise ValueError(msg)


def verify_lint_scanner_text(data: StrictPolicy) -> None:
    """Fail if strict scanner invocation or coverage reporting drifted."""
    publisher = data["generatedWorkflows"]
    lint_text = "\n".join(
        (ROOT / "ci/quality" / name).read_text()
        for name in ("lint_support.py", "check_python.py", "check_workflow.py")
    )
    for needle in ("--enable=all", "--follow-imports=silent", "--persona", "auditor"):
        if needle not in lint_text:
            msg = "Strict linter invocation drifted"
            raise ValueError(msg)
    if "mypy coverage incomplete" not in lint_text:
        msg = "mypy can report a partial run as complete"
        raise ValueError(msg)
    if (
        "returncode == 2 and not parsed" in lint_text
        or "returncode == 2 and duplicate" in lint_text
    ):
        msg = "mypy still accepts a fatal partial run"
        raise ValueError(msg)
    if "quality-graph-publish" in lint_text or ".github/workflows" not in lint_text:
        msg = "workflow scanner special-cases or drops workflow files"
        raise ValueError(msg)
    for rule in publisher["zizmor"]:
        if rule in lint_text:
            msg = "zizmor rule is named in the scanner"
            raise ValueError(msg)


def verify_pinned_tools() -> None:
    """Fail if pinned quality tool versions drifted."""
    project = (ROOT / "pyproject.toml").read_text()
    for pin in ("mypy==2.4.1", "ruff==0.15.12", "ansible-lint==26.11.0", "yamllint==1.38.0"):
        if pin not in project:
            msg = "Pinned quality tool drifted"
            raise ValueError(msg)


def verify_historical_debt() -> None:
    """Fail if any historical debt file can decide acceptance."""
    for path in (ROOT / "ci/quality/debt").glob("*.json"):
        debt = json.loads(path.read_text())
        if debt.get("acceptance") is not False:
            msg = "Historical debt file is not marked non-accepting"
            raise ValueError(msg)


def verify_configuration() -> None:
    """Fail if any part of the pinned strict policy does not hold."""
    frozen_source_files()
    use_project_tools()
    data = policy()
    verify_ruff_policy(data)
    verify_mypy_policy(data)
    verify_yamllint_contract(data)
    verify_yamllint_text(data)
    verify_ansible_policy(data)
    verify_ansible_catalog(data)
    verify_kube_linter_policy(data)
    verify_hadolint_policy()
    verify_vendor_provenance(data)
    verify_secret_list(data)
    verify_quality_tooling()
    verify_generated_publisher(data)
    verify_lint_scanner_text(data)
    verify_pinned_tools()
    verify_historical_debt()


def main() -> int:
    """Execute main."""
    try:
        verify_configuration()
    except (OSError, TypeError, ValueError) as error:
        print(f"configuration: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    hits = suppression_hits(owned(tracked()))
    print(f"suppressions={len(hits)}")
    for hit in hits:
        print(hit)
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
