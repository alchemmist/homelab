"""Check yaml."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.quality.common import Finding


from ci.quality.common import ROOT, finding
from ci.quality.runner import run


def yaml_targets(names):
    # Helm and Ansible templates are Go/Jinja text, not YAML documents.
    """Execute yaml_targets."""
    return [
        p
        for p in names
        if p.endswith((".yml", ".yaml")) and "/templates/" not in p and not p.endswith(".j2")
    ]


def check_yaml(names: list[str]) -> tuple[list[Finding], int]:
    """Run the yaml linter and return findings and target count."""
    from yamllint import linter
    from yamllint.config import YamlLintConfig

    config = YamlLintConfig(file=str(ROOT / "ci/quality/yamllint.yaml"))
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
