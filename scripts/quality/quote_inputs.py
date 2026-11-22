"""Emit the tracked, owned script and test inputs to the Q000 graph node."""

from __future__ import annotations

import os
import sys

from common import owned, tracked


def quote_inputs() -> list[str]:
    """Validate ownership first; an empty inventory in either scope is an error."""
    files = owned(tracked())
    result = []
    for root in ("scripts/", "tests/"):
        selected = [name for name in files if name.startswith(root) and name.endswith(".py")]
        if not selected:
            message = f"No tracked owned Python inputs in {root}"
            raise ValueError(message)
        result.extend(selected)
    return result


if __name__ == "__main__":
    for path in quote_inputs():
        sys.stdout.buffer.write(os.fsencode(path) + b"\0")
