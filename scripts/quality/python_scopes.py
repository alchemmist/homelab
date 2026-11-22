"""Check additive Python scopes against the owned Git inventory with pinned Ruff."""

from __future__ import annotations

import json
import sys
from itertools import batched
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from scripts.quality import common

if TYPE_CHECKING:
    from pathlib import Path

RUFF = common.ROOT / ".venv/bin/ruff"


def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Don't let a repeated JSON field silently replace an earlier rule or path."""
    result = dict(pairs)
    if len(result) != len(pairs):
        message = "Duplicate JSON field"
        raise ValueError(message)
    return result


def string_list(value: object) -> list[str]:
    """Require a nonempty JSON array of nonempty strings."""
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        message = "Expected a nonempty list of strings"
        raise ValueError(message)
    return value


def read_scope(path: Path, inventory: list[PurePosixPath]) -> tuple[list[str], list[str]]:
    """Expand each anchored glob independently and reject stale or unsafe includes."""
    if path.is_symlink() or not path.is_file():
        message = f"Not a regular scope: {path.name}"
        raise ValueError(message)
    scope = json.loads(path.read_bytes(), object_pairs_hook=unique_fields)
    if not isinstance(scope, dict) or set(scope) != {"include", "rules"}:
        message = "Scope must contain exactly include and rules"
        raise ValueError(message)
    selected = set()
    for pattern in string_list(scope["include"]):
        if "\\" in pattern or "\0" in pattern or {"", ".", ".."}.intersection(pattern.split("/")):
            message = f"Invalid repository-relative glob: {pattern!r}"
            raise ValueError(message)
        matches = [str(p) for p in inventory if p.full_match(pattern, case_sensitive=True)]
        if not matches:
            message = f"No tracked owned Python files match {pattern!r}"
            raise ValueError(message)
        selected.update(matches)
    return sorted(selected), string_list(scope["rules"])


def main() -> int:
    """Run each rule independently so overlapping scopes can only add coverage."""
    directory = common.ROOT / "quality/python-scopes"
    scopes = sorted(directory.glob("*.json"))
    if directory.is_symlink() or not scopes:
        message = "Missing or unsafe Python scope registry"
        raise ValueError(message)
    inventory = [PurePosixPath(p) for p in common.owned(common.tracked()) if p.endswith(".py")]
    catalog = json.loads(common.command([RUFF, "rule", "--all", "--output-format=json"]).stdout)
    preview = {row["code"]: row["preview"] for row in catalog if "Removed" not in row["status"]}
    by_rule: dict[str, set[str]] = {}
    for path in scopes:
        try:
            files, rules = read_scope(path, inventory)
        except ValueError as error:
            message = f"{path.name}: {error}"
            raise ValueError(message) from error
        for rule in rules:
            if rule not in preview:
                message = f"{path.name}: Unknown or removed Ruff rule: {rule!r}"
                raise ValueError(message)
            by_rule.setdefault(rule, set()).update(files)

    status = 0
    for rule, paths in sorted(by_rule.items()):
        for batch in batched(sorted(paths), 32, strict=False):
            result = common.command(
                [
                    RUFF,
                    "check",
                    "--config",
                    "quality/ruff.toml",
                    "--config",
                    "lint.per-file-ignores = {}",
                    "--select",
                    rule,
                    "--ignore-noqa",
                    "--no-fix",
                    "--preview" if preview[rule] else "--no-preview",
                    "--output-format=concise",
                    "--",
                    *(f"./{p}" for p in batch),
                ],
                allowed=(0, 1),
            )
            sys.stdout.write(result.stdout)
            status |= result.returncode
    return status


if __name__ == "__main__":
    raise SystemExit(main())
