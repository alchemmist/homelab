"""Inventory backend and middleware dependencies of every ordinary public Ingress.

Rows are diagnostic even on errors: a missing middleware can leave a partial
middlewareBodies list. Never consume routes alone or use a nonempty errors
report to compile or publish a snapshot.
"""

import hashlib
import json
import sys
from collections import defaultdict
from typing import TypedDict
from urllib.parse import urlsplit

import yaml

from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.public_web import CATALOG

PREFIX = "traefik.ingress.kubernetes.io/"
MAX_PORT = 65535
HTTPS_PORT = 443
MSG_UNSUPPORTED_KIND = "unsupported input kind; do not supply Secret objects"


class _Buses(TypedDict):
    """The four labeled item inventories produced by one input classification."""

    ingresses: list[dict[str, object]]
    services: dict[tuple[object, object], dict[str, object]]
    crds: "defaultdict[tuple[str, object], list[dict[str, object]]]"
    slices: "defaultdict[tuple[object, object], list[dict[str, object]]]"


class _RowContext(TypedDict):
    """The per-ingress-row facts one backend row is assembled from."""

    ns: object
    name: object
    host: object
    middlewares: list[str]
    observability: dict[str, bool]
    ann: dict[str, object]


def _fingerprint(spec: dict[str, object]) -> str:
    """Detect body drift without including CRD payloads in reports."""
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _observability(annotations: dict[str, object]) -> tuple[dict[str, bool], bool]:
    """Absence means inherit, not false. Never drop an unrecognized override."""
    prefix = PREFIX + "router.observability."
    fields = {"accesslogs": "accessLogs", "metrics": "metrics", "tracing": "tracing"}
    settings: dict[str, bool] = {}
    valid = True
    for key, value in annotations.items():
        folded = key.lower()
        if folded != prefix[:-1] and not folded.startswith(prefix):
            continue
        field = fields.get(folded.removeprefix(prefix))
        if (
            not field
            or field in settings
            or not isinstance(value, str)
            or value not in ("true", "false")
        ):
            valid = False
            continue
        settings[field] = value == "true"
    return settings, valid


def _middleware_kind(spec: dict[str, object]) -> str | None:
    """Recognize just the two self-contained owner shapes rehearsed so far."""
    if set(spec) == {"forwardAuth"}:
        body = view(spec["forwardAuth"])
        if set(body) != {"address", "trustForwardHeader"}:
            return None
        if body["trustForwardHeader"] is not False or not isinstance(body["address"], str):
            return None
        try:
            url = urlsplit(body["address"])
            if (
                url.scheme == "https"
                and url.hostname
                and url.username is None
                and not url.query
                and not url.fragment
                and url.path.startswith("/")
            ):
                return "forwardAuth"
        except ValueError:
            return None
    if set(spec) == {"redirectRegex"}:
        body = view(spec["redirectRegex"])
        if (
            set(body) == {"regex", "replacement", "permanent"}
            and type(body["permanent"]) is bool
            and all(isinstance(body[k], str) and body[k] for k in ("regex", "replacement"))
        ):
            return "redirectRegex"
    return None


def _malformed_port(raw: object) -> bool:
    """Reject non-int (exactly typed), out-of-bounds or bool-poison port values."""
    return type(raw) is not int or not 1 <= raw <= MAX_PORT


def _classify(items: list[dict[str, object]]) -> _Buses:
    """Route every input item to its bus, refusing Secret-payload kinds entirely."""
    ingresses: list[dict[str, object]] = []
    services: dict[tuple[object, object], dict[str, object]] = {}
    crds: defaultdict[tuple[str, object], list[dict[str, object]]] = defaultdict(list)
    slices: defaultdict[tuple[object, object], list[dict[str, object]]] = defaultdict(list)
    for item in items:
        meta = view(item["metadata"])
        kind = item["kind"]
        ns, name = meta["namespace"], meta["name"]
        if kind == "Ingress":
            ingresses.append(item)
        elif kind == "Service":
            services[ns, name] = item
        elif kind == "EndpointSlice":
            owner = view(meta.get("labels", {})).get("kubernetes.io/service-name")
            slices[ns, owner].append(item)
        elif kind in {"Middleware", "ServersTransport"}:
            crds[plain(kind), f"{ns}-{name}@kubernetescrd"].append(item)
        else:
            reason = MSG_UNSUPPORTED_KIND
            raise ValueError(reason)
    return {"ingresses": ingresses, "services": services, "crds": crds, "slices": slices}


def _middleware_rows(
    ident: str,
    middlewares: list[str],
    crds: "defaultdict[tuple[str, object], list[dict[str, object]]]",
    errors: set[str],
) -> list[dict[str, object]]:
    """Fingerprint every named middleware body recognized as an owner shape."""
    bodies: list[dict[str, object]] = []
    for mw in middlewares:
        if len(crds["Middleware", mw]) != 1:
            errors.add(f"{ident}: middleware missing or ambiguous: {mw}")
            continue
        body = view(crds["Middleware", mw][0]["spec"])
        kind = _middleware_kind(body)
        if not kind:
            errors.add(f"{ident}: unreviewed middleware body: {mw}")
            continue
        bodies.append({"ref": mw, "kind": kind, "sha256": _fingerprint(body)})
    return bodies


def _service_port(
    ident: str,
    service: dict[str, object] | None,
    backend: object,
    selector: object,
    errors: set[str],
) -> dict[str, object] | None:
    """Resolve the single named ClusterIP Service port behind one path target."""
    if (
        not service
        or view(service["spec"]).get("type", "ClusterIP") != "ClusterIP"
        or view(service["spec"]).get("clusterIP") in (None, "None")
    ):
        errors.add(f"{ident}: missing or non-ClusterIP Service {backend}")
        return None
    declared_ports = [view(p) for p in entries(view(service["spec"]).get("ports", []))]
    if any(_malformed_port(port.get("port")) for port in declared_ports):
        errors.add(f"{ident}: malformed Service port on {backend}")
        return None
    ports = [
        port
        for port in declared_ports
        if port.get("protocol", "TCP") == "TCP"
        and (
            selector == {"number": port["port"]}
            or (port.get("name") and selector == {"name": port["name"]})
        )
    ]
    if len(ports) != 1:
        errors.add(f"{ident}: cannot resolve Service port on {backend}")
        return None
    return ports[0]


def _transport_digest(
    ident: str,
    transport: object,
    scheme: object,
    crds: "defaultdict[tuple[str, object], list[dict[str, object]]]",
    errors: set[str],
) -> str | None:
    """Fingerprint the one reviewed ServerName-verified ServersTransport, or None."""
    matches = crds["ServersTransport", transport]
    spec = view(matches[0]["spec"]) if len(matches) == 1 else None
    if (
        spec is None
        or set(spec) - {"serverName", "insecureSkipVerify"}
        or scheme != "https"
        or spec.get("insecureSkipVerify", False) is not False
        or not spec.get("serverName")
    ):
        reason = f"{ident}: missing, ambiguous or unverified backend transport {transport}"
        errors.add(reason)
        return None
    return _fingerprint(spec)


def _ready_backend(
    slices: "defaultdict[tuple[object, object], list[dict[str, object]]]",
    ns: object,
    backend: object,
    port: dict[str, object],
    target_port: object,
) -> bool:
    """Tell whether one ready, matching EndpointSlice backend exists."""
    return any(
        any(
            (view(p).get("name") or "") == (port.get("name") or "")
            and view(p).get("protocol", "TCP") == "TCP"
            and not _malformed_port(view(p).get("port"))
            and (isinstance(target_port, str) or view(p)["port"] == target_port)
            for p in entries(view(sl).get("ports", []))
        )
        and any(
            view(e).get("addresses")
            and view(view(e).get("conditions", {})).get("ready") is True
            and not view(view(e).get("conditions", {})).get("terminating", False)
            for e in entries(view(sl).get("endpoints", []))
        )
        for sl in slices[ns, backend]
    )


def _route_row(
    ident: str,
    raw_port_map: dict[str, object],
    context: _RowContext,
    buses: _Buses,
    errors: set[str],
) -> dict[str, object]:
    """Assemble one backend row, recording every diagnostic along the way."""
    backend_map = view(raw_port_map.get("backend", {}))
    target = view(backend_map.get("service", {}))
    backend = target.get("name")
    selector = target.get("port", {})
    service = buses["services"].get((context["ns"], backend))
    port = _service_port(ident, service, backend, selector, errors)
    if port is None:
        return {}
    sa = view(view(view(service or {})["metadata"]).get("annotations", {}))
    scheme = sa.get(
        PREFIX + "service.serversscheme",
        "https"
        if port["port"] == HTTPS_PORT or str(port.get("name", "")).startswith("https")
        else "http",
    )
    if scheme not in {"http", "https", "h2c"}:
        errors.add(f"{ident}: unsupported backend scheme")
    transport = sa.get(PREFIX + "service.serverstransport")
    transport_digest = None
    if transport:
        transport_digest = _transport_digest(ident, transport, scheme, buses["crds"], errors)
    target_port = port.get("targetPort", port["port"])
    ready = _ready_backend(buses["slices"], context["ns"], backend, port, target_port)
    if not ready:
        errors.add(f"{ident}: no ready EndpointSlice backend for {backend}:{port['port']}")
    return {
        "host": context["host"],
        "path": raw_port_map.get("path"),
        "pathType": raw_port_map.get("pathType"),
        "owner": f"{context['ns']}/{context['name']}",
        "service": f"{context['ns']}/{backend}",
        "port": port["port"],
        "scheme": scheme,
        "transport": transport,
        "middlewares": context["middlewares"],
        "middlewareBodies": _middleware_rows(ident, context["middlewares"], buses["crds"], errors),
        "observability": context["observability"],
        "transportDigest": transport_digest,
        "priority": context["ann"].get(PREFIX + "router.priority"),
        "readyEndpoint": ready,
    }


def inventory(catalog: dict[str, object], items: list[dict[str, object]]) -> dict[str, object]:
    """Resolve references without granting access, reading Secrets or emitting executable config."""
    hosts_view = view(catalog["hosts"])
    owners = {
        (ns, host)
        for ns, names in hosts_view.items()
        for host, policy in view(names).items()
        if view(policy).get("route", "web") == "web"
    }
    buses = _classify(items)
    routes: list[dict[str, object]] = []
    errors: set[str] = set()
    seen: set[tuple[object, object]] = set()
    for ing in buses["ingresses"]:
        meta, spec = view(ing["metadata"]), view(ing["spec"])
        ns, name = meta["namespace"], meta["name"]
        if spec.get("ingressClassName") != "traefik":
            continue
        ann = view(meta.get("annotations", {}))
        observability, observability_valid = _observability(ann)
        middlewares = [
            m.strip()
            for m in str(ann.get(PREFIX + "router.middlewares", "")).split(",")
            if m.strip()
        ]
        for raw_rule in entries(spec.get("rules", [])):
            rule = view(raw_rule)
            host = rule.get("host")
            if (ns, host) not in owners:
                continue
            seen.add((ns, host))
            ident = f"{ns}/{name} {host}"
            if not observability_valid:
                errors.add(f"{ident}: ambiguous or unsupported router observability override")
            paths = entries(view(rule.get("http", {})).get("paths", []))
            if not paths:
                errors.add(f"{ident}: missing HTTP paths")
            context: _RowContext = {
                "ns": ns,
                "name": name,
                "host": host,
                "middlewares": middlewares,
                "observability": observability,
                "ann": ann,
            }
            for raw_path in paths:
                path = view(raw_path)
                if not path.get("path") or path.get("pathType") not in {"Exact", "Prefix"}:
                    errors.add(f"{ident}: missing or controller-specific path semantics")
                row = _route_row(ident, path, context, buses, errors)
                if row:
                    routes.append(row)
    errors.update(f"missing route owner {ns}/{host}" for ns, host in owners - seen)
    return {
        "routes": sorted(routes, key=lambda r: (r["host"], r["path"] or "", r["owner"])),
        "errors": sorted(errors),
    }


def main() -> int:
    """Inventory the catalog against stdin Kubernetes items, exiting nonzero on any error."""
    report = inventory(yaml.safe_load(CATALOG.read_text()), json.load(sys.stdin)["items"])
    print(json.dumps(report, indent=2))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(main())
