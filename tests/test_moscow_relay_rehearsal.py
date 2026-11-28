"""Offline Helm contracts for a private relay beside the fenced public owner."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from ci.quality.closed_root_backend import Obj, entries, plain, view, whole

ROOT = Path(__file__).resolve().parents[1]
# Identity every rendered rehearsal resource is indexed by.
DocKey = tuple[object, object]


def objects(*args: str) -> dict[DocKey, Obj]:
    """Index nonempty rendered resources by Kubernetes identity."""
    output = subprocess.check_output(
        [
            "helm",
            "template",
            "vpn-transit",
            str(ROOT / "charts/vpn-transit"),
            "-n",
            "vpn-transit",
            *args,
        ],
        text=True,
    )
    docs: dict[DocKey, Obj] = {}
    for item in yaml.safe_load_all(output):
        if not item:
            continue
        doc = view(item)
        docs[(doc["kind"], view(doc["metadata"])["name"])] = doc
    return docs


def test_private_rehearsal_never_takes_public_sockets() -> None:
    """The ordinary release is unchanged even when the second relay is rendered."""
    legacy = ("Deployment", "vpn-transit")
    default = objects()
    assert set(default) == {legacy}
    stage = objects("--set", "podRehearsal=true")
    assert stage[legacy] == default[legacy]
    relay_doc = view(stage["Deployment", "vpn-transit-rehearsal"])
    template = view(view(relay_doc["spec"])["template"])
    pod = view(template["spec"])
    assert pod["hostNetwork"] is False
    assert pod["automountServiceAccountToken"] is False
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-4"}
    assert all(
        "hostPort" not in view(port)
        for c in entries(pod["containers"])
        for port in entries(view(c)["ports"])
    )
    assert pod["volumes"] == [
        {"name": "user-config", "configMap": {"name": "vpn-transit-rehearsal"}}
    ]
    service_spec = view(view(view(stage["Service", "vpn-transit"])["spec"]))
    assert service_spec["type"] == "ClusterIP"
    assert service_spec["selector"] == view(view(template["metadata"])["labels"])
    legacy_labels = view(view(view(view(stage[legacy]["spec"])["template"])["metadata"])["labels"])
    assert service_spec["selector"] != legacy_labels
    config = json.loads(
        plain(view(view(stage["ConfigMap", "vpn-transit-rehearsal"])["data"])["user.json"])
    )
    baseline = json.loads((ROOT / "deploy/vpn-hardening/moscow-transit.json").read_text())
    assert baseline["outbounds"][0].pop("sendThrough") == "10.250.0.40"
    assert config == baseline
    sockets = [
        (i["settings"]["allowedNetwork"].upper(), int(port))
        for i in config["inbounds"]
        for port in i["port"].split(",")
    ]
    ports = set(sockets)
    assert len(sockets) == len(ports), "Duplicate listener within one transport"
    assert ports == {("TCP", p) for p in (80, 443, 32053, 32083, 32084)} | {
        ("UDP", p) for p in (443, 32085, 32086)
    }
    assert {
        (plain(view(entry)["protocol"]), whole(view(entry)["targetPort"]))
        for entry in entries(service_spec["ports"])
    } == ports
    policy = view(view(view(stage["NetworkPolicy", "vpn-transit-rehearsal"])["spec"]))
    assert view(view(policy["podSelector"])["matchLabels"]) == service_spec["selector"]
    (egress,) = entries(policy["egress"])
    egress_doc = view(egress)
    assert egress_doc["to"] == [{"ipBlock": {"cidr": "10.250.0.2/32"}}]
    assert {
        (plain(view(entry)["protocol"]), whole(view(entry)["port"]))
        for entry in entries(egress_doc["ports"])
    } == ports
    assert policy["ingress"] == [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "traefik-moscow"}
                    },
                    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik-moscow"}},
                }
            ]
        }
    ]


def test_parking_and_restoring_only_changes_legacy_replica_count() -> None:
    """Keep both objects tracked even when Argo pruning is disabled."""
    serving = objects("--set", "podRehearsal=true")
    parked = objects("--set", "podRehearsal=true,legacyPortOwner=parked")
    legacy = ("Deployment", "vpn-transit")
    relay = ("Deployment", "vpn-transit-rehearsal")
    assert view(view(parked[relay])["spec"])["replicas"] == 1
    legacy_spec = view(view(parked[legacy])["spec"])
    assert legacy_spec["replicas"] == 0
    legacy_spec["replicas"] = 1
    restored = objects("--set", "podRehearsal=true,legacyPortOwner=serving")
    assert parked == serving == restored


@pytest.mark.parametrize(
    "values",
    [
        "legacyPortOwner=parked",
        "legacyPortOwner=parked,podRehearsal=true,replicas=0",
        "legacyPortOwner=typo",
        "replicas=2",
    ],
)
def test_invalid_owner_states_fail_to_render(values: str) -> None:
    """Reject missing replacement backends and unknown or competing owner states."""
    with pytest.raises(subprocess.CalledProcessError):
        objects("--set", values)


def test_tls_flow_requires_both_exact_steps_on_same_new_socket() -> None:
    """Match a new socket only when both TLS write deltas land on it exactly."""
    from ci.quality.moscow_blog_relay import matches

    opened = dict.fromkeys(range(5), 100)
    first = dict.fromkeys((0, 1, 2, 3), 151)
    second = {0: 212, 1: 212, 2: 211, 4: 212}
    assert matches({0: 0}, opened, (first, 51), (second, 61)) == {1}
    second[3] = 212
    assert matches({0: 0}, opened, (first, 51), (second, 61)) == {1, 3}


def test_www_split_fixture_is_exact_and_rejects_widened_owner_rules() -> None:
    """Ensure the compiled fixture matches only the exact reviewed split objects."""
    from ci.quality.moscow_www_split import VPN, WWW, fixture

    def render(release: str, chart: str, namespace: str, *extra: str) -> list[Obj]:
        return [
            view(doc)
            for doc in yaml.safe_load_all(
                subprocess.check_output(
                    [
                        "helm",
                        "template",
                        release,
                        str(ROOT / "charts" / chart),
                        "-n",
                        namespace,
                        *extra,
                    ]
                )
            )
            if doc
        ]

    (route,) = [
        doc
        for doc in render(
            "traefik-moscow",
            "traefik-moscow",
            "traefik-moscow",
            "--set",
            "rehearsal=true",
        )
        if view(doc.get("metadata", {})).get("name") == "moscow-tcp-443"
    ]
    docs = render("blog", "blog", "blog", "-f", str(ROOT / "deploy/blog/values.yaml"))
    (b,) = [doc for doc in docs if doc["kind"] == "Ingress"]
    (s,) = [doc for doc in docs if doc["kind"] == "Service"]
    service_spec = view(s["spec"])
    service_spec.update(type="ClusterIP", clusterIP="10.43.1.2")
    (service_port,) = entries(service_spec["ports"])
    view(service_port)["protocol"] = "TCP"
    out = fixture(route, b, s)
    www_router = view(view(view(out["http"])["routers"])["www"])
    vpn_router = view(view(view(out["tcp"])["routers"])["vpn"])
    assert www_router["rule"] == f"Host(`{WWW}`)"
    assert vpn_router["rule"] == f"HostSNI(`{VPN}`)"
    assert vpn_router["tls"] == {"passthrough": True}
    assert view(view(view(view(out["tcp"])["services"])["fixture"])["loadBalancer"])["servers"] == [
        {"address": "127.0.0.1:19443"}
    ]
    assert "10.250.0.2" not in json.dumps(out)
    annotations = view(view(view(b["metadata"])["annotations"]))
    annotations["traefik.ingress.kubernetes.io/router.middlewares"] = "unreviewed"
    with pytest.raises(ValueError, match="blog owner changed"):
        fixture(route, b, s)
    del annotations["traefik.ingress.kubernetes.io/router.middlewares"]
    (tcp_route,) = entries(view(view(route)["spec"])["routes"])
    view(tcp_route)["match"] = "HostSNI(`*`)"
    with pytest.raises(ValueError, match="TCP owner changed"):
        fixture(route, b, s)


def test_trojan_fixture_preserves_private_destination_guard_and_separate_credentials():
    from ci.quality.moscow_vpn_echo import ECHO, PATH, configs

    a, b = "1" * 64, "2" * 64
    server, right, wrong = configs(a, b, "10.42.7.101")
    assert server["routing"]["rules"] == [
        {
            "type": "field",
            "ip": ["10.42.7.101/32"],
            "port": str(ECHO),
            "network": "tcp,udp",
            "outboundTag": "echo",
        }
    ]
    assert server["outbounds"] == [
        {"tag": "deny", "protocol": "blackhole"},
        {"tag": "echo", "protocol": "freedom"},
    ]
    assert all(
        c["inbounds"][0]["listen"] == "127.0.0.1" for c in (server, right, wrong)
    )
    assert server["inbounds"][0]["settings"] == {"clients": [{"password": a}]}
    for client, credential in [(right, a), (wrong, b)]:
        out = client["outbounds"][0]
        assert out["settings"] == {
            "servers": [{"address": "127.0.0.1", "port": 18443, "password": credential}]
        }
        s = out["streamSettings"]
        assert s["wsSettings"] == {"path": PATH} and s["tlsSettings"] == {
            "serverName": "vpn.alchemmist.xyz",
            "disableSystemRoot": True,
            "certificates": [
                {"usage": "verify", "certificateFile": "/client/fixture-ca.crt"}
            ],
        }
    for first, second, peer in [
        (a, a, "10.42.1.1"),
        (a, "short", "10.42.1.1"),
        (a, b, "10.250.0.2"),
    ]:
        with pytest.raises(ValueError):
            configs(first, second, peer)
