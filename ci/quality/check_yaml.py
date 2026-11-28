"""Check yaml."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ci.quality.common import Finding


from ci.quality.common import ROOT, finding
from ci.quality.runner import run


def yaml_targets(names: list[str]) -> list[str]:
    # Helm and Ansible templates are Go/Jinja text, not YAML documents.
    """Execute yaml_targets."""
    return [
        p
        for p in names
        if p.endswith((".yml", ".yaml")) and "/templates/" not in p and not p.endswith(".j2")
    ]


class _YamllintProblem(Protocol):
    """One reported yamllint problem surface."""

    rule: str | None
    line: int
    desc: str


class _YamllintLinterModule(Protocol):
    """The importable yamllint.linter surface the checker targets."""

    def run(self, source: str, config: object, filepath: str) -> Iterator[_YamllintProblem]: ...


class _YamlLintConfigFactory(Protocol):
    """Constructs a yamllint configuration from a repository config file."""

    def __call__(self, *, file: str) -> object: ...


class _YamlLintConfigModule(Protocol):
    """The importable yamllint.config module surface the checker targets."""

    YamlLintConfig: _YamlLintConfigFactory


def check_yaml(names: list[str]) -> tuple[list[Finding], int]:
    """Run the yaml linter and return findings and target count."""
    linter = cast("_YamllintLinterModule", import_module("yamllint.linter"))
    config_module = cast("_YamlLintConfigModule", import_module("yamllint.config"))
    config = config_module.YamlLintConfig(file=str(ROOT / "ci/quality/yamllint.yaml"))
    files = yaml_targets(names)
    result = [
        finding(
            "yaml-" + (item.rule or "syntax"),
            path,
            item.line,
            "YAML " + (item.rule or "syntax") + ": " + item.desc,
        )
        for path in files
        for item in linter.run((ROOT / path).read_text(), config, filepath=path)
    ]
    return result, len(files)


if __name__ == "__main__":
    raise SystemExit(run("yaml", check_yaml))
