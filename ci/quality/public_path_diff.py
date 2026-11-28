"""Compare public path ownership at boundary witnesses, using backend inventory JSON."""

import argparse
import json
import re
import sys
from collections import defaultdict
from typing import cast

from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.public_path_rule import source_priority

MSG_INVALID_PRIORITY = "invalid router priority"


def _declared_priority(row: dict[str, object]) -> int:
    """Retrieve the reviewed router priority, rejecting anything unparsable."""
    value = row["priority"]
    if value is None:
        return 0
    if isinstance(value, bool) or not re.fullmatch(r"-?[0-9]+", str(value)):
        reason = MSG_INVALID_PRIORITY
        raise ValueError(reason)
    return int(str(value))


def _winners(
    rows: list[tuple[int, dict[str, object]]], path: str, *, strict: bool
) -> list[dict[str, object]]:
    """Rank the rows one boundary witness selects under one prefixmatching policy."""
    matches: list[tuple[int, dict[str, object]]] = []
    for priority, row in rows:
        pattern = plain(row["path"])
        base = pattern.rstrip("/")
        if row["pathType"] == "Exact":
            hit = path == pattern
        elif strict:
            hit = path == base or path.startswith(base + "/")
        else:
            hit = path.startswith(pattern)
        if hit:
            matches.append((priority, row))
    top = max((p for p, _ in matches), default=None)
    return sorted((r for p, r in matches if p == top), key=lambda r: json.dumps(r, sort_keys=True))


def _witnesses(rows: list[tuple[int, dict[str, object]]]) -> set[str]:
    """Collect the boundary paths where either policy may split winners."""
    witnesses = {"/"}
    for _, row in rows:
        pattern = plain(row["path"])
        base = pattern.rstrip("/")
        witnesses.update(
            [
                pattern,
                base or "/",
                base + "/",
                base + "/probe",
                base + "-probe" if base else "/probe",
            ]
        )
    return witnesses


def path_diff(routes: list[dict[str, object]], *, source_strict: bool) -> list[dict[str, object]]:
    """Report changed winning rows or ties. Never use this report as a route allowlist."""
    groups: defaultdict[str, list[tuple[int, dict[str, object]]]] = defaultdict(list)
    for row in routes:
        pr = source_priority(
            plain(row["host"]),
            plain(row["path"]),
            plain(row["pathType"]),
            strict_prefix=source_strict,
            declared=_declared_priority(row),
        )
        groups[plain(row["host"])].append((pr, row))
    findings: list[dict[str, object]] = []
    for host, rows in sorted(groups.items()):
        for witness in sorted(_witnesses(rows)):
            old = _winners(rows, witness, strict=source_strict)
            new = _winners(rows, witness, strict=True)
            if old != new or len(old) > 1 or len(new) > 1:
                findings.append(
                    {"host": host, "witness": witness, "original": old, "candidate": new}
                )
    return findings


def main() -> int:
    """Diff path winners per boundary witness, exiting nonzero on any finding."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-prefix", required=True, choices=["character", "segment"])
    args = parser.parse_args()
    report = json.load(sys.stdin)
    if view(report)["errors"]:
        print("Backend inventory incomplete; cannot compare path winners.", file=sys.stderr)
        return 2
    routes = cast("list[dict[str, object]]", entries(view(report)["routes"]))
    findings = path_diff(routes, source_strict=args.source_prefix == "segment")
    print(json.dumps(findings, indent=2))
    return int(bool(findings))


if __name__ == "__main__":
    sys.exit(main())
