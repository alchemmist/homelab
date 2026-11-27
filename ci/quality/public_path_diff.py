"""Compare public path ownership at boundary witnesses, using backend inventory JSON."""

import argparse
import json
import re
import sys
from collections import defaultdict

from ci.quality.public_path_rule import source_priority


def path_diff(routes: list[dict], *, source_strict: bool) -> list[dict]:
    """Report changed winning rows or ties. Never use this report as a route allowlist."""
    groups = defaultdict(list)
    for row in routes:
        value = row["priority"]
        if value is not None and not re.fullmatch(r"-?[0-9]+", str(value)):
            raise ValueError("invalid router priority")
        pr = source_priority(
            row["host"],
            row["path"],
            row["pathType"],
            strict_prefix=source_strict,
            declared=int(value or 0),
        )
        groups[row["host"]].append((pr, row))
    findings = []
    for host, rows in sorted(groups.items()):
        witnesses = {"/"}
        for _, row in rows:
            base = row["path"].rstrip("/")
            witnesses.update(
                [
                    row["path"],
                    base or "/",
                    base + "/",
                    base + "/probe",
                    base + "-probe" if base else "/probe",
                ]
            )

        def winners(path: str, strict: bool) -> list[dict]:
            matches = []
            for priority, row in rows:
                pattern = row["path"]
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
            return sorted(
                (r for p, r in matches if p == top), key=lambda r: json.dumps(r, sort_keys=True)
            )

        for witness in sorted(witnesses):
            old = winners(witness, source_strict)
            new = winners(witness, True)
            if old != new or len(old) > 1 or len(new) > 1:
                findings.append(
                    {"host": host, "witness": witness, "original": old, "candidate": new}
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-prefix", required=True, choices=["character", "segment"])
    args = parser.parse_args()
    report = json.load(sys.stdin)
    if report["errors"]:
        print("Backend inventory incomplete; cannot compare path winners.", file=sys.stderr)
        return 2
    findings = path_diff(report["routes"], source_strict=args.source_prefix == "segment")
    print(json.dumps(findings, indent=2))
    return int(bool(findings))


if __name__ == "__main__":
    sys.exit(main())
