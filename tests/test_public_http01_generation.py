import copy

import pytest

from ci.quality.public_http01_generation import same_presentation


def fixture(uid):
    ns, name, host = "owner", "challenge", "probe.invalid"
    owner = {
        "apiVersion": "acme.cert-manager.io/v1",
        "kind": "Challenge",
        "name": name,
        "uid": uid,
        "controller": True,
    }
    token = "A" * 43
    challenge = {
        "apiVersion": owner["apiVersion"],
        "kind": "Challenge",
        "metadata": {"namespace": ns, "name": name, "uid": uid},
        "spec": {"dnsName": host, "type": "HTTP-01", "token": token},
        "status": {"state": "pending", "presented": True, "processing": True},
    }
    children = [
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
                            "backend": {
                                "service": {"name": "svc", "port": {"number": 8089}}
                            },
                        }
                    ]
                },
            }
        ],
    }
    return (ns, name, uid, host), challenge, *children


@pytest.mark.parametrize("index", [2, 3, 4])
def test_same_name_recreation_never_reuses_an_old_child(index):
    before = fixture("first")
    after = list(fixture("next"))
    assert same_presentation(*before) and same_presentation(*after)
    after[index] = before[index]
    assert not same_presentation(*after)
    assert not same_presentation(before[0], *after[1:])
    assert not same_presentation(after[0], None, *before[2:])


@pytest.mark.parametrize(
    "fault",
    [
        "deleting",
        "valid",
        "not-presented",
        "other-name",
        "other-peer",
        "token",
        "extra-path",
        "extra-controller",
        "class",
        "selector",
        "other-service",
        "other-port",
        "default",
    ],
)
def test_inactive_or_unrelated_observations_cannot_present(fault):
    expected, ch, ing, svc, pod = fixture("current")
    r = ing["spec"]
    path = r["rules"][0]["http"]["paths"][0]
    if fault == "deleting":
        ch["metadata"]["deletionTimestamp"] = "deleting"
    elif fault == "valid":
        ch["status"]["state"] = "valid"
    elif fault == "not-presented":
        ch["status"]["presented"] = False
    elif fault == "other-name":
        ch["spec"]["dnsName"] = "else.invalid"
    elif fault == "other-peer":
        pod["metadata"]["namespace"] = "other"
    elif fault == "token":
        path["path"] += "x"
    elif fault == "extra-path":
        r["rules"][0]["http"]["paths"].append(path.copy())
    elif fault == "extra-controller":
        svc["metadata"]["ownerReferences"] *= 2
    elif fault == "class":
        r["ingressClassName"] = "private"
    elif fault == "selector":
        ing["metadata"]["labels"] = {}
    elif fault == "other-service":
        path["backend"]["service"]["name"] = "other"
    elif fault == "other-port":
        path["backend"]["service"]["port"]["number"] = 80
    else:
        r["defaultBackend"] = {}
    assert not same_presentation(expected, ch, ing, svc, pod)


def destination_fixture(uid="now", token=None):
    from zlib import adler32

    expected, ch, ing, svc, pod = fixture(uid)
    if token is not None:
        ch["spec"]["token"] = token
        ing["spec"]["rules"][0]["http"]["paths"][0]["path"] = (
            "/.well-known/acme-challenge/" + token
        )
        ns, _, _, host = expected
        expected = (ns, "challenge-" + uid, uid, host)
        ch["metadata"]["name"] = expected[1]
        for child in (ing, svc, pod):
            child["metadata"]["ownerReferences"][0]["name"] = expected[1]
    ns, _, _, host = expected
    ip = "10.42.2.9"
    selector = {
        "acme.cert-manager.io/http01-solver": "true",
        "acme.cert-manager.io/http-domain": str(adler32(host.encode())),
        "acme.cert-manager.io/http-token": str(adler32(ch["spec"]["token"].encode())),
    }
    for child in (ing, svc, pod):
        child["metadata"].setdefault("labels", {}).update(selector)
    svc["spec"] = {
        "type": "NodePort",
        "clusterIP": "10.43.22.11",
        "ports": [
            {"name": "http", "port": 8089, "targetPort": 8089, "nodePort": 32123}
        ],
        "selector": selector,
    }
    pod["spec"] = {}
    pod["status"] = {
        "phase": "Running",
        "podIP": ip,
        "conditions": [{"type": "Ready", "status": "True"}],
    }
    sl = {
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
                    "uid": svc["metadata"]["uid"],
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
                    "uid": pod["metadata"]["uid"],
                    "namespace": ns,
                },
                "conditions": {"ready": True},
            }
        ],
    }
    return expected, ch, ing, svc, pod, [sl]


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "old-service",
        "old-pod",
        "substitute-ip",
        "node-address",
        "host-network",
        "deleting-slice",
        "second-slice",
        "wrong-target",
        "wrong-label",
        "not-serving",
        "terminating",
        "udp",
        "wrong-generation",
        "not-ready",
    ],
)
def test_only_verified_solver_pod_address_is_admitted(fault):
    from ipaddress import IPv4Network

    from ci.quality.public_http01_generation import solver_destination

    expected, ch, ing, svc, pod, slices = destination_fixture()
    sl = slices[0]
    ep = sl["endpoints"][0]
    if fault == "old-service":
        sl["metadata"]["ownerReferences"][0]["uid"] = "old"
    if fault == "old-pod":
        ep["targetRef"]["uid"] = "old"
    if fault == "substitute-ip":
        ep["addresses"] = ["10.42.2.8"]
    if fault == "node-address":
        ep["addresses"] = ["10.250.0.2"]
        pod["status"]["podIP"] = ep["addresses"][0]
    if fault == "host-network":
        pod["spec"]["hostNetwork"] = True
    if fault == "deleting-slice":
        sl["metadata"]["deletionTimestamp"] = "now"
    if fault == "second-slice":
        slices.append(sl)
    if fault == "wrong-target":
        svc["spec"]["ports"][0]["targetPort"] = 32123
    if fault == "wrong-label":
        pod["metadata"]["labels"]["acme.cert-manager.io/http-token"] = "other"
    if fault == "not-serving":
        ep["conditions"]["serving"] = False
    if fault == "terminating":
        ep["conditions"]["terminating"] = True
    if fault == "udp":
        sl["ports"][0]["protocol"] = "UDP"
    if fault == "wrong-generation":
        ch["metadata"]["uid"] = "next"
    if fault == "not-ready":
        pod["status"]["conditions"] = []
    assert solver_destination(
        expected, ch, ing, svc, pod, slices, IPv4Network("10.42.0.0/16")
    ) == ("http://10.42.2.9:8089" if fault == "none" else None)


def test_closed_snapshot_never_encodes_empty_services_on_withdrawal():
    from ipaddress import IPv4Network

    from ci.quality.public_http01_generation import closed_solver_snapshot

    inputs = list(destination_fixture())
    network = IPv4Network("10.42.0.0/16")
    baseline = closed_solver_snapshot(*inputs, network)
    http = baseline["http"]
    assert http["services"] == {
        "solver": {"loadBalancer": {"servers": [{"url": "http://10.42.2.9:8089"}]}}
    }
    proof = http["routers"]["proof"]
    assert (
        proof["rule"]
        == f"Host(`probe.invalid`) && Path(`/.well-known/acme-challenge/{inputs[1]['spec']['token']}`)"
        and proof["observability"] == {"accessLogs": False, "tracing": False}
    )
    inputs[-1][0]["endpoints"][0]["targetRef"]["uid"] = "stale"
    withdrawn = closed_solver_snapshot(*inputs, network)
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
    assert baseline["http"]["routers"].keys() == {"proof", "sentinel"}
    inputs[1] = None
    assert closed_solver_snapshot(*inputs, network) == withdrawn


def test_batch_withdrawal_is_local_and_ambiguous_claims_never_choose_a_winner():
    from ipaddress import IPv4Network

    from ci.quality.public_http01_generation import closed_solver_batch

    net = IPv4Network("10.42.0.0/16")
    a = destination_fixture("first", "A" * 43)
    b = destination_fixture("second", "B" * 43)

    def snapshot(*rows):
        return closed_solver_batch(rows, net)["http"]

    both = snapshot(a, b)
    assert both == snapshot(b, a) and len(both["services"]) == 2
    stale = copy.deepcopy(a)
    stale[-1][0]["endpoints"][0]["targetRef"]["uid"] = "old"
    assert snapshot(stale, b) == snapshot(b)
    assert snapshot(a, b, destination_fixture("third", "A" * 43)) == snapshot(b)
    assert snapshot(a, stale, b) == snapshot(b)
    assert snapshot() == snapshot(stale) and "services" not in snapshot()


def list_page(items=(), cursor="", version="opaque-rv"):
    return 200, {
        "apiVersion": "acme.cert-manager.io/v1",
        "kind": "ChallengeList",
        "metadata": {"resourceVersion": version, "continue": cursor},
        "items": list(items),
    }


def test_scan_completes_pagination_before_resolving_children_or_emitting_empty_file():
    from ipaddress import IPv4Network

    from ci.quality.public_http01_scan import scan_namespace

    a = destination_fixture("a", "A" * 43)
    b = destination_fixture("b", "B" * 43)
    calls = []

    def run(pages):
        def read(ns, cursor):
            calls.append((ns, cursor))
            return pages[cursor]

        def children(item):
            calls.append(item["metadata"]["uid"])
            return (a if item is a[1] else b)[2:]

        return scan_namespace(
            "owner",
            frozenset({"probe.invalid"}),
            read,
            children,
            IPv4Network("10.42.0.0/16"),
        )["http"]

    # An empty first page with a cursor is not an empty collection.
    result = run(
        {
            "": list_page(cursor="next"),
            "next": list_page([a[1]], "last"),
            "last": list_page([b[1]]),
        }
    )
    assert (
        calls == [("owner", ""), ("owner", "next"), ("owner", "last"), "a", "b"]
        and len(result["services"]) == 2
    )
    assert "services" not in run({"": list_page()})


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
def test_interrupted_scan_never_emits_partial_or_empty_withdrawal(fault):
    from ipaddress import IPv4Network

    from ci.quality.public_http01_scan import IncompleteScan, scan_namespace

    a = destination_fixture()
    item = a[1]
    resolved = []

    def read(ns, cursor):
        if not cursor:
            return list_page([item], "sensitive-cursor")
        if fault in ("403", "410"):
            return int(fault), {"message": "sensitive-fixture"}
        if fault == "timeout":
            raise TimeoutError("sensitive-fixture")
        if fault == "eof":
            raise StopIteration
        if fault == "version":
            return list_page(version="newer")
        if fault == "loop":
            return list_page(cursor=cursor)
        if fault == "duplicate":
            return list_page([item])
        if fault == "foreign":
            other = copy.deepcopy(item)
            other["metadata"]["namespace"] = "other"
            return list_page([other])
        status, page = list_page()
        if fault == "remaining":
            page["metadata"]["remainingItemCount"] = 1
        return status, page

    def children(obj):
        resolved.append(obj)
        raise TimeoutError("sensitive-child")

    with pytest.raises(IncompleteScan, match="no snapshot") as err:
        scan_namespace(
            "owner",
            frozenset({"probe.invalid"}),
            read,
            children,
            IPv4Network("10.42.0.0/16"),
        )
    assert err.value.__context__ is None and "sensitive" not in str(err.value)
    assert len(resolved) == int(fault == "child")
