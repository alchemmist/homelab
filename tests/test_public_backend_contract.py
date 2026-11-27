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
        spec={"clusterIP": "10.43.0.10", "ports": [{"name": "secure", "port": 443}]},
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
        item("Middleware", "guard", spec={"forwardAuth": {}}),
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
