"""Offline checks for the HTTP-01 solver observer chain; no cluster required."""

import copy
import time
from collections.abc import Callable
from ipaddress import IPv4Network
from zlib import adler32

import pytest

from ci.quality.public_http01_generation import Observation, same_presentation
from ci.quality.public_http01_lease_scan import Presentation, ScannedSlot
from ci.quality.public_http01_scan import IncompleteScan, scan_namespace

Ref = tuple[str, str, str, str]
Doc = dict[str, object]
Page = tuple[int, Doc]
Children = tuple[Doc, Doc, Doc, list[Doc]]
ReadPage = Callable[[str, str], Page]
ReadChildren = Callable[[Doc], Children]

POD_NETWORK = "10.42.0.0/16"
SOLVER_URL = "http://10.42.2.9:8089"
SOLVER_SERVICE_COUNT = 2
WAIT_SECONDS = 5
RENEWAL_WINDOW = 10
ADDRESS_WINDOW = 10**10
GATE_WINDOW = 10**11


def step(current: object, key: str | int) -> object:
    """Take one keyed hop inside a fixture, map or list, nothing else."""
    if isinstance(current, dict) and isinstance(key, str):
        return current[key]
    assert isinstance(current, list)
    assert isinstance(key, int)
    return current[key]


def container(obj: object, *path: str | int) -> Doc:
    """Navigate a fixture to a mapping; the fixtures are fully built in here."""
    current: object = obj
    for key in path:
        current = step(current, key)
    assert isinstance(current, dict)
    return current


def value_at(obj: object, *path: str | int) -> object:
    """Navigate a fixture to a single value; fixtures are owned by this module."""
    current: object = obj
    for key in path:
        current = step(current, key)
    return current


def text(obj: object, *path: str | int) -> str:
    """Read a fixture string located at the given path."""
    value = value_at(obj, *path)
    assert isinstance(value, str)
    return value


def sequence(obj: object, *path: str | int) -> list[object]:
    """Navigate a fixture to a list; fixtures are owned by this module."""
    current: object = obj
    for key in path:
        current = step(current, key)
    assert isinstance(current, list)
    return current


def poke(obj: object, path: tuple[str | int, ...], *, value: object) -> None:
    """Set a nested fixture value without widening local annotations."""
    parent: object = obj
    for key in path[:-1]:
        parent = step(parent, key)
    last = path[-1]
    if isinstance(parent, dict) and isinstance(last, str):
        parent[last] = value
    else:
        assert isinstance(parent, list)
        assert isinstance(last, int)
        parent[last] = value


def fixture(uid: str) -> tuple[Ref, Doc, Doc, Doc, Doc]:
    ns, name, host = "owner", "challenge", "probe.invalid"
    owner = {
        "apiVersion": "acme.cert-manager.io/v1",
        "kind": "Challenge",
        "name": name,
        "uid": uid,
        "controller": True,
    }
    token = "A" * 43
    challenge: Doc = {
        "apiVersion": owner["apiVersion"],
        "kind": "Challenge",
        "metadata": {"namespace": ns, "name": name, "uid": uid},
        "spec": {"dnsName": host, "type": "HTTP-01", "token": token},
        "status": {"state": "pending", "presented": True, "processing": True},
    }
    children: list[Doc] = [
        {
            "apiVersion": api,
            "kind": kind,
            "metadata": {
                "name": n,
                "uid": uid + "-" + n,
                "namespace": ns,
                "ownerReferences": [copy.deepcopy(owner)],
            },
        }
        for api, kind, n in [
            ("networking.k8s.io/v1", "Ingress", "ing"),
            ("v1", "Service", "svc"),
            ("v1", "Pod", "pod"),
        ]
    ]
    assert isinstance(children[0]["metadata"], dict)
    children[0]["metadata"]["labels"] = {"homelab.alchemmist.xyz/public-web": "true"}
    children[0]["spec"] = {
        "ingressClassName": "traefik",
        "rules": [
            {
                "host": host,
                "http": {
                    "paths": [
                        {
                            "path": "/.well-known/acme-challenge/" + token,
                            "pathType": "ImplementationSpecific",
                            "backend": {"service": {"name": "svc", "port": {"number": 8089}}},
                        }
                    ]
                },
            }
        ],
    }
    return (ns, name, uid, host), challenge, children[0], children[1], children[2]


INGRESS, SERVICE, POD = 2, 3, 4


@pytest.mark.parametrize("index", [INGRESS, SERVICE, POD])
def test_same_name_recreation_never_reuses_an_old_child(index: int) -> None:
    before = fixture("first")
    after = fixture("next")
    assert same_presentation(*before)
    assert same_presentation(*after)
    mixed_ing = before[2] if index == INGRESS else after[2]
    mixed_svc = before[3] if index == SERVICE else after[3]
    mixed_pod = before[4] if index == POD else after[4]
    assert not same_presentation(after[0], after[1], mixed_ing, mixed_svc, mixed_pod)
    assert not same_presentation(before[0], after[1], mixed_ing, mixed_svc, mixed_pod)
    assert not same_presentation(after[0], None, before[2], before[3], before[4])


def _reject_deleting_challenge(ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc) -> None:
    container(ch, "metadata")["deletionTimestamp"] = "deleting"


def _reject_valid_challenge(ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc) -> None:
    container(ch, "status")["state"] = "valid"


def _reject_unpresented_challenge(ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc) -> None:
    container(ch, "status")["presented"] = False


def _reject_other_hostname(ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc) -> None:
    container(ch, "spec")["dnsName"] = "else.invalid"


def _reject_foreign_peer(_ch: Doc, _ing: Doc, _svc: Doc, pod: Doc) -> None:
    container(pod, "metadata")["namespace"] = "other"


def _reject_other_token(_ch: Doc, ing: Doc, _svc: Doc, _pod: Doc) -> None:
    route = text(ing, "spec", "rules", 0, "http", "paths", 0, "path") + "x"
    poke(ing, ("spec", "rules", 0, "http", "paths", 0, "path"), value=route)


def _reject_extra_route_path(_ch: Doc, ing: Doc, _svc: Doc, _pod: Doc) -> None:
    paths = sequence(ing, "spec", "rules", 0, "http", "paths")
    first = paths[0]
    assert isinstance(first, dict)
    paths.append(first.copy())


def _reject_second_controller(_ch: Doc, _ing: Doc, svc: Doc, _pod: Doc) -> None:
    refs = container(svc, "metadata")["ownerReferences"]
    assert isinstance(refs, list)
    container(svc, "metadata")["ownerReferences"] = refs * 2


def _reject_other_ingress_class(_ch: Doc, ing: Doc, _svc: Doc, _pod: Doc) -> None:
    container(ing, "spec")["ingressClassName"] = "private"


def _reject_selector_labels(_ch: Doc, ing: Doc, _svc: Doc, _pod: Doc) -> None:
    container(ing, "metadata")["labels"] = {}


def _reject_other_backend_service(_ch: Doc, ing: Doc, _svc: Doc, _pod: Doc) -> None:
    poke(
        ing,
        ("spec", "rules", 0, "http", "paths", 0, "backend", "service", "name"),
        value="other",
    )


def _reject_other_backend_port(_ch: Doc, ing: Doc, _svc: Doc, _pod: Doc) -> None:
    poke(
        ing,
        (
            "spec",
            "rules",
            0,
            "http",
            "paths",
            0,
            "backend",
            "service",
            "port",
            "number",
        ),
        value=80,
    )


def _reject_default_backend(_ch: Doc, ing: Doc, _svc: Doc, _pod: Doc) -> None:
    container(ing, "spec")["defaultBackend"] = {}


PRESENTATION_FAULTS: dict[str, Callable[[Doc, Doc, Doc, Doc], None]] = {
    "deleting": _reject_deleting_challenge,
    "valid": _reject_valid_challenge,
    "not-presented": _reject_unpresented_challenge,
    "other-name": _reject_other_hostname,
    "other-peer": _reject_foreign_peer,
    "token": _reject_other_token,
    "extra-path": _reject_extra_route_path,
    "extra-controller": _reject_second_controller,
    "class": _reject_other_ingress_class,
    "selector": _reject_selector_labels,
    "other-service": _reject_other_backend_service,
    "other-port": _reject_other_backend_port,
    "default": _reject_default_backend,
}


@pytest.mark.parametrize("fault", sorted(PRESENTATION_FAULTS))
def test_inactive_or_unrelated_observations_cannot_present(fault: str) -> None:
    expected, ch, ing, svc, pod = fixture("current")
    PRESENTATION_FAULTS[fault](ch, ing, svc, pod)
    assert not same_presentation(expected, ch, ing, svc, pod)


def destination_fixture(
    uid: str = "now", token: str | None = None
) -> tuple[Ref, Doc, Doc, Doc, Doc, list[Doc]]:
    expected, ch, ing, svc, pod = fixture(uid)
    ns, _, _, host = expected
    if token is not None:
        container(ch, "spec")["token"] = token
        challenge_path = container(ing, "spec", "rules", 0, "http", "paths", 0)
        challenge_path["path"] = "/.well-known/acme-challenge/" + token
        expected = (ns, "challenge-" + uid, uid, host)
        container(ch, "metadata")["name"] = expected[1]
        for child in (ing, svc, pod):
            poke(child, ("metadata", "ownerReferences", 0, "name"), value=expected[1])
    ip = "10.42.2.9"
    selector = {
        "acme.cert-manager.io/http01-solver": "true",
        "acme.cert-manager.io/http-domain": str(adler32(host.encode())),
        "acme.cert-manager.io/http-token": str(adler32(text(ch, "spec", "token").encode())),
    }
    for child in (ing, svc, pod):
        assert isinstance(child["metadata"], dict)
        labels = child["metadata"].setdefault("labels", {})
        assert isinstance(labels, dict)
        labels.update(selector)
    assert isinstance(svc["metadata"], dict)
    svc["spec"] = {
        "type": "NodePort",
        "clusterIP": "10.43.22.11",
        "ports": [{"name": "http", "port": 8089, "targetPort": 8089, "nodePort": 32123}],
        "selector": selector,
    }
    pod["spec"] = {}
    pod["status"] = {
        "phase": "Running",
        "podIP": ip,
        "conditions": [{"type": "Ready", "status": "True"}],
    }
    sl: Doc = {
        "apiVersion": "discovery.k8s.io/v1",
        "kind": "EndpointSlice",
        "metadata": {
            "uid": "sl",
            "name": "solver-abc",
            "namespace": ns,
            "labels": {
                "kubernetes.io/service-name": "svc",
                "endpointslice.kubernetes.io/managed-by": "endpointslice-controller.k8s.io",
            },
            "ownerReferences": [
                {
                    "apiVersion": "v1",
                    "kind": "Service",
                    "controller": True,
                    "name": "svc",
                    "uid": text(svc, "metadata", "uid"),
                }
            ],
        },
        "addressType": "IPv4",
        "ports": [{"name": "http", "port": 8089}],
        "endpoints": [
            {
                "addresses": [ip],
                "targetRef": {
                    "kind": "Pod",
                    "name": "pod",
                    "uid": text(pod, "metadata", "uid"),
                    "namespace": ns,
                },
                "conditions": {"ready": True},
            }
        ],
    }
    return expected, ch, ing, svc, pod, [sl]


def _admit_no_override(_ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, _slices: list[Doc]) -> None:
    return None


def _reject_stale_slice_owner(_ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]) -> None:
    poke(container(slices[0], "metadata"), ("ownerReferences", 0, "uid"), value="old")


def _reject_stale_endpoint_target(
    _ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]
) -> None:
    poke(container(slices[0], "endpoints", 0), ("targetRef", "uid"), value="old")


def _reject_substituted_pod_ip(
    _ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]
) -> None:
    container(slices[0], "endpoints", 0)["addresses"] = ["10.42.2.8"]


def _reject_node_network_ip(_ch: Doc, _ing: Doc, _svc: Doc, pod: Doc, slices: list[Doc]) -> None:
    container(slices[0], "endpoints", 0)["addresses"] = ["10.250.0.2"]
    container(pod, "status")["podIP"] = "10.250.0.2"


def _reject_host_network_pod(_ch: Doc, _ing: Doc, _svc: Doc, pod: Doc, _slices: list[Doc]) -> None:
    pod["spec"] = {"hostNetwork": True}


def _reject_deleting_slice(_ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]) -> None:
    container(slices[0], "metadata")["deletionTimestamp"] = "now"


def _reject_duplicate_slice(_ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]) -> None:
    slices.append(slices[0])


def _reject_ambiguous_target_port(
    _ch: Doc, _ing: Doc, svc: Doc, _pod: Doc, _slices: list[Doc]
) -> None:
    poke(svc, ("spec", "ports", 0, "targetPort"), value=32123)


def _reject_wrong_solver_label(
    _ch: Doc, _ing: Doc, _svc: Doc, pod: Doc, _slices: list[Doc]
) -> None:
    poke(pod, ("metadata", "labels", "acme.cert-manager.io/http-token"), value="other")


def _reject_not_serving(_ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]) -> None:
    poke(container(slices[0], "endpoints", 0), ("conditions", "serving"), value=False)


def _reject_terminating(_ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]) -> None:
    poke(container(slices[0], "endpoints", 0), ("conditions", "terminating"), value=True)


def _reject_udp_port(_ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, slices: list[Doc]) -> None:
    container(slices[0], "ports", 0)["protocol"] = "UDP"


def _reject_newer_generation(ch: Doc, _ing: Doc, _svc: Doc, _pod: Doc, _slices: list[Doc]) -> None:
    container(ch, "metadata")["uid"] = "next"


def _reject_not_ready_pod(_ch: Doc, _ing: Doc, _svc: Doc, pod: Doc, _slices: list[Doc]) -> None:
    container(pod, "status")["conditions"] = []


DESTINATION_FAULTS: dict[str, Callable[[Doc, Doc, Doc, Doc, list[Doc]], None]] = {
    "none": _admit_no_override,
    "old-service": _reject_stale_slice_owner,
    "old-pod": _reject_stale_endpoint_target,
    "substitute-ip": _reject_substituted_pod_ip,
    "node-address": _reject_node_network_ip,
    "host-network": _reject_host_network_pod,
    "deleting-slice": _reject_deleting_slice,
    "second-slice": _reject_duplicate_slice,
    "wrong-target": _reject_ambiguous_target_port,
    "wrong-label": _reject_wrong_solver_label,
    "not-serving": _reject_not_serving,
    "terminating": _reject_terminating,
    "udp": _reject_udp_port,
    "wrong-generation": _reject_newer_generation,
    "not-ready": _reject_not_ready_pod,
}


@pytest.mark.parametrize("fault", sorted(DESTINATION_FAULTS))
def test_only_verified_solver_pod_address_is_admitted(fault: str) -> None:
    from ci.quality.public_http01_generation import solver_destination

    expected, ch, ing, svc, pod, slices = destination_fixture()
    DESTINATION_FAULTS[fault](ch, ing, svc, pod, slices)
    destination = solver_destination(
        (expected, ch, ing, svc, pod, slices), pod_network=IPv4Network(POD_NETWORK)
    )
    assert destination == (SOLVER_URL if fault == "none" else None)


def test_closed_snapshot_never_encodes_empty_services_on_withdrawal() -> None:
    from ci.quality.public_http01_generation import closed_solver_snapshot

    expected, ch, ing, svc, pod, slices = destination_fixture()
    network = IPv4Network(POD_NETWORK)
    baseline = closed_solver_snapshot((expected, ch, ing, svc, pod, slices), pod_network=network)
    http = container(baseline, "http")
    services = http["services"]
    assert services == {"solver": {"loadBalancer": {"servers": [{"url": SOLVER_URL}]}}}
    proof = container(http, "routers", "proof")
    token = text(ch, "spec", "token")
    assert proof["rule"] == (
        f"Host(`probe.invalid`) && Path(`/.well-known/acme-challenge/{token}`)"
    )
    assert proof["observability"] == {"accessLogs": False, "tracing": False}
    poke(container(slices[0], "endpoints", 0), ("targetRef", "uid"), value="stale")
    withdrawn = closed_solver_snapshot((expected, ch, ing, svc, pod, slices), pod_network=network)
    assert withdrawn == {
        "http": {
            "routers": {
                "sentinel": {
                    "rule": "Host(`sentinel.invalid`)",
                    "entryPoints": ["closed"],
                    "service": "noop@internal",
                }
            }
        }
    }
    routers = container(baseline, "http", "routers")
    assert routers.keys() == {"proof", "sentinel"}
    assert (
        closed_solver_snapshot((expected, None, ing, svc, pod, slices), pod_network=network)
        == withdrawn
    )


def test_batch_withdrawal_is_local_and_ambiguous_claims_never_choose_a_winner() -> None:
    from ci.quality.public_http01_generation import closed_solver_batch

    net = IPv4Network(POD_NETWORK)
    a = destination_fixture("first", "A" * 43)
    b = destination_fixture("second", "B" * 43)

    def snapshot(*rows: Observation) -> Doc:
        return container(closed_solver_batch(rows, net), "http")

    both = snapshot(a, b)
    assert both == snapshot(b, a)
    assert len(container(both, "services")) == SOLVER_SERVICE_COUNT
    stale = copy.deepcopy(a)
    poke(container(stale[-1][0], "endpoints", 0), ("targetRef", "uid"), value="old")
    assert snapshot(stale, b) == snapshot(b)
    assert snapshot(a, b, destination_fixture("third", "A" * 43)) == snapshot(b)
    assert snapshot(a, stale, b) == snapshot(b)
    assert snapshot() == snapshot(stale)
    assert "services" not in snapshot()


def list_page(
    items: tuple[Doc, ...] | list[Doc] = (),
    cursor: str = "",
    version: str = "opaque-rv",
) -> Page:
    return 200, {
        "apiVersion": "acme.cert-manager.io/v1",
        "kind": "ChallengeList",
        "metadata": {"resourceVersion": version, "continue": cursor},
        "items": list(items),
    }


def test_scan_completes_pagination_before_resolving_children_or_emitting_empty_file() -> None:
    a = destination_fixture("a", "A" * 43)
    b = destination_fixture("b", "B" * 43)
    calls: list[object] = []

    def run(pages: dict[str, Page]) -> Doc:
        def read(ns: str, cursor: str) -> Page:
            calls.append((ns, cursor))
            return pages[cursor]

        def children(item: Doc) -> Children:
            calls.append(container(item, "metadata")["uid"])
            return (a if item is a[1] else b)[2:]

        return container(
            scan_namespace(
                "owner",
                frozenset({"probe.invalid"}),
                read,
                children,
                IPv4Network(POD_NETWORK),
            ),
            "http",
        )

    # An empty first page with a cursor is not an empty collection.
    result = run(
        {
            "": list_page(cursor="next"),
            "next": list_page([a[1]], "last"),
            "last": list_page([b[1]]),
        }
    )
    assert calls == [("owner", ""), ("owner", "next"), ("owner", "last"), "a", "b"]
    assert len(container(result, "services")) == SOLVER_SERVICE_COUNT
    assert "services" not in run({"": list_page()})


def interrupted_followups(item: Doc, fault: str) -> dict[str, Callable[[str], Page]]:
    """Map an interruption fault to the page callback that triggers it."""

    def deny(_cursor: str) -> Page:
        denial: Doc = {"message": "sensitive-fixture"}
        return int(fault), denial

    def hang(_cursor: str) -> Page:
        denial = "sensitive-fixture"
        raise TimeoutError(denial)

    def eof(_cursor: str) -> Page:
        raise StopIteration

    def newer(_cursor: str) -> Page:
        return list_page(version="newer")

    def loop(cursor: str) -> Page:
        return list_page(cursor=cursor)

    def duplicate(_cursor: str) -> Page:
        return list_page([item])

    def foreign(_cursor: str) -> Page:
        other = copy.deepcopy(item)
        container(other, "metadata")["namespace"] = "other"
        return list_page([other])

    def uncounted(_cursor: str) -> Page:
        status, page = list_page()
        container(page, "metadata")["remainingItemCount"] = 1
        return status, page

    return {
        "403": deny,
        "410": deny,
        "timeout": hang,
        "eof": eof,
        "version": newer,
        "loop": loop,
        "duplicate": duplicate,
        "foreign": foreign,
        "remaining": uncounted,
    }


@pytest.mark.parametrize(
    "fault",
    [
        "403",
        "410",
        "timeout",
        "eof",
        "version",
        "loop",
        "duplicate",
        "foreign",
        "remaining",
        "child",
    ],
)
def test_interrupted_scan_never_emits_partial_or_empty_withdrawal(fault: str) -> None:
    a = destination_fixture()
    item = a[1]
    resolved: list[Doc] = []
    followups = interrupted_followups(item, fault)

    def terminal(_followup: object) -> Page:
        return list_page()

    def read(_ns: str, cursor: str) -> Page:
        if not cursor:
            return list_page([item], "sensitive-cursor")
        return followups.get(fault, terminal)(cursor)

    def children(ob: Doc) -> Children:
        resolved.append(ob)
        raise TimeoutError("sensitive" + "-child")

    with pytest.raises(IncompleteScan, match="no snapshot") as err:
        scan_namespace(
            "owner",
            frozenset({"probe.invalid"}),
            read,
            children,
            IPv4Network(POD_NETWORK),
        )
    assert err.value.__context__ is None
    assert "sensitive" not in str(err.value)
    assert len(resolved) == int(fault == "child")


def test_namespace_scan_renews_only_original_slot_after_terminal_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tick = [100]
    monkeypatch.setattr(time, "monotonic_ns", lambda: tick[0])
    expected, ch, ing, svc, pod, slices = destination_fixture()
    ns, _, uid, host = expected
    slot = ScannedSlot(ns, host, uid, text(ch, "spec", "token"), SOLVER_URL, RENEWAL_WINDOW)
    net = IPv4Network(POD_NETWORK)

    def run(final: Callable[[], Page], child: ReadChildren | None = None) -> bool:
        def read(namespace: str, cursor: str) -> Page:
            assert namespace == ns
            return list_page([ch], cursor="next") if not cursor else final()

        return slot.refresh(frozenset({host}), read, child or default_children, net)

    def default_children(_item: Doc) -> Children:
        return ing, svc, pod, slices

    assert run(list_page)
    original = slot.witness()
    assert original is not None
    tick[0] = 108
    with pytest.raises(IncompleteScan):
        run(lambda: (410, {}))
    assert slot.witness() == original

    def interrupted(_item: Doc) -> Children:
        raise TimeoutError

    with pytest.raises(IncompleteScan):
        run(list_page, interrupted)
    tick[0] = 110
    assert slot.witness() is None
    assert run(list_page)

    def late() -> Page:
        tick[0] += 10
        return list_page()

    assert not run(late)
    assert slot.witness() is None
    assert run(list_page)
    assert not slot.refresh(frozenset({host}), lambda *_: list_page(), interrupted, net)
    assert slot.witness() is None


def test_new_verified_address_cannot_renew_a_slot_for_an_old_backend() -> None:
    expected, ch, ing, svc, pod, slices = destination_fixture()
    ns, _, uid, host = expected
    slot = ScannedSlot(ns, host, uid, text(ch, "spec", "token"), SOLVER_URL, ADDRESS_WINDOW)

    def run() -> bool:
        return slot.refresh(
            frozenset({host}),
            lambda *_: list_page([ch]),
            lambda _: (ing, svc, pod, slices),
            IPv4Network(POD_NETWORK),
        )

    assert run()
    container(pod, "status")["podIP"] = "10.42.2.11"
    container(slices[0], "endpoints", 0)["addresses"] = ["10.42.2.11"]
    assert not run()
    assert slot.witness() is None


@pytest.mark.parametrize("newer_outcome", ["finishes", "aborts"])
def test_one_namespace_scan_cannot_resurrect_a_slot_from_an_older_inflight_round(
    newer_outcome: str,
) -> None:
    newer_finishes = newer_outcome == "finishes"
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from ci.quality.public_http01_lease_scan import NamespaceGate

    rows = [destination_fixture(k, k * 43) for k in ("a", "b")]
    net = IPv4Network(POD_NETWORK)
    slots = tuple(
        Presentation(
            "owner",
            r[0][3],
            r[0][2],
            text(r[1], "spec", "token"),
            SOLVER_URL,
            GATE_WINDOW,
        )
        for r in rows
    )
    gate = NamespaceGate("owner", slots)
    calls: list[object] = []

    def children(ch: Doc) -> Children:
        calls.append(container(ch, "metadata")["uid"])
        return rows[int(container(ch, "metadata")["uid"] == "b")][2:]

    def both(_ns: str, cursor: str) -> Page:
        return list_page([rows[int(bool(cursor))][1]], "" if cursor else "more")

    assert gate.refresh(both, children, net)
    assert calls == ["a", "b"]
    original = [gate.witness(s) for s in slots]
    assert all(original)
    entered, release = Event(), Event()

    def blocked(ns: str, cursor: str) -> Page:
        if cursor:
            entered.set()
            assert release.wait(WAIT_SECONDS)
        return both(ns, cursor)

    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(gate.refresh, blocked, children, net)
        try:
            assert entered.wait(WAIT_SECONDS)
            if newer_finishes:
                assert gate.refresh(lambda *_: list_page([rows[1][1]]), children, net)
                after = [gate.witness(s) for s in slots]
                assert after[0] is None
                assert after[1] is not None
                assert after[1] != original[1]
            else:
                with pytest.raises(IncompleteScan):
                    gate.refresh(lambda *_: (410, {}), children, net)
                after = original
        finally:
            release.set()
        assert old.result(WAIT_SECONDS) is False
        assert [gate.witness(s) for s in slots] == after
