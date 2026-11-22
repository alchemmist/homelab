"""Enforce Q000,D300 on the scripts-q000 inventory."""

from ci.quality.ruff_scope import run


def main() -> int:
    """Run this rule scope locally or in Quality Graph."""
    return run("Q000,D300", ["ci/", "scripts/", "tests/"])


if __name__ == "__main__":
    raise SystemExit(main())
