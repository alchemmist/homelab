"""Inventory exact TLS owners from Ingress and Certificate objects, never Secret payloads."""

import json
import sys
from collections import defaultdict

import yaml

from ci.quality.public_web import CATALOG


def inventory(catalog: dict, objects: list[dict]) -> dict:
    """Reject ambiguous/missing host bindings and missing or unready certificate writers."""
    owners = {
        (ns, host)
        for ns, hosts in catalog["hosts"].items()
        for host, policy in hosts.items()
        if policy.get("route", "web") == "web"
    }
    routes = set()
    refs = defaultdict(set)
    writers = defaultdict(list)
    errors = set()
    for obj in objects:
        kind = obj["kind"]
        if kind not in {"Ingress", "Certificate"}:
            raise ValueError("expected only Ingress and Certificate metadata/spec/status")
        ns = obj["metadata"]["namespace"]
        spec = obj["spec"]
        if kind == "Certificate":
            writers[ns, spec["secretName"]].append(obj)
            continue
        if spec.get("ingressClassName") != "traefik":
            continue
        declared = {rule.get("host") for rule in spec.get("rules", [])}
        ordinary = {(ns, host) for host in declared if (ns, host) in owners}
        if not ordinary:
            continue
        routes.update(ordinary)
        if len(ordinary) != len(declared):
            errors.add(
                f"{ns}/{obj['metadata'].get('name', '<unnamed>')}: mixed ordinary and undeclared hosts"
            )
        for tls in spec.get("tls", []):
            for host in tls.get("hosts", []):
                if (ns, host) in owners and tls.get("secretName"):
                    refs[host].add((ns, tls["secretName"]))
    errors.update(f"missing route owner {ns}/{host}" for ns, host in owners - routes)
    sources = {}
    by_namespace = defaultdict(set)
    for host in sorted({host for _, host in owners}):
        if len(refs[host]) != 1:
            errors.add(f"{host}: expected one explicit TLS source, found {len(refs[host])}")
            continue
        (ref,) = refs[host]
        ns, secret = ref
        sources[host] = f"{ns}/{secret}"
        if len(writers[ref]) != 1:
            errors.add(f"{host}: expected one Certificate writer, found {len(writers[ref])}")
            continue
        (cert,) = writers[ref]
        if host not in cert["spec"].get("dnsNames", []):
            errors.add(f"{host}: no exact DNS name in Certificate spec")
        if any((ns, name) not in owners for name in cert["spec"].get("dnsNames", [])):
            errors.add(f"{host}: Certificate also covers names outside this public owner")
        if not any(
            c.get("type") == "Ready"
            and c.get("status") == "True"
            and isinstance(cert["metadata"].get("generation"), int)
            and c.get("observedGeneration") == cert["metadata"].get("generation")
            for c in cert.get("status", {}).get("conditions", [])
        ):
            errors.add(f"{host}: Certificate not Ready")
        by_namespace[ns].add(secret)
    # A diagnostic upper bound for a future exact-get reader, NOT a drop-in
    # policy for Traefik's informer, which still requires list/watch.
    rules = (
        {}
        if errors
        else {
            ns: {
                "apiGroups": [""],
                "resources": ["secrets"],
                "resourceNames": sorted(names),
                "verbs": ["get"],
            }
            for ns, names in sorted(by_namespace.items())
        }
    )
    return {"hostSources": sources, "namedGetRules": rules, "errors": sorted(errors)}


def main() -> int:
    batch = json.load(sys.stdin)
    report = inventory(yaml.safe_load(CATALOG.read_text()), batch["items"])
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(main())
