"""Offline Helm contracts for a private relay beside the fenced public owner."""

import json
import subprocess
from pathlib import Path

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
    return {
        (d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(output) if d
    }


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
    assert (
        service["type"] == "ClusterIP"
        and service["selector"] == template["metadata"]["labels"]
    )
    assert (
        service["selector"] != stage[legacy]["spec"]["template"]["metadata"]["labels"]
    )
    config = json.loads(
        stage["ConfigMap", "vpn-transit-rehearsal"]["data"]["user.json"]
    )
    baseline = json.loads(
        (ROOT / "deploy/vpn-hardening/moscow-transit.json").read_text()
    )
    assert baseline["outbounds"][0].pop("sendThrough") == "10.250.0.40"
    assert config == baseline
    ports = {
        (i["settings"]["allowedNetwork"].upper(), int(port))
        for i in config["inbounds"]
        for port in i["port"].split(",")
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
                    "podSelector": {
                        "matchLabels": {"app.kubernetes.io/name": "traefik-moscow"}
                    },
                }
            ]
        }
    ]
