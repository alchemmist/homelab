"""Enforce ANN201 on the rustfs-return-types inventory."""

from ci.quality.ruff_scope import run


def main() -> int:
    """Run this rule scope locally or in Quality Graph."""
    return run("ANN201", ["services/rustfs_gateway/"])


if __name__ == "__main__":
    raise SystemExit(main())
