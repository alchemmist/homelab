"""Check ansible."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.quality.common import Finding

from ci.quality.common import ROOT, command
from ci.quality.lint_support import sarif
from ci.quality.runner import run


def check_ansible(names: list[str]) -> tuple[list[Finding], int]:
    """Run the ansible linter and return findings and target count."""
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


if __name__ == "__main__":
    raise SystemExit(run("ansible", check_ansible))
