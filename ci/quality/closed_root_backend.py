"""Compile only ready HTTP Pod destinations for a closed, selector-backed Service.

This is backend assembly, not router authorization: no hostname, TLS material,
public listener, API client, endpoint discovery grant or executable CLI.
"""

from ipaddress import IPv4Address, IPv4Network


def servers(
    service: dict,
    slices: list[dict],
    pods: list[dict],
    *,
    expected: tuple[str, str, int],
    pod_network: IPv4Network,
) -> list[dict]:
    """Accept ordinary numeric HTTP targets only; never trust an address on its own."""
    ns, name, number = expected
    meta, spec = service["metadata"], service["spec"]
    uid = meta.get("uid")
    selector = spec.get("selector")
    if (
        service.get("kind") != "Service"
        or (meta.get("namespace"), meta.get("name")) != (ns, name)
        or not uid
        or not selector
        or spec.get("type", "ClusterIP") != "ClusterIP"
        or spec.get("clusterIP") in (None, "None")
    ):
        raise ValueError("expected selector-backed ClusterIP Service")
    if (
        any(
            k.startswith("traefik.ingress.kubernetes.io/service.")
            for k in meta.get("annotations", {})
        )
        or spec.get("publishNotReadyAddresses")
        or spec.get("internalTrafficPolicy", "Cluster") != "Cluster"
        or spec.get("sessionAffinity", "None") != "None"
    ):
        raise ValueError("unsupported backend semantics")
    ports = [
        p for p in spec["ports"] if p.get("port") == number and p.get("protocol", "TCP") == "TCP"
    ]
    if len(ports) != 1:
        raise ValueError("ambiguous or missing HTTP Service port")
    port = ports[0]
    target = port.get("targetPort", number)
    if (
        port.get("name") != "http"
        or number == 443
        or port.get("appProtocol") not in (None, "http")
        or type(target) is not int
        or not 1 <= target <= 65535
    ):
        raise ValueError("unreviewed backend protocol or target")
    return verified_pod_servers(ns, name, uid, selector, target, slices, pods, pod_network)


def verified_pod_servers(ns, name, uid, selector, target, slices, pods, pod_network):
    """Common ready Pod verification after the caller validates its Service contract."""
    by_uid = {}
    for pod in pods:
        pm = pod["metadata"]
        if pod.get("kind") != "Pod" or pm.get("namespace") != ns or not pm.get("uid"):
            continue
        if pm["uid"] in by_uid:
            raise ValueError("duplicate Pod UID in backend observations")
        by_uid[pm["uid"]] = pod
    urls = set()
    for sl in slices:
        sm = sl["metadata"]
        labels = sm.get("labels", {})
        if sm.get("namespace") != ns or labels.get("kubernetes.io/service-name") != name:
            raise ValueError("unexpected slice in scoped Service observations")
        controllers = [
            (r.get("apiVersion"), r.get("kind"), r.get("name"), r.get("uid"))
            for r in sm.get("ownerReferences", [])
            if r.get("controller") is True
        ]
        if (
            sl.get("kind") != "EndpointSlice"
            or sl.get("addressType") != "IPv4"
            or controllers != [("v1", "Service", name, uid)]
            or labels.get("endpointslice.kubernetes.io/managed-by")
            != "endpointslice-controller.k8s.io"
        ):
            raise ValueError("unverified EndpointSlice provenance")
        matches = [
            p
            for p in sl.get("ports", [])
            if p.get("name") == "http" and p.get("protocol", "TCP") == "TCP"
        ]
        if len(matches) != 1 or matches[0].get("port") != target:
            raise ValueError("unexpected EndpointSlice port")
        for ep in sl.get("endpoints", []):
            conditions = ep.get("conditions", {})
            if conditions.get("ready") is not True or conditions.get("terminating") is True:
                continue
            ref = ep.get("targetRef", {})
            p = by_uid.get(ref.get("uid"))
            if (
                not p
                or ref.get("kind") != "Pod"
                or ref.get("namespace") != ns
                or ref.get("name") != p["metadata"]["name"]
            ):
                raise ValueError("unverified endpoint target")
            pm = p["metadata"]
            status = p.get("status", {})
            if (
                status.get("phase") != "Running"
                or pm.get("deletionTimestamp")
                or p["spec"].get("hostNetwork")
                or any(pm.get("labels", {}).get(k) != v for k, v in selector.items())
                or not any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in status.get("conditions", [])
                )
            ):
                raise ValueError("endpoint does not match an admitted ready Pod")
            addresses = ep.get("addresses", [])
            if not status.get("podIP"):
                raise ValueError("missing observed Pod IP")
            if len(addresses) != 1 or addresses[0] != status["podIP"]:
                raise ValueError("endpoint and Pod IP disagree")
            ip = IPv4Address(addresses[0])
            if (
                ip not in pod_network
                or ip.is_loopback
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_link_local
            ):
                raise ValueError("endpoint outside approved Pod address range")
            urls.add(f"http://{ip}:{target}")
    if not urls:
        raise ValueError("no verified ready Pod endpoints")
    return [{"url": url} for url in sorted(urls)]
