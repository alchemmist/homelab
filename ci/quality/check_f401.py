"""Enforce F401 on the deploy-i001 inventory."""

from ci.quality.ruff_scope import run


def main() -> int:
    """Run this rule scope locally or in Quality Graph."""
    return run("F401", ["ci/", "scripts/", "tests/"])


if __name__ == "__main__":
    raise SystemExit(main())
