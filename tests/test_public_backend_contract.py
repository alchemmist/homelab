"""Test port-, owner- and protocol-specific backend selection before web staging."""

import pytest

from ci.quality.public_backend_contract import PREFIX, inventory


def item(kind: str, name: str, **fields: dict) -> dict:
    return {"kind": kind, "metadata": {"namespace": "app", "name": name}, **fields}


def fixture() -> tuple[dict, list[dict]]:
    catalog = {
        "hosts": {"app": {"site.test": {}, "vpn.test": {"route": "vpn-transit"}}}
    }
    service = item(
        "Service",
        "backend",
        spec={
            "clusterIP": "10.43.0.10",
            "ports": [{"name": "secure", "port": 443, "targetPort": 8443}],
        },
    )
    service["metadata"]["annotations"] = {
        PREFIX + "service.serverstransport": "app-verified@kubernetescrd"
    }
    slices = item(
        "EndpointSlice",
        "backend-x",
        ports=[{"name": "secure", "port": 8443}],
        endpoints=[{"addresses": ["10.42.1.10"], "conditions": {"ready": True}}],
    )
    slices["metadata"]["labels"] = {"kubernetes.io/service-name": "backend"}
    ing = item(
        "Ingress",
        "route",
        spec={
            "ingressClassName": "traefik",
            "rules": [
                {
                    "host": "site.test",
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": "backend",
                                        "port": {"name": "secure"},
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        },
    )
    ing["metadata"]["annotations"] = {
        PREFIX + "router.middlewares": "app-guard@kubernetescrd",
        PREFIX + "router.priority": "150",
    }
    return catalog, [
        ing,
        service,
        slices,
        item(
            "Middleware",
            "guard",
            spec={
                "forwardAuth": {
                    "address": "https://site.test/auth",
                    "trustForwardHeader": False,
                }
            },
        ),
        item(
            "ServersTransport",
            "verified",
            spec={"serverName": "site.test", "insecureSkipVerify": False},
        ),
    ]


def test_preserves_upstream_and_auth_references() -> None:
    catalog, objects = fixture()
    report = inventory(catalog, objects)
    assert not report["errors"]
    (row,) = report["routes"]
    assert (row["service"], row["port"], row["scheme"], row["transport"]) == (
        "app/backend",
        443,
        "https",
        "app-verified@kubernetescrd",
    )
    assert (
        row["middlewares"] == ["app-guard@kubernetescrd"] and row["priority"] == "150"
    )
    objects[1]["metadata"]["annotations"] = {PREFIX + "service.serversscheme": "h2c"}
    assert inventory(catalog, objects)["routes"][0]["scheme"] == "h2c"


@pytest.mark.parametrize(
    "fault",
    [
        "auth",
        "transport",
        "skip-verify",
        "port",
        "not-ready",
        "terminating",
        "external",
        "class",
        "empty-paths",
    ],
)
def test_missing_dependencies_fail_the_gate(fault: str) -> None:
    catalog, objects = fixture()
    ing, svc, sl, guard, transport = objects
    if fault == "auth":
        objects.remove(guard)
    elif fault == "transport":
        objects.remove(transport)
    elif fault == "skip-verify":
        transport["spec"]["insecureSkipVerify"] = True
    elif fault == "port":
        sl["ports"][0]["name"] = "other"
    elif fault == "not-ready":
        sl["endpoints"][0]["conditions"]["ready"] = False
    elif fault == "terminating":
        sl["endpoints"][0]["conditions"]["terminating"] = True
    elif fault == "external":
        svc["spec"]["type"] = "ExternalName"
    elif fault == "class":
        ing["spec"]["ingressClassName"] = "private"
    else:
        ing["spec"]["rules"][0]["http"]["paths"] = []
    assert inventory(catalog, objects)["errors"]


def test_closed_path_rules_do_not_widen_segment_or_exact_matches() -> None:
    from ci.quality.public_path_rule import path_rule

    host = "site.test"
    assert (
        path_rule(host, "/public/", "Prefix")
        == path_rule(host, "/public", "Prefix")
        == "Host(`site.test`) && (Path(`/public`) || PathPrefix(`/public/`))"
    )
    assert (
        path_rule(host, "/change-password/", "Exact")
        == "Host(`site.test`) && Path(`/change-password/`)"
    )
    assert path_rule(host, "/", "Prefix") == "Host(`site.test`) && PathPrefix(`/`)"
    for name, path, kind in [
        ("*.test", "/", "Prefix"),
        ("site.test", "/public//x", "Prefix"),
        ("site.test", "/public/../x", "Prefix"),
        ("site.test", "/x?query", "Exact"),
        ("site.test", "/x`", "Exact"),
        ("site.test", "/x", "ImplementationSpecific"),
    ]:
        with pytest.raises(ValueError):
            path_rule(name, path, kind)


def test_implicit_priority_is_from_source_not_rewritten_matcher_length() -> None:
    from ci.quality.public_path_rule import path_rule, source_priority

    host = "site.invalid"
    path = "/public/"
    old = len('Host("site.invalid") && PathPrefix("/public/")')
    assert source_priority(host, path, "Prefix", strict_prefix=False) == old
    assert old < old + 1 < len(path_rule(host, path, "Prefix"))
    assert source_priority(host, path, "Prefix", strict_prefix=True) == len(
        path_rule(host, path, "Prefix")
    )
    assert (
        source_priority(host, path, "Prefix", strict_prefix=False, declared=155) == 155
    )
    assert source_priority(host, "/", "Prefix", strict_prefix=False) == source_priority(
        host, "/", "Prefix", strict_prefix=True
    )
    with pytest.raises(ValueError):
        source_priority(host, path, "Prefix", strict_prefix=None)


def test_path_diff_reports_winning_auth_owner_and_ties_not_just_http_service():
    from ci.quality.public_path_diff import path_diff

    rows = [
        {
            "host": "site.test",
            "path": "/",
            "pathType": "Prefix",
            "owner": "site/ui",
            "service": "site/app",
            "priority": None,
        },
        {
            "host": "site.test",
            "path": "/webhook",
            "pathType": "Prefix",
            "owner": "site/machine",
            "service": "site/app",
            "priority": "200",
        },
    ]
    report = path_diff(rows, source_strict=False)
    (one,) = report
    assert (
        one["witness"] == "/webhook-probe"
        and one["original"] == [rows[1]]
        and one["candidate"] == [rows[0]]
    )
    assert not path_diff(rows, source_strict=True)
    rows.append({**rows[1], "owner": "site/other"})
    assert any(len(f["candidate"]) == 2 for f in path_diff(rows, source_strict=True))


@pytest.mark.parametrize("path", ["/public/", "/api/v1"])
@pytest.mark.parametrize("priority", [0, 160])
def test_closed_compiler_refuses_non_equivalent_prefix_even_with_priority(
    path, priority
):
    from ci.quality.public_path_rule import unchanged_path_matcher

    with pytest.raises(ValueError, match="scope review"):
        unchanged_path_matcher(
            "site.test", path, "Prefix", source_strict=False, declared=priority
        )
    strict = unchanged_path_matcher(
        "site.test", path, "Prefix", source_strict=True, declared=priority
    )
    assert strict[1] == (priority or len(strict[0]))
    for kind, unchanged in [("Exact", path), ("Prefix", "/")]:
        assert unchanged_path_matcher(
            "site.test", unchanged, kind, source_strict=False
        ) == unchanged_path_matcher("site.test", unchanged, kind, source_strict=True)


def test_host_compilation_does_not_return_fallback_without_blocked_specific_route():
    from ci.quality.public_path_rule import unchanged_host_matchers

    paths = [("/", "Prefix", 10), ("/public/", "Prefix", 155)]
    with pytest.raises(ValueError, match="scope review"):
        unchanged_host_matchers("site.test", paths, source_strict=False)
    assert len(unchanged_host_matchers("site.test", paths, source_strict=True)) == 2


def test_same_ref_body_changes_are_visible_without_dumping_contents():
    catalog, objects = fixture()
    before = inventory(catalog, objects)
    assert not before["errors"]
    objects[3]["spec"]["forwardAuth"]["address"] = "https://site.test/other-auth"
    objects[4]["spec"]["serverName"] = "other.test"
    after = inventory(catalog, objects)
    assert not after["errors"]
    old, new = before["routes"][0], after["routes"][0]
    assert (
        old["middlewareBodies"] != new["middlewareBodies"]
        and old["transportDigest"] != new["transportDigest"]
    )
    assert (
        old["middlewares"] == new["middlewares"]
        and old["transport"] == new["transport"]
    )
    assert "other-auth" not in str(after) and "other.test" not in str(after)


@pytest.mark.parametrize(
    "change", ["trust", "chain", "transport-option", "middleware-option"]
)
def test_unrehearsed_crd_shapes_block_route_comparison(change):
    catalog, objects = fixture()
    if change == "trust":
        objects[3]["spec"]["forwardAuth"]["trustForwardHeader"] = True
    elif change == "chain":
        objects[3]["spec"] = {"chain": {"middlewares": [{"name": "unknown"}]}}
    elif change == "middleware-option":
        objects[3]["spec"]["forwardAuth"]["authResponseHeaders"] = ["X-Fixture"]
    else:
        objects[4]["spec"]["rootCAsSecrets"] = ["some-ca"]
    assert inventory(catalog, objects)["errors"]


def test_unnamed_service_port_must_match_numeric_target_not_frontend():
    catalog, objects = fixture()
    target = objects[0]["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
    target["port"] = {"number": 443}
    port = objects[1]["spec"]["ports"][0]
    del port["name"]
    del objects[2]["ports"][0]["name"]
    assert not inventory(catalog, objects)["errors"]
    objects[2]["ports"][0]["port"] = 443
    assert inventory(catalog, objects)["errors"]
    del port["targetPort"]
    assert not inventory(catalog, objects)["errors"]
