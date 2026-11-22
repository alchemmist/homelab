"""Emit the tracked, owned Python inputs to a scoped lint node."""

from __future__ import annotations

import argparse
import os
import sys

from scripts.quality.common import owned, tracked


def python_inputs(roots: list[str]) -> list[str]:
    """Validate ownership first; an empty inventory in any requested scope is an error."""
    files = owned(tracked())
    result = []
    for root in roots:
        selected = [name for name in files if name.startswith(root) and name.endswith(".py")]
        if not selected:
            message = f"No tracked owned Python inputs in {root}"
            raise ValueError(message)
        result.extend(selected)
    return list(dict.fromkeys(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots",
        nargs="+",
        choices=("ansible/", "deploy/", "scripts/", "scripts/quality/", "tests/"),
    )
    for path in python_inputs(parser.parse_args().roots):
        sys.stdout.buffer.write(os.fsencode(path) + b"\0")
