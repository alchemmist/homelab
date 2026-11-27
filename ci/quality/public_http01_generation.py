"""Offline identity check for cert-manager v1.16.2 solver observations.

A positive result is not a published router, trusted writer, verified endpoint
or authority to contact the ACME server. Never log the input objects.
"""

import re
from collections import Counter
from collections.abc import Iterable
from hashlib import sha256
from ipaddress import IPv4Network
from zlib import adler32

from ci.quality.closed_root_backend import entries, plain, verified_pod_servers, view
from ci.quality.public_path_rule import path_rule

_API = "acme.cert-manager.io/v1"
SOLVER_PORT = 8089

Obj = dict[str, object]
Observation = tuple[
    tuple[str, str, str, str],
    Obj | None,
    Obj,
    Obj,
    Obj,
    list[Obj],
]
_TOKEN = re.compile(r"[A-Za-z0-9_-]{22,256}")


def same_presentation(
    expected: tuple[str, str, str, str],
    challenge: Obj | None,
    ingress: Obj,
    service: Obj,
    pod: Obj,
) -> bool:
    """Match (namespace, Challenge name, UID, approved hostname) or refuse.

    Require all three children to name the current generation as controller.
    Callers must separately reject conflicting observations, verify the entire
    backend and require a fresh complete observation before each publication.
    """
    namespace, name, uid, host = expected
    try:
        if not all(v for v in expected) or not challenge:
            return False
        meta = view(challenge["metadata"])
        spec = view(challenge["spec"])
        status = view(challenge["status"])
        if (
            challenge["apiVersion"],
            challenge["kind"],
            meta["namespace"],
            meta["name"],
            meta["uid"],
        ) != (_API, "Challenge", namespace, name, uid) or meta.get("deletionTimestamp") is not None:
            return False
        if (
            spec["type"] != "HTTP-01"
            or spec["dnsName"] != host
            or spec.get("wildcard", False) is not False
            or status.get("processing") is not True
            or status.get("presented") is not True
            or status.get("state") != "pending"
        ):
            return False
        token = spec["token"]
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            return False
        for child, api, kind in [
            (ingress, "networking.k8s.io/v1", "Ingress"),
            (service, "v1", "Service"),
            (pod, "v1", "Pod"),
        ]:
            m = view(child["metadata"])
            if (
                (child["apiVersion"], child["kind"], m["namespace"]) != (api, kind, namespace)
                or m.get("deletionTimestamp") is not None
                or not m.get("uid")
                or not m.get("name")
            ):
                return False
            owners = [
                (view(o)["apiVersion"], view(o)["kind"], view(o)["name"], view(o)["uid"])
                for o in entries(m["ownerReferences"])
                if view(o).get("controller") is True
            ]
            if owners != [(_API, "Challenge", name, uid)]:
                return False
        if (
            view(view(ingress["metadata"]).get("labels", {})).get(
                "homelab.alchemmist.xyz/public-web"
            )
            != "true"
        ):
            return False
        route = view(ingress["spec"])
        backend = view(service["metadata"])["name"]
        return (
            route.get("ingressClassName") == "traefik"
            and not route.get("tls")
            and "defaultBackend" not in route
            and route.get("rules")
            == [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/.well-known/acme-challenge/" + token,
                                "pathType": "ImplementationSpecific",
                                "backend": {
                                    "service": {"name": backend, "port": {"number": SOLVER_PORT}}
                                },
                            }
                        ]
                    },
                }
            ]
        )
    except (AttributeError, KeyError, TypeError):
        return False


def solver_destination(
    expected: tuple[str, str, str, str],
    challenge: Obj | None,
    ingress: Obj,
    service: Obj,
    pod: Obj,
    slices: list[Obj],
    pod_network: IPv4Network,
) -> str | None:
    """Return only one verified Pod URL, never a NodePort, ClusterIP or arbitrary Service.

    Controller labels are consistency checks rather than cryptographic ownership.
    Unknown/incomplete, stale or duplicate observations yield no destination.
    """
    if challenge is None:
        return None
    if not same_presentation(expected, challenge, ingress, service, pod):
        return None
    try:
        spec = view(service["spec"])
        ports = entries(spec["ports"])
        ns, _, _, host = expected
        labels = {
            "acme.cert-manager.io/http01-solver": "true",
            "acme.cert-manager.io/http-domain": str(adler32(host.encode("ascii"))),
            "acme.cert-manager.io/http-token": str(
                adler32(plain(view(challenge["spec"])["token"]).encode("ascii"))
            ),
        }
        if spec.get("selector") != labels or any(
            any(
                view(view(obj["metadata"]).get("labels", {})).get(k) != v for k, v in labels.items()
            )
            for obj in (ingress, service, pod)
        ):
            return None
        if (
            spec.get("type") not in ("ClusterIP", "NodePort")
            or spec.get("clusterIP") in (None, "None")
            or spec.get("publishNotReadyAddresses")
            or len(ports) != 1
        ):
            return None
        port = view(ports[0])
        if (
            port.get("name") != "http"
            or port.get("protocol", "TCP") != "TCP"
            or port.get("port") != SOLVER_PORT
            or port.get("targetPort") != SOLVER_PORT
            or port.get("appProtocol") is not None
        ):
            return None
        if len(slices) != 1:
            return None
        sl = slices[0]
        sm = view(sl["metadata"])
        (ep_node,) = entries(sl["endpoints"])
        (sp_node,) = entries(sl["ports"])
        ep = view(ep_node)
        sp = view(sp_node)
        if (
            sl["apiVersion"] != "discovery.k8s.io/v1"
            or sm.get("deletionTimestamp") is not None
            or not sm.get("uid")
            or view(ep.get("conditions", {})).get("serving") is False
            or view(ep.get("targetRef", {})).get("namespace") != ns
            or sp.get("appProtocol") is not None
        ):
            return None
        (result,) = verified_pod_servers(
            ns,
            plain(view(service["metadata"])["name"]),
            view(service["metadata"])["uid"],
            labels,
            SOLVER_PORT,
            slices,
            [pod],
            pod_network,
        )
        return plain(view(result)["url"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def closed_solver_snapshot(
    expected: tuple[str, str, str, str],
    challenge: Obj | None,
    ingress: Obj,
    service: Obj,
    pod: Obj,
    slices: list[Obj],
    pod_network: IPv4Network,
) -> dict[str, object]:
    """Build one isolated HTTP-only fixture, never replace a shared provider with it.

    Inputs are complete observations for exactly one independently approved
    presentation. Output may contain the challenge path: do not log it.
    No publishing, polling or consumer acknowledgment takes place here.
    """
    routers: Obj = {
        "sentinel": {
            "rule": "Host(`sentinel.invalid`)",
            "entryPoints": ["closed"],
            "service": "noop@internal",
        }
    }
    http: Obj = {"routers": routers}
    dest = solver_destination(expected, challenge, ingress, service, pod, slices, pod_network)
    if dest is not None and challenge is not None:
        try:
            rule = path_rule(
                expected[3],
                "/.well-known/acme-challenge/" + plain(view(challenge["spec"])["token"]),
                "Exact",
            )
        except ValueError:
            return {"http": http}
        routers["proof"] = {
            "rule": rule,
            "entryPoints": ["closed"],
            "service": "solver",
            "observability": {"accessLogs": False, "tracing": False},
        }
        http["services"] = {"solver": {"loadBalancer": {"servers": [{"url": dest}]}}}
    return {"http": http}


def closed_solver_batch(
    observations: Iterable[Observation], pod_network: IPv4Network
) -> dict[str, object]:
    """Dedicated solver file for one complete scan, separate from ordinary routes.

    Never pass an interrupted list as a completed scan. Reserve claims before
    checking destinations, so an invalid backend cannot break a tie. Output
    contains challenge paths and must not be logged. No writer or file I/O.
    """
    rows = list(observations)
    names = Counter[tuple[str, str]]()
    uids = Counter[str]()
    paths = Counter[tuple[str, str]]()
    claims: list[tuple[str, str] | None] = []
    for expected, challenge, *_ in rows:
        ns, name, uid, host = expected
        names[ns, name] += 1
        uids[uid] += 1
        token = (
            view(view(challenge).get("spec", {})).get("token")
            if isinstance(challenge, dict)
            else None
        )
        claim = (host, token) if isinstance(token, str) and _TOKEN.fullmatch(token) else None
        if claim:
            paths[claim] += 1
        claims.append(claim)
    http: Obj = {
        "routers": {
            "acme-fixture-sentinel": {
                "rule": "Host(`sentinel.invalid`)",
                "entryPoints": ["closed"],
                "service": "noop@internal",
            }
        }
    }
    for row, claim in zip(rows, claims, strict=True):
        ns, name, uid, host = row[0]
        if not claim or paths[claim] != 1 or names[ns, name] != 1 or uids[uid] != 1:
            continue
        single = view(view(closed_solver_snapshot(*row, pod_network))["http"])
        proof = view(single["routers"]).get("proof")
        if not proof:
            continue
        key = "acme-fixture-" + sha256(uid.encode()).hexdigest()
        view(http["routers"])[key] = {**view(proof), "service": key}
        services = view(single["services"])
        if "services" not in http:
            http["services"] = {}
        view(http["services"])[key] = view(services)["solver"]
    return {"http": http}
