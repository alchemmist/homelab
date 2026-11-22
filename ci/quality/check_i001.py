"""Enforce I001 on the deploy-i001 inventory."""

from ci.quality.ruff_scope import run


def main() -> int:
    """Run this rule scope locally or in Quality Graph."""
    return run("I001", ["ansible/", "deploy/", "ci/", "scripts/", "tests/"])


if __name__ == "__main__":
    raise SystemExit(main())
