"""Check secrets."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.quality.common import Finding

from ci.quality.common import ROOT, command, finding, tracked
from ci.quality.runner import run


def check_secrets(_names: list[str]) -> tuple[list[Finding], int]:
    """Run the secrets linter and return findings and target count."""
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


if __name__ == "__main__":
    raise SystemExit(run("secrets", check_secrets))
