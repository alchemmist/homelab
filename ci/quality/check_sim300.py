"""Enforce SIM300 on the graph inventory."""

from ci.quality.ruff_scope import run


def main() -> int:
    """Run this rule scope locally or in Quality Graph."""
    return run("SIM300", ["ci/quality/"])


if __name__ == "__main__":
    raise SystemExit(main())
