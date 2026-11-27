"""Inventory the backend and middleware dependencies of every ordinary public Ingress."""

import hashlib
import json
import sys
from collections import defaultdict
from urllib.parse import urlsplit

import yaml

from ci.quality.public_web import CATALOG

PREFIX = "traefik.ingress.kubernetes.io/"


def _fingerprint(spec: dict) -> str:
    """Detect body drift without including CRD payloads in reports."""
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _middleware_kind(spec: dict) -> str | None:
    """Recognize just the two self-contained owner shapes rehearsed so far."""
    if set(spec) == {"forwardAuth"}:
        body = spec["forwardAuth"]
        if not isinstance(body, dict) or set(body) != {"address", "trustForwardHeader"}:
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
        body = spec["redirectRegex"]
        if (
            isinstance(body, dict)
            and set(body) == {"regex", "replacement", "permanent"}
            and type(body["permanent"]) is bool
            and all(isinstance(body[k], str) and body[k] for k in ("regex", "replacement"))
        ):
            return "redirectRegex"
    return None


def inventory(catalog: dict, items: list[dict]) -> dict:
    """Resolve references without granting access, reading Secrets or emitting executable config."""
    owners = {
        (n, h)
        for n, names in catalog["hosts"].items()
        for h, p in names.items()
        if p.get("route", "web") == "web"
    }
    services = {}
    crds = defaultdict(list)
    slices = defaultdict(list)
    ingresses = []
    for item in items:
        meta, kind = item["metadata"], item["kind"]
        ns, name = meta["namespace"], meta["name"]
        if kind == "Ingress":
            ingresses.append(item)
        elif kind == "Service":
            services[ns, name] = item
        elif kind == "EndpointSlice":
            slices[ns, meta.get("labels", {}).get("kubernetes.io/service-name")].append(item)
        elif kind in {"Middleware", "ServersTransport"}:
            crds[kind, f"{ns}-{name}@kubernetescrd"].append(item)
        else:
            raise ValueError("unsupported input kind; do not supply Secret objects")
    routes = []
    errors = set()
    seen = set()
    for ing in ingresses:
        meta, spec = ing["metadata"], ing["spec"]
        ns, name = meta["namespace"], meta["name"]
        if spec.get("ingressClassName") != "traefik":
            continue
        ann = meta.get("annotations", {})
        middlewares = [
            m.strip() for m in ann.get(PREFIX + "router.middlewares", "").split(",") if m.strip()
        ]
        for rule in spec.get("rules", []):
            host = rule.get("host")
            if (ns, host) not in owners:
                continue
            seen.add((ns, host))
            ident = f"{ns}/{name} {host}"
            middleware_bodies = []
            for mw in middlewares:
                if len(crds["Middleware", mw]) != 1:
                    errors.add(f"{ident}: middleware missing or ambiguous: {mw}")
                    continue
                body = crds["Middleware", mw][0]["spec"]
                kind = _middleware_kind(body)
                if not kind:
                    errors.add(f"{ident}: unreviewed middleware body: {mw}")
                    continue
                middleware_bodies.append({"ref": mw, "kind": kind, "sha256": _fingerprint(body)})
            paths = rule.get("http", {}).get("paths", [])
            if not paths:
                errors.add(f"{ident}: missing HTTP paths")
            for path in paths:
                if not path.get("path") or path.get("pathType") not in {"Exact", "Prefix"}:
                    errors.add(f"{ident}: missing or controller-specific path semantics")
                target = path.get("backend", {}).get("service", {})
                backend = target.get("name")
                svc = services.get((ns, backend))
                if (
                    not svc
                    or svc["spec"].get("type", "ClusterIP") != "ClusterIP"
                    or svc["spec"].get("clusterIP") in (None, "None")
                ):
                    errors.add(f"{ident}: missing or non-ClusterIP Service {backend}")
                    continue
                selector = target.get("port", {})
                ports = [
                    p
                    for p in svc["spec"].get("ports", [])
                    if p.get("protocol", "TCP") == "TCP"
                    and (
                        selector == {"number": p["port"]}
                        or (p.get("name") and selector == {"name": p["name"]})
                    )
                ]
                if len(ports) != 1:
                    errors.add(f"{ident}: cannot resolve Service port on {backend}")
                    continue
                (port,) = ports
                sa = svc["metadata"].get("annotations", {})
                scheme = sa.get(
                    PREFIX + "service.serversscheme",
                    "https"
                    if port["port"] == 443 or port.get("name", "").startswith("https")
                    else "http",
                )
                if scheme not in {"http", "https", "h2c"}:
                    errors.add(f"{ident}: unsupported backend scheme")
                transport = sa.get(PREFIX + "service.serverstransport")
                transport_digest = None
                if transport:
                    matches = crds["ServersTransport", transport]
                    if (
                        len(matches) != 1
                        or set(matches[0]["spec"]) - {"serverName", "insecureSkipVerify"}
                        or scheme != "https"
                        or matches[0]["spec"].get("insecureSkipVerify", False) is not False
                        or not matches[0]["spec"].get("serverName")
                    ):
                        errors.add(
                            f"{ident}: missing, ambiguous or unverified backend transport {transport}"
                        )
                    else:
                        transport_digest = _fingerprint(matches[0]["spec"])
                target_port = port.get("targetPort", port["port"])
                ready = any(
                    any(
                        (p.get("name") or "") == (port.get("name") or "")
                        and p.get("protocol", "TCP") == "TCP"
                        and type(p.get("port")) is int
                        and 1 <= p["port"] <= 65535
                        and (isinstance(target_port, str) or p["port"] == target_port)
                        for p in sl.get("ports", [])
                    )
                    and any(
                        e.get("addresses")
                        and e.get("conditions", {}).get("ready") is True
                        and not e.get("conditions", {}).get("terminating", False)
                        for e in sl.get("endpoints", [])
                    )
                    for sl in slices[ns, backend]
                )
                if not ready:
                    errors.add(
                        f"{ident}: no ready EndpointSlice backend for {backend}:{port['port']}"
                    )
                routes.append(
                    {
                        "host": host,
                        "path": path.get("path"),
                        "pathType": path.get("pathType"),
                        "owner": f"{ns}/{name}",
                        "service": f"{ns}/{backend}",
                        "port": port["port"],
                        "scheme": scheme,
                        "transport": transport,
                        "middlewares": middlewares,
                        "middlewareBodies": middleware_bodies,
                        "transportDigest": transport_digest,
                        "priority": ann.get(PREFIX + "router.priority"),
                        "readyEndpoint": ready,
                    }
                )
    errors.update(f"missing route owner {n}/{h}" for n, h in owners - seen)
    return {
        "routes": sorted(routes, key=lambda r: (r["host"], r["path"] or "", r["owner"])),
        "errors": sorted(errors),
    }


def main() -> int:
    report = inventory(yaml.safe_load(CATALOG.read_text()), json.load(sys.stdin)["items"])
    print(json.dumps(report, indent=2))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(main())
