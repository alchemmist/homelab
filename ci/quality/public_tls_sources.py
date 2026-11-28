"""Inventory exact TLS owners from Ingress and Certificate metadata, never Secret payloads."""

import json
import sys
from collections import defaultdict
from typing import TypedDict

import yaml

from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.public_web import CATALOG

MSG_ONLY_INGRESS_CERT = "expected only Ingress and Certificate metadata/spec/status"


class _Bindings(TypedDict):
    """The catalog-derived route and reference sets one inventory pass accumulates."""

    owners: set[tuple[str, str]]
    routes: set[tuple[str, str]]
    refs: "defaultdict[str, set[tuple[str, str]]]"


def _owners(catalog: dict[str, object]) -> _Bindings:
    """Bind the catalogs ordinary web routes and prepare reference accumulation."""
    owner_set = {
        (ns, host)
        for ns, hosts in view(catalog["hosts"]).items()
        for host, policy in view(hosts).items()
        if view(policy).get("route", "web") == "web"
    }
    return {"owners": owner_set, "routes": set(), "refs": defaultdict(set)}


def _certificate_writer(
    obj: dict[str, object],
    meta: dict[str, object],
    spec: dict[str, object],
    writers: "defaultdict[tuple[str, str], list[dict[str, object]]]",
    errors: set[str],
) -> None:
    """Record one Certificate writer for its namespace/local destination."""
    dest = spec.get("secretName")
    if not isinstance(dest, str) or not dest:
        name = meta.get("name", "<unnamed>")
        errors.add(f"{plain(meta['namespace'])}/{name}: Certificate missing secretName")
        return
    writers[plain(meta["namespace"]), dest].append(obj)


def _ingress_refs(
    meta: dict[str, object],
    ns: str,
    spec: dict[str, object],
    bindings: _Bindings,
    errors: set[str],
) -> None:
    """Record the ordinary-host routes and explicit TLS references one Ingress declares."""
    declared = {plain(view(rule).get("host")) for rule in entries(spec.get("rules", []))}
    ordinary = {(ns, host) for host in declared if (ns, host) in bindings["owners"]}
    if not ordinary:
        return
    bindings["routes"].update(ordinary)
    name = meta.get("name", "<unnamed>")
    if len(ordinary) != len(declared):
        errors.add(f"{ns}/{name}: mixed ordinary and undeclared hosts")
    for tls in entries(spec.get("tls", [])):
        binding = view(tls)
        for host in entries(binding.get("hosts", [])):
            secret = binding.get("secretName")
            if (ns, plain(host)) in bindings["owners"] and secret:
                bindings["refs"][plain(host)].add((ns, plain(secret)))


def _host_sources(
    bindings: _Bindings,
    writers: "defaultdict[tuple[str, str], list[dict[str, object]]]",
    by_namespace: "defaultdict[str, set[str]]",
    errors: set[str],
) -> dict[str, str]:
    """Bind each host to one reviewed namespace/secret source or record the reason."""
    sources: dict[str, str] = {}
    for host in sorted({name for _, name in bindings["owners"]}):
        if len(bindings["refs"][host]) != 1:
            errors.add(
                f"{host}: expected one explicit TLS source, found {len(bindings['refs'][host])}"
            )
            continue
        (ref,) = bindings["refs"][host]
        ns, secret = ref
        sources[host] = f"{ns}/{secret}"
        if len(writers[ref]) != 1:
            errors.add(f"{host}: expected one Certificate writer, found {len(writers[ref])}")
            continue
        (cert,) = writers[ref]
        spec = view(cert["spec"])
        if host not in entries(spec.get("dnsNames", [])):
            errors.add(f"{host}: no exact DNS name in Certificate spec")
        if any(
            (ns, plain(name)) not in bindings["owners"]
            for name in entries(spec.get("dnsNames", []))
        ):
            errors.add(f"{host}: Certificate also covers names outside this public owner")
        if not any(
            view(c).get("type") == "Ready"
            and view(c).get("status") == "True"
            and isinstance(view(cert["metadata"]).get("generation"), int)
            and view(c).get("observedGeneration") == view(cert["metadata"]).get("generation")
            for c in entries(view(cert.get("status", {})).get("conditions", []))
        ):
            errors.add(f"{host}: Certificate not Ready")
        by_namespace[ns].add(secret)
    return sources


def _named_get_rules(
    by_namespace: "defaultdict[str, set[str]]", errors: set[str]
) -> dict[str, dict[str, object]]:
    """Build the diagnostic exact-get policy, withheld whenever any error was recorded."""
    return (
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


def inventory(catalog: dict[str, object], objects: list[dict[str, object]]) -> dict[str, object]:
    """Reject ambiguous/missing host bindings and missing or unready certificate writers."""
    bindings = _owners(catalog)
    writers: defaultdict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    by_namespace: defaultdict[str, set[str]] = defaultdict(set)
    errors: set[str] = set()
    for obj in objects:
        kind = obj["kind"]
        if kind not in {"Ingress", "Certificate"}:
            reason = MSG_ONLY_INGRESS_CERT
            raise ValueError(reason)
        meta, spec = view(obj["metadata"]), view(obj["spec"])
        ns = plain(meta["namespace"])
        if kind == "Certificate":
            _certificate_writer(obj, meta, spec, writers, errors)
        elif spec.get("ingressClassName") == "traefik":
            _ingress_refs(meta, ns, spec, bindings, errors)
    errors.update(
        f"missing route owner {ns}/{host}" for ns, host in bindings["owners"] - bindings["routes"]
    )
    return {
        "hostSources": _host_sources(bindings, writers, by_namespace, errors),
        "namedGetRules": _named_get_rules(by_namespace, errors),
        "errors": sorted(errors),
    }


def main() -> int:
    """Inventory the catalog against a stdin Kubernetes List, exiting nonzero on any error."""
    batch = json.load(sys.stdin)
    report = inventory(yaml.safe_load(CATALOG.read_text()), batch["items"])
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(main())
