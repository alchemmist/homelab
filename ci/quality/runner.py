"""Report one check using the shared owned inventory and fail-closed protocol."""

import sys
from collections.abc import Callable

from ci.quality.common import (
    ROOT,
    Finding,
    failure,
    owned,
    report,
    tracked,
    use_project_tools,
)


def run(tool: str, checker: Callable[[list[str]], tuple[list[Finding], int]]) -> int:
    """Run an independent CI check and write its native report."""
    output = ROOT / f"reports/{tool}.json"
    try:
        use_project_tools()
        findings, count = checker(owned(tracked()))
        return report(tool, findings, count, output)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        failure(output, error)
        print(
            f"{tool}: {type(error).__name__}; tool failure, NOT an accepted lint result",
            file=sys.stderr,
        )
        return 2
