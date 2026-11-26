"""Audit proposed Ingress selection using Kubernetes JSON from stdin, without writes."""

import json
import sys
from collections import defaultdict
from itertools import combinations

import yaml
from ci.quality.public_web import CATALOG

LABEL = "homelab.alchemmist.xyz/public-web"


def findings(catalog: dict, items: list[dict]) -> list[str]:
    """Require each ordinary path owner, reject implicit routes and ambiguous owners."""
    expected = {
        (ns, host)
        for ns, names in catalog["hosts"].items()
        for host, policy in names.items()
        if policy.get("route", "web") == "web"
    }
    seen = set()
    owners = defaultdict(set)
    issues = set()
    for item in items:
        meta, spec = item["metadata"], item["spec"]
        ns, name = meta["namespace"], meta["name"]
        selected = meta.get("labels", {}).get(LABEL) == "true"
        rules = spec.get("rules", [])
        if selected and (not rules or "defaultBackend" in spec):
            issues.add(f"unexpected default route: {ns}/{name}")
        for rule in rules:
            host = rule.get("host", "*")
            if (ns, host) not in expected:
                if selected:
                    issues.add(f"unexpected selected host: {ns}/{name} {host}")
                continue
            seen.add((ns, host))
            paths = rule.get("http", {}).get("paths", [])
            if not paths:
                issues.add(f"missing paths: {ns}/{name} {host}")
            for path in paths:
                if not path.get("path") or path.get("pathType") not in {
                    "Exact",
                    "Prefix",
                    "ImplementationSpecific",
                }:
                    issues.add(f"invalid path or pathType: {ns}/{name} {host}")
                    continue
                key = (host, path["path"], path["pathType"])
                owners[key].add(f"{ns}/{name}")
            if not selected or spec.get("ingressClassName") != "traefik":
                issues.add(f"missing opt-in or class: {ns}/{name} {host}")
    for ns, host in expected - seen:
        issues.add(f"missing Ingress: {ns} {host}")
    for key, names in owners.items():
        if len(names) > 1:
            issues.add(f"overlapping owners: {' '.join(key)}: {', '.join(sorted(names))}")
    for (left, ls), (right, rs) in combinations(sorted(owners.items()), 2):
        if left[0] != right[0] or len(ls | rs) == 1:
            continue

        def covers(parent: tuple, child: tuple) -> bool:
            if parent[2] == "ImplementationSpecific":
                return True  # Controller-specific semantics require owner review.
            if parent[2] == "Exact":
                return parent[1] == child[1]
            prefix = parent[1].rstrip("/")
            return child[1].rstrip("/") == prefix or child[1].startswith(prefix + "/")

        if covers(left, right) or covers(right, left):
            issues.add(
                f"review intersecting paths: {' '.join(left)} | {' '.join(right)}: {', '.join(sorted(ls | rs))}"
            )
    return sorted(issues)


def main() -> int:
    """Exit nonzero for incomplete inventory; emit route metadata only."""
    issues = findings(yaml.safe_load(CATALOG.read_text()), json.load(sys.stdin)["items"])
    for issue in issues:
        print(issue)
    return int(bool(issues))


if __name__ == "__main__":
    sys.exit(main())
