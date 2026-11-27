"""Offline identity check for cert-manager v1.16.2 solver observations.

A positive result is not a published router, trusted writer, verified endpoint
or authority to contact the ACME server. Never log the input objects.
"""

import re

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
