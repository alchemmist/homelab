"""Offline identity check for cert-manager v1.16.2 solver observations.

A positive result is not a published router, trusted writer, verified endpoint
or authority to contact the ACME server. Never log the input objects.
"""

import re
from ipaddress import IPv4Network
from zlib import adler32

from ci.quality.closed_root_backend import verified_pod_servers
from ci.quality.public_path_rule import path_rule

_API = "acme.cert-manager.io/v1"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{22,256}")


def same_presentation(
    expected: tuple[str, str, str, str],
    challenge: dict | None,
    ingress: dict,
    service: dict,
    pod: dict,
) -> bool:
    """Match (namespace, Challenge name, UID, approved hostname) or refuse.

    Require all three children to name the current generation as controller.
    Callers must separately reject conflicting observations, verify the entire
    backend and require a fresh complete observation before each publication.
    """
    namespace, name, uid, host = expected
    try:
        if not all(isinstance(v, str) and v for v in expected) or not challenge:
            return False
        meta = challenge["metadata"]
        spec = challenge["spec"]
        status = challenge["status"]
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
            m = child["metadata"]
            if (
                (child["apiVersion"], child["kind"], m["namespace"]) != (api, kind, namespace)
                or m.get("deletionTimestamp") is not None
                or not m.get("uid")
                or not m.get("name")
            ):
                return False
            owners = [
                (o["apiVersion"], o["kind"], o["name"], o["uid"])
                for o in m["ownerReferences"]
                if o.get("controller") is True
            ]
            if owners != [(_API, "Challenge", name, uid)]:
                return False
        if ingress["metadata"].get("labels", {}).get("homelab.alchemmist.xyz/public-web") != "true":
            return False
        route = ingress["spec"]
        backend = service["metadata"]["name"]
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
                                "backend": {"service": {"name": backend, "port": {"number": 8089}}},
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
    challenge: dict | None,
    ingress: dict,
    service: dict,
    pod: dict,
    slices: list[dict],
    pod_network: IPv4Network,
) -> str | None:
    """Return only one verified Pod URL, never a NodePort, ClusterIP or arbitrary Service.

    Controller labels are consistency checks rather than cryptographic ownership.
    Unknown/incomplete, stale or duplicate observations yield no destination.
    """
    if not same_presentation(expected, challenge, ingress, service, pod):
        return None
    try:
        spec = service["spec"]
        ports = spec["ports"]
        ns, _, _, host = expected
        labels = {
            "acme.cert-manager.io/http01-solver": "true",
            "acme.cert-manager.io/http-domain": str(adler32(host.encode("ascii"))),
            "acme.cert-manager.io/http-token": str(
                adler32(challenge["spec"]["token"].encode("ascii"))
            ),
        }
        if spec.get("selector") != labels or any(
            any(obj["metadata"].get("labels", {}).get(k) != v for k, v in labels.items())
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
        port = ports[0]
        if (
            port.get("name") != "http"
            or port.get("protocol", "TCP") != "TCP"
            or port.get("port") != 8089
            or port.get("targetPort") != 8089
            or port.get("appProtocol") is not None
        ):
            return None
        if len(slices) != 1:
            return None
        sl = slices[0]
        sm = sl["metadata"]
        (ep,) = sl["endpoints"]
        (sp,) = sl["ports"]
        if (
            sl["apiVersion"] != "discovery.k8s.io/v1"
            or sm.get("deletionTimestamp") is not None
            or not sm.get("uid")
            or ep.get("conditions", {}).get("serving") is False
            or ep.get("targetRef", {}).get("namespace") != ns
            or sp.get("appProtocol") is not None
        ):
            return None
        (result,) = verified_pod_servers(
            ns,
            service["metadata"]["name"],
            service["metadata"]["uid"],
            labels,
            8089,
            slices,
            [pod],
            pod_network,
        )
        return result["url"]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def closed_solver_snapshot(expected, challenge, ingress, service, pod, slices, pod_network) -> dict:
    """Build one isolated HTTP-only fixture, never replace a shared provider with it.

    Inputs are complete observations for exactly one independently approved
    presentation. Output may contain the challenge path: do not log it.
    No publishing, polling or consumer acknowledgment takes place here.
    """
    routers = {
        "sentinel": {
            "rule": "Host(`sentinel.invalid`)",
            "entryPoints": ["closed"],
            "service": "noop@internal",
        }
    }
    http = {"routers": routers}
    dest = solver_destination(expected, challenge, ingress, service, pod, slices, pod_network)
    if dest is not None:
        try:
            rule = path_rule(
                expected[3], "/.well-known/acme-challenge/" + challenge["spec"]["token"], "Exact"
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


def closed_solver_batch(observations, pod_network: IPv4Network) -> dict:
    """Dedicated solver file for one complete scan, separate from ordinary routes.

    Never pass an interrupted list as a completed scan. Reserve claims before
    checking destinations, so an invalid backend cannot break a tie. Output
    contains challenge paths and must not be logged. No writer or file I/O.
    """
    from collections import Counter
    from hashlib import sha256

    entries = list(observations)
    names = Counter()
    uids = Counter()
    paths = Counter()
    claims = []
    for expected, challenge, *_ in entries:
        ns, name, uid, host = expected
        names[ns, name] += 1
        uids[uid] += 1
        token = challenge.get("spec", {}).get("token") if isinstance(challenge, dict) else None
        claim = (host, token) if isinstance(token, str) and _TOKEN.fullmatch(token) else None
        if claim:
            paths[claim] += 1
        claims.append(claim)
    http = {
        "routers": {
            "acme-fixture-sentinel": {
                "rule": "Host(`sentinel.invalid`)",
                "entryPoints": ["closed"],
                "service": "noop@internal",
            }
        }
    }
    for row, claim in zip(entries, claims, strict=True):
        ns, name, uid, host = row[0]
        if not claim or paths[claim] != 1 or names[ns, name] != 1 or uids[uid] != 1:
            continue
        single = closed_solver_snapshot(*row, pod_network)["http"]
        proof = single["routers"].get("proof")
        if not proof:
            continue
        key = "acme-fixture-" + sha256(uid.encode()).hexdigest()
        http["routers"][key] = {**proof, "service": key}
        http.setdefault("services", {})[key] = single["services"]["solver"]
    return {"http": http}
