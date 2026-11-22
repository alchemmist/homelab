"""Check javascript."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ci.quality.common import Finding

from ci.quality.common import ROOT, command, finding
from ci.quality.runner import run


def check_javascript(names: list[str]) -> tuple[list[Finding], int]:
    """Run the javascript linter and return findings and target count."""
    files = [p for p in names if p.endswith(".js")]
    result = []
    for path in files:
        process = command(["node", "--check", path], allowed=(0, 1))
        if process.returncode:
            from ci.quality.common import digest

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


if __name__ == "__main__":
    raise SystemExit(run("javascript", check_javascript))
