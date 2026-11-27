"""Compile only ready HTTP Pod destinations for a closed, selector-backed Service.

This is backend assembly, not router authorization: no hostname, TLS material,
public listener, API client, endpoint discovery grant or executable CLI.
"""

from ipaddress import IPv4Address, IPv4Network

Obj = dict[str, object]

MSG_NOT_A_MAPPING = "observation is not a mapping"
MSG_NOT_A_LIST = "observation is not a list"
MSG_NOT_A_STRING = "expected a string field"

MIN_TARGET_PORT = 1
MAX_TARGET_PORT = 65535
HTTPS_PORT = 443


def view(obj: object) -> Obj:
    """Runtime narrowing of caller-supplied observations to a mapping."""
    if not isinstance(obj, dict):
        raise TypeError(MSG_NOT_A_MAPPING)
    return obj


def entries(obj: object) -> list[object]:
    """Runtime narrowing of caller-supplied observations to a list."""
    if not isinstance(obj, list):
        raise TypeError(MSG_NOT_A_LIST)
    return obj


def plain(value: object) -> str:
    """Runtime narrowing of a caller-supplied field to a string."""
    if not isinstance(value, str):
        raise TypeError(MSG_NOT_A_STRING)
    return value


def servers(
    service: Obj,
    slices: list[Obj],
    pods: list[Obj],
    *,
    expected: tuple[str, str, int],
    pod_network: IPv4Network,
) -> list[Obj]:
    """Accept ordinary numeric HTTP targets only; never trust an address on its own."""
    ns, name, number = expected
    meta, spec = view(service["metadata"]), view(service["spec"])
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
        wrong_service = "expected selector-backed ClusterIP Service"
        raise ValueError(wrong_service)
    if (
        any(
            k.startswith("traefik.ingress.kubernetes.io/service.")
            for k in view(meta.get("annotations", {}))
        )
        or spec.get("publishNotReadyAddresses")
        or spec.get("internalTrafficPolicy", "Cluster") != "Cluster"
        or spec.get("sessionAffinity", "None") != "None"
    ):
        bad_semantics = "unsupported backend semantics"
        raise ValueError(bad_semantics)
    ports = [
        view(p)
        for p in entries(spec["ports"])
        if view(p).get("port") == number and view(p).get("protocol", "TCP") == "TCP"
    ]
    if len(ports) != 1:
        bad_port_count = "ambiguous or missing HTTP Service port"
        raise ValueError(bad_port_count)
    port = ports[0]
    target = port.get("targetPort", number)
    if (
        port.get("name") != "http"
        or number == HTTPS_PORT
        or port.get("appProtocol") not in (None, "http")
        or type(target) is not int
        or not MIN_TARGET_PORT <= target <= MAX_TARGET_PORT
    ):
        scope_error = "unreviewed backend protocol or target"
        raise ValueError(scope_error)
    return verified_pod_servers(ns, name, uid, selector, target, slices, pods, pod_network)


def verified_pod_servers(
    ns: str,
    name: str,
    uid: object,
    selector: object,
    target: int,
    slices: list[Obj],
    pods: list[Obj],
    pod_network: IPv4Network,
) -> list[Obj]:
    """Verify every presented slice endpoint against a ready Pod of the Service."""
    by_uid: dict[object, Obj] = {}
    for pod in pods:
        pm = view(pod["metadata"])
        if pod.get("kind") != "Pod" or pm.get("namespace") != ns or not pm.get("uid"):
            continue
        if pm["uid"] in by_uid:
            duplicate_pod = "duplicate Pod UID in backend observations"
            raise ValueError(duplicate_pod)
        by_uid[pm["uid"]] = pod
    urls: set[str] = set()
    for sl in slices:
        sm = view(sl["metadata"])
        labels = view(sm.get("labels", {}))
        if sm.get("namespace") != ns or labels.get("kubernetes.io/service-name") != name:
            foreign_slice = "unexpected slice in scoped Service observations"
            raise ValueError(foreign_slice)
        controllers = [
            (
                view(r).get("apiVersion"),
                view(r).get("kind"),
                view(r).get("name"),
                view(r).get("uid"),
            )
            for r in entries(sm.get("ownerReferences", []))
            if view(r).get("controller") is True
        ]
        if (
            sl.get("kind") != "EndpointSlice"
            or sl.get("addressType") != "IPv4"
            or controllers != [("v1", "Service", name, uid)]
            or labels.get("endpointslice.kubernetes.io/managed-by")
            != "endpointslice-controller.k8s.io"
        ):
            bad_provenance = "unverified EndpointSlice provenance"
            raise ValueError(bad_provenance)
        matches = [
            view(p)
            for p in entries(sl.get("ports", []))
            if view(p).get("name") == "http" and view(p).get("protocol", "TCP") == "TCP"
        ]
        if len(matches) != 1 or matches[0].get("port") != target:
            bad_port = "unexpected EndpointSlice port"
            raise ValueError(bad_port)
        for node in entries(sl.get("endpoints", [])):
            ep = view(node)
            conditions = view(ep.get("conditions", {}))
            if conditions.get("ready") is not True or conditions.get("terminating") is True:
                continue
            ref = view(ep.get("targetRef", {}))
            p = by_uid.get(ref.get("uid"))
            if (
                not p
                or ref.get("kind") != "Pod"
                or ref.get("namespace") != ns
                or ref.get("name") != view(p["metadata"]).get("name")
            ):
                bad_target = "unverified endpoint target"
                raise ValueError(bad_target)
            pm = view(p["metadata"])
            status = view(p.get("status", {}))
            if (
                status.get("phase") != "Running"
                or pm.get("deletionTimestamp")
                or view(p["spec"]).get("hostNetwork")
                or any(view(pm.get("labels", {})).get(k) != v for k, v in view(selector).items())
                or not any(
                    view(c).get("type") == "Ready" and view(c).get("status") == "True"
                    for c in entries(status.get("conditions", []))
                )
            ):
                nonready = "endpoint does not match an admitted ready Pod"
                raise ValueError(nonready)
            addresses = entries(ep.get("addresses", []))
            if not status.get("podIP"):
                no_ip = "missing observed Pod IP"
                raise ValueError(no_ip)
            if len(addresses) != 1 or addresses[0] != status["podIP"]:
                ip_conflict = "endpoint and Pod IP disagree"
                raise ValueError(ip_conflict)
            ip = IPv4Address(plain(addresses[0]))
            if (
                ip not in pod_network
                or ip.is_loopback
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_link_local
            ):
                bad_range = "endpoint outside approved Pod address range"
                raise ValueError(bad_range)
            urls.add(f"http://{ip}:{target}")
    if not urls:
        empty_backend = "no verified ready Pod endpoints"
        raise ValueError(empty_backend)
    return [{"url": url} for url in sorted(urls)]
