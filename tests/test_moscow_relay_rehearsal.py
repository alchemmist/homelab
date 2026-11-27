"""Offline Helm contracts for a private relay beside the fenced public owner."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def objects(*args: str) -> dict:
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
    return {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(output) if d}


def test_private_rehearsal_never_takes_public_sockets() -> None:
    """The ordinary release is unchanged even when the second relay is rendered."""
    legacy = ("Deployment", "vpn-transit")
    default = objects()
    assert set(default) == {legacy}
    stage = objects("--set", "podRehearsal=true")
    assert stage[legacy] == default[legacy]
    template = stage["Deployment", "vpn-transit-rehearsal"]["spec"]["template"]
    pod = template["spec"]
    assert pod["hostNetwork"] is False and pod["automountServiceAccountToken"] is False
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-4"}
    assert all("hostPort" not in port for c in pod["containers"] for port in c["ports"])
    assert pod["volumes"] == [
        {"name": "user-config", "configMap": {"name": "vpn-transit-rehearsal"}}
    ]
    service = stage["Service", "vpn-transit"]["spec"]
    assert service["type"] == "ClusterIP" and service["selector"] == template["metadata"]["labels"]
    assert service["selector"] != stage[legacy]["spec"]["template"]["metadata"]["labels"]
    config = json.loads(stage["ConfigMap", "vpn-transit-rehearsal"]["data"]["user.json"])
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
    assert {(p["protocol"], p["targetPort"]) for p in service["ports"]} == ports
    policy = stage["NetworkPolicy", "vpn-transit-rehearsal"]["spec"]
    assert policy["podSelector"]["matchLabels"] == service["selector"]
    (egress,) = policy["egress"]
    assert egress["to"] == [{"ipBlock": {"cidr": "10.250.0.2/32"}}]
    assert {(p["protocol"], p["port"]) for p in egress["ports"]} == ports
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
    assert parked[relay]["spec"]["replicas"] == 1
    assert parked[legacy]["spec"]["replicas"] == 0
    parked[legacy]["spec"]["replicas"] = 1
    assert parked == serving == objects("--set", "podRehearsal=true,legacyPortOwner=serving")


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
    from ci.quality.moscow_blog_relay import matches

    opened = {i: 100 for i in range(5)}
    first = {i: 151 for i in (0, 1, 2, 3)}
    second = {0: 212, 1: 212, 2: 211, 4: 212}
    assert matches({0: 0}, opened, (first, 51), (second, 61)) == {1}
    second[3] = 212
    assert matches({0: 0}, opened, (first, 51), (second, 61)) == {1, 3}


def test_www_split_fixture_is_exact_and_rejects_widened_owner_rules() -> None:
    from ci.quality.moscow_www_split import VPN, WWW, fixture

    def render(release, chart, namespace, *extra):
        return [
            d
            for d in yaml.safe_load_all(
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
            if d
        ]

    (route,) = [
        d
        for d in render(
            "traefik-moscow",
            "traefik-moscow",
            "traefik-moscow",
            "--set",
            "rehearsal=true",
        )
        if d.get("metadata", {}).get("name") == "moscow-tcp-443"
    ]
    docs = render("blog", "blog", "blog", "-f", str(ROOT / "deploy/blog/values.yaml"))
    (b,) = [d for d in docs if d["kind"] == "Ingress"]
    (s,) = [d for d in docs if d["kind"] == "Service"]
    s["spec"].update(type="ClusterIP", clusterIP="10.43.1.2")
    s["spec"]["ports"][0]["protocol"] = "TCP"
    out = fixture(route, b, s)
    assert (
        out["http"]["routers"]["www"]["rule"] == f"Host(`{WWW}`)"
        and out["tcp"]["routers"]["vpn"]["rule"] == f"HostSNI(`{VPN}`)"
        and out["tcp"]["routers"]["vpn"]["tls"] == {"passthrough": True}
    )
    assert out["tcp"]["services"]["fixture"]["loadBalancer"]["servers"] == [
        {"address": "127.0.0.1:19443"}
    ]
    assert "10.250.0.2" not in json.dumps(out)
    b["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"] = "unreviewed"
    with pytest.raises(ValueError):
        fixture(route, b, s)
    del b["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"]
    route["spec"]["routes"][0]["match"] = "HostSNI(`*`)"
    with pytest.raises(ValueError):
        fixture(route, b, s)
