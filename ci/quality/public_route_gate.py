"""Audit proposed Ingress selection using Kubernetes JSON from stdin, without writes."""

import json
import sys
from collections import defaultdict
from itertools import combinations
from typing import TypedDict

import yaml

from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.public_web import CATALOG

LABEL = "homelab.alchemmist.xyz/public-web"


class _Review(TypedDict):
    """Accumulated review state: expected owners, sightings, path owners and issues."""

    expected: set[tuple[str, str]]
    seen: set[tuple[str, str]]
    owners: "defaultdict[tuple[str, str, str], set[str]]"
    issues: set[str]


class _ItemCtx(TypedDict):
    """One item's selection context: namespace, name, opt-in label and class."""

    ns: str
    name: str
    selected: bool
    ingressClass: object


def _plain_host(policy: object) -> str:
    """Narrow one catalog host entry's route policy to its plain form."""
    return str(view(policy).get("route", "web"))


def _item_ctx(item: dict[str, object]) -> _ItemCtx:
    """Narrow one item's metadata and opt-in label into the review context."""
    meta = view(item["metadata"])
    selected = view(meta.get("labels", {})).get(LABEL) in {"true", "reviewed"}
    return {
        "ns": plain(meta["namespace"]),
        "name": plain(meta["name"]),
        "selected": selected,
        "ingressClass": view(item["spec"]).get("ingressClassName"),
    }


def _rule_findings(review: _Review, ctx: _ItemCtx, rule: dict[str, object]) -> None:
    """Record one rule's path ownership findings against the catalog review."""
    ns, name, selected = ctx["ns"], ctx["name"], ctx["selected"]
    host = plain(rule.get("host", "*"))
    if (ns, host) not in review["expected"]:
        if selected:
            review["issues"].add(f"unexpected selected host: {ns}/{name} {host}")
        return
    review["seen"].add((ns, host))
    paths = entries(view(rule.get("http", {})).get("paths", []))
    if not paths:
        review["issues"].add(f"missing paths: {ns}/{name} {host}")
    for raw_path in paths:
        path = view(raw_path)
        if not path.get("path") or path.get("pathType") not in {
            "Exact",
            "Prefix",
            "ImplementationSpecific",
        }:
            review["issues"].add(f"invalid path or pathType: {ns}/{name} {host}")
            continue
        key = (host, plain(path["path"]), plain(path["pathType"]))
        review["owners"][key].add(f"{ns}/{name}")
    if not selected or ctx["ingressClass"] != "traefik":
        review["issues"].add(f"missing opt-in or class: {ns}/{name} {host}")


def _item_findings(review: _Review, item: dict[str, object]) -> None:
    """Review one Ingress-shaped item for implicit default routes and rule ownership."""
    spec = view(item["spec"])
    ctx = _item_ctx(item)
    rules = entries(spec.get("rules", []))
    if ctx["selected"] and (not rules or "defaultBackend" in spec):
        review["issues"].add(f"unexpected default route: {ctx['ns']}/{ctx['name']}")
    for rule in rules:
        _rule_findings(review, ctx, view(rule))


def _covers(parent: tuple[str, str, str], child: tuple[str, str, str]) -> bool:
    """Determine whether the parent path selector covers the child under Kubernetes semantics."""
    if parent[2] == "ImplementationSpecific":
        return True  # Controller-specific semantics require owner review.
    if parent[2] == "Exact":
        return parent[1] == child[1]
    prefix = parent[1].rstrip("/")
    return child[1].rstrip("/") == prefix or child[1].startswith(prefix + "/")


def _emit_ambiguous(review: _Review) -> None:
    """Report owners that overlap on one host or that select intersecting paths."""
    for key, names in review["owners"].items():
        if len(names) > 1:
            review["issues"].add(f"overlapping owners: {' '.join(key)}: {', '.join(sorted(names))}")
    for (left, ls), (right, rs) in combinations(sorted(review["owners"].items()), 2):
        if left[0] != right[0] or len(ls | rs) == 1:
            continue
        if _covers(left, right) or _covers(right, left):
            both = ", ".join(sorted(ls | rs))
            review["issues"].add(
                f"review intersecting paths: {' '.join(left)} | {' '.join(right)}: {both}"
            )


def findings(catalog: dict[str, object], items: list[dict[str, object]]) -> list[str]:
    """Require each ordinary path owner, reject implicit routes and ambiguous owners."""
    review: _Review = {
        "expected": {
            (ns, host)
            for ns, names in view(catalog["hosts"]).items()
            for host, policy in view(names).items()
            if str(view(policy).get("route", "web")) == "web"
        },
        "seen": set(),
        "owners": defaultdict(set),
        "issues": set(),
    }
    for item in items:
        _item_findings(review, item)
    review["issues"].update(
        f"missing Ingress: {ns} {host}" for ns, host in review["expected"] - review["seen"]
    )
    _emit_ambiguous(review)
    return sorted(review["issues"])


def main() -> int:
    """Exit nonzero for incomplete inventory; emit route metadata only."""
    issues = findings(yaml.safe_load(CATALOG.read_text()), json.load(sys.stdin)["items"])
    for issue in issues:
        print(issue)
    return int(bool(issues))


if __name__ == "__main__":
    sys.exit(main())
