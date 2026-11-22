"""Run scoped Ruff checks on the tracked, owned Python inventory."""

import subprocess
from itertools import batched

from ci.quality.python_inputs import python_inputs


def run(rules: str, roots: list[str]) -> int:
    """Pass paths as argv (including spaces) and propagate failures from every batch."""
    argv = [
        "ruff",
        "check",
        "--config",
        "ci/quality/ruff.toml",
        "--select",
        rules,
        "--ignore-noqa",
        "--output-format",
        "concise",
        "--",
    ]
    status = 0
    for paths in batched(python_inputs(roots), 128):
        result = subprocess.run([*argv, *paths], check=False)
        status = status or result.returncode
    return status
