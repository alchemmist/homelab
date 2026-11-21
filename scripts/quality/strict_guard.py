"""Fail closed when strict policy, ownership, or suppression controls drift."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

import yaml
from common import (
    ROOT,
    command,
    frozen_source_files,
    owned,
    tracked,
    use_project_tools,
    vendor_prefixes,
)


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
    """Keys of quality/strict-policy.json consumed by the strict guard."""

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
            r"#\s*" + marker("no", "qa") + r"\b",
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
    return json.loads((ROOT / "quality/strict-policy.json").read_text())


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
    if path.startswith(("quality/", "scripts/quality/")) or path in {"qg.yaml", "pyproject.toml"}:
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
        "tools": "workflows",
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
        raise ValueError("ansible-lint rule catalog was not parsed")
    return found


def verify_ruff_policy(data: StrictPolicy) -> None:
    """Fail if ruff config diverges from the strict policy."""
    ruff = tomllib.loads((ROOT / "quality/ruff.toml").read_text())
    if "exclude" in ruff or "extend-exclude" in ruff or "exclude" in ruff.get("lint", {}):
        raise ValueError("Ruff exclude hides files")
    if ruff["lint"]["select"] != ["ALL"]:
        raise ValueError("Ruff must select ALL")
    if ruff["lint"]["ignore"] != data["ruff"]["ignore"]:
        raise ValueError("Ruff ignore list drifted from the strict policy")
    if ruff["lint"]["per-file-ignores"] != data["ruff"]["perFileIgnores"]:
        raise ValueError("Ruff per-file ignores drifted")


def verify_mypy_policy(data: StrictPolicy) -> None:
    """Fail if mypy strict config or required flags drifted."""
    mypy = (ROOT / "quality/mypy.ini").read_text()
    if (
        "strict = true" not in mypy
        or "disable_error_code" in mypy
        or "ignore_missing_imports" in mypy
    ):
        raise ValueError("mypy strict mode drifted")
    if "follow_imports" in mypy:
        raise ValueError("mypy must not skip imports from the config file")
    for flag in data["mypy"]["extra"]:
        if f"{flag} = true" not in mypy:
            raise ValueError("Missing mypy strict flag")
    for code in data["mypy"]["errorCodes"]:
        if code not in mypy:
            raise ValueError("Missing mypy error code")


def verify_yamllint_contract(data: StrictPolicy) -> None:
    """Fail if yamllint enabled/disabled rules drifted from the policy."""
    from yamllint.config import YamlLintConfig

    yamllint_rules = YamlLintConfig(file=str(ROOT / "quality/yamllint.yaml")).rules
    for name, reason in data["yamllint"]["disabled"].items():
        if not isinstance(reason, str) or len(reason) < 20:
            raise ValueError("Yamllint disable reason is missing")
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
    yamllint_text = (ROOT / "quality/yamllint.yaml").read_text()
    if "disable" in yamllint_text:
        disabled_names = set(data["yamllint"]["disabled"])
        for line in yamllint_text.splitlines():
            if "disable" not in line:
                continue
            named = line.split(":", 1)[0].strip()
            if named not in disabled_names:
                raise ValueError("Yamllint disables a rule that has no contract")
    yamllint = yaml.safe_load(yamllint_text)
    if yamllint["rules"]["truthy"]["allowed-values"] != ["true", "false"]:
        raise ValueError("YAML truthy values drifted")
    if yamllint["rules"]["truthy"].get("check-keys") is not False:
        raise ValueError("YAML truthy key exception drifted")
    if yamllint["rules"]["line-length"]["max"] != 100:
        raise ValueError("YAML line length drifted from the repository length")


def verify_ansible_policy(data: StrictPolicy) -> None:
    """Fail if the ansible-lint partition drifted from the policy."""
    ansible = yaml.safe_load((ROOT / "quality/ansible-lint.yaml").read_text())
    if set(ansible) != {"profile", "offline", "strict", "enable_list"}:
        raise ValueError("Ansible lint config has an unexpected key")
    if (
        ansible["profile"] != "min"
        or ansible["offline"] is not True
        or ansible["strict"] is not True
    ):
        raise ValueError("Ansible lint mode drifted")
    enable = set(ansible["enable_list"])
    excluded = set(data["ansible"]["excluded"])
    profile_min = set(data["ansible"]["profileMin"])
    if enable != set(data["ansible"]["enable"]):
        raise ValueError("Ansible enable list drifted")
    if enable & excluded or enable & profile_min or excluded & profile_min:
        raise ValueError("Ansible rule partition overlaps")


def verify_ansible_catalog(data: StrictPolicy) -> None:
    """Fail if the ansible-lint catalog is not exactly partitioned."""
    enable = set(data["ansible"]["enable"])
    excluded = set(data["ansible"]["excluded"])
    profile_min = set(data["ansible"]["profileMin"])
    catalog = listed_ansible_rules()
    if catalog != enable | excluded | profile_min:
        missing = catalog - (enable | excluded | profile_min)
        extra = (enable | excluded | profile_min) - catalog
        raise ValueError(
            f"Ansible rule partition does not cover the installed catalog {missing or extra}"
        )
    unknown = discovered_ansible_rules() - catalog
    if unknown:
        raise ValueError("Unreviewed ansible-lint rule")


def verify_kube_linter_policy(data: StrictPolicy) -> None:
    """Fail if kube-linter defaults or includes drifted."""
    kube = yaml.safe_load((ROOT / "quality/kube-linter.yaml").read_text())
    checks = kube["checks"]
    if checks.get("doNotAutoAddDefaults") is not False or "exclude" in checks:
        raise ValueError("kube-linter defaults were disabled")
    if checks["include"] != data["kubeLinter"]["include"]:
        raise ValueError("kube-linter include list drifted")
    omitted = set(data["kubeLinter"]["omitted"])
    if set(checks["include"]) & omitted:
        raise ValueError("kube-linter include overlaps an omission")


def verify_hadolint_policy() -> None:
    """Fail if hadolint strict threshold drifted."""
    hadolint = yaml.safe_load((ROOT / "quality/hadolint.yaml").read_text())
    if hadolint.get("ignored") or hadolint.get("failure-threshold") != "style":
        raise ValueError("hadolint strict threshold drifted")


def verify_vendor_provenance(data: StrictPolicy) -> None:
    """Fail if vendored tree provenance drifted."""
    vendors = json.loads((ROOT / "deploy/contracts/vendors.json").read_text())
    if sorted(tree["path"] for tree in vendors["trees"]) != sorted(data["vendorPaths"]):
        raise ValueError("Vendor provenance drifted")
    if [item.rstrip("/") for item in vendor_prefixes()] != [
        tree["path"] for tree in vendors["trees"]
    ]:
        raise ValueError("Vendor prefix adapter drifted")


def verify_secret_list(data: StrictPolicy) -> None:
    """Fail if the secret false-positive list changed without review."""
    secret_path = ROOT / "quality/secret-false-positives.json"
    digest = hashlib.sha256(secret_path.read_bytes()).hexdigest()
    if digest != data["reviewedExceptionDigest"]:
        raise ValueError("Secret false-positive list changed without a policy review")


def verify_quality_tooling() -> None:
    """Fail if debt regeneration or baseline acceptance returned."""
    for name in ("scripts/quality/lint.py", "scripts/quality/charts.py"):
        if "--record-debt" in (ROOT / name).read_text():
            raise ValueError("Debt regeneration flag returned")
    common = (ROOT / "scripts/quality/common.py").read_text()
    if "not in known" in common or "Baseline regeneration is forbidden" not in common:
        raise ValueError("Debt baseline can decide success again")


def verify_generated_publisher(data: StrictPolicy) -> None:
    """Fail if generated workflow trust or permissions drifted."""
    publisher = data["generatedWorkflows"]
    if publisher["trusted"] is not False or publisher["waiver"] is not False:
        raise ValueError("Generated workflows were marked trusted")
    if len(publisher["blocker"]) < 20:
        raise ValueError("Generated workflow blocker is missing")
    document = yaml.safe_load((ROOT / publisher["publisher"]).read_text())
    if document.get("on") != publisher["triggers"]:
        raise ValueError("Generated publisher triggers drifted")
    if document.get("permissions") != publisher["topPermissions"]:
        raise ValueError("Generated publisher top permissions drifted")
    for job, permissions in publisher["jobs"].items():
        if document["jobs"][job].get("permissions") != permissions:
            raise ValueError("Generated publisher job permissions drifted")
    header = (ROOT / publisher["publisher"]).read_text().splitlines()[0]
    if not header.startswith("# Generated by Quality Graph. DO NOT EDIT MANUALLY."):
        raise ValueError("Generated publisher header drifted")


def verify_lint_scanner_text(data: StrictPolicy) -> None:
    """Fail if strict scanner invocation or coverage reporting drifted."""
    publisher = data["generatedWorkflows"]
    lint_text = (ROOT / "scripts/quality/lint.py").read_text()
    for needle in ("--enable=all", "--follow-imports=silent", "--persona", "auditor"):
        if needle not in lint_text:
            raise ValueError("Strict linter invocation drifted")
    if "mypy coverage incomplete" not in lint_text:
        raise ValueError("mypy can report a partial run as complete")
    if (
        "returncode == 2 and not parsed" in lint_text
        or "returncode == 2 and duplicate" in lint_text
    ):
        raise ValueError("mypy still accepts a fatal partial run")
    if "quality-graph-publish" in lint_text or ".github/workflows" not in lint_text:
        raise ValueError("workflow scanner special-cases or drops workflow files")
    for rule in publisher["zizmor"]:
        if rule in lint_text:
            raise ValueError("zizmor rule is named in the scanner")


def verify_pinned_tools() -> None:
    """Fail if pinned quality tool versions drifted."""
    project = (ROOT / "pyproject.toml").read_text()
    for pin in ("mypy==2.4.1", "ruff==0.15.12", "ansible-lint==26.11.0", "yamllint==1.38.0"):
        if pin not in project:
            raise ValueError("Pinned quality tool drifted")


def verify_historical_debt() -> None:
    """Fail if any historical debt file can decide acceptance."""
    for path in (ROOT / "quality/debt").glob("*.json"):
        debt = json.loads(path.read_text())
        if debt.get("acceptance") is not False:
            raise ValueError("Historical debt file is not marked non-accepting")


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
