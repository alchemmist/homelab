"""Check replica equality against rendered resources, not names of known sites."""

import json
import subprocess

import pytest
import yaml

from ci.quality.public_web import CATALOG, ROOT, replica_values


def test_every_replica_is_the_same_except_placement_and_local_a() -> None:
    """A new location with an unknown label must not require any routing code change."""
    catalog = yaml.safe_load(CATALOG.read_text())
    candidates = [
        *catalog["replicas"].values(),
        {"node": "example-worker", "publicIP": "192.0.2.10"},
    ]
    baseline = None
    for instance in candidates:
        values = replica_values(catalog, instance, 2026112601)
        text = subprocess.check_output(
            [
                "helm",
                "template",
                "entry",
                str(ROOT / "deploy/public-web/replica"),
                "-n",
                "public-entry",
                "-f",
                "-",
            ],
            input=json.dumps(values),
            text=True,
        )
        docs = [doc for doc in yaml.safe_load_all(text) if doc]
        (cm,) = [doc for doc in docs if doc["kind"] == "ConfigMap"]
        (dep,) = [doc for doc in docs if doc["kind"] == "Deployment"]
        pod = dep["spec"]["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        assert [c["name"] for c in pod["containers"] if any(
            m["name"] == "api" for m in c.get("volumeMounts", [])
        )] == ["traefik"]
        (dns,) = [c for c in pod["containers"] if c["name"] == "coredns"]
        (service,) = [d["spec"] for d in docs if d["kind"] == "Service"]
        port = dns["readinessProbe"]["tcpSocket"]["port"]
        assert f":{port} {{" in cm["data"]["Corefile"]
        assert service["type"] == "ClusterIP"
        assert {(p["protocol"], p["port"], p["targetPort"]) for p in service["ports"]} == {
            ("TCP", 53, port), ("UDP", 53, port)
        }
        assert pod.pop("nodeSelector") == {"kubernetes.io/hostname": instance["node"]}
        dep["spec"]["template"]["metadata"].pop("annotations")
        expected = {
            host
            for names in catalog["hosts"].values()
            for host, policy in names.items()
            if policy.get("route", "web") == "web" and policy["dns"] == "managed"
        }
        normalized = []
        observed = []
        for line in cm["data"]["db.alchemmist.xyz"].splitlines():
            fields = line.split()
            host = (
                (
                    "alchemmist.xyz"
                    if fields[:1] == ["@"]
                    else fields[0] + ".alchemmist.xyz"
                )
                if fields
                else None
            )
            if host in expected and fields[1:3] == ["IN", "A"]:
                assert fields[3:] == [instance["publicIP"]]
                observed.append(host)
                normalized.append(f"{host} SELF")
            else:
                normalized.append(line)
        assert sorted(observed) == sorted(expected)
        cm["data"]["db.alchemmist.xyz"] = normalized
        assert any(line.startswith("vpn IN A ") for line in normalized)
        assert set(values["publications"]) == {
            d["metadata"]["namespace"] for d in docs if d["kind"] == "Role"
        }
        (controller,) = [c for c in pod["containers"] if c["name"] == "traefik"]
        prefix = "--providers.kubernetesingress.namespaces="
        (scope,) = [
            arg.removeprefix(prefix)
            for arg in controller["args"]
            if arg.startswith(prefix)
        ]
        assert set(scope.split(",")) == set(values["publications"])
        assert {
            d["metadata"]["namespace"] for d in docs if d["kind"] == "RoleBinding"
        } == set(scope.split(","))
        assert not {"postgres", "redis", "netbird-pilot"}.intersection(scope.split(","))
        assert "inform.sch1357.ru" in values["publications"]["schoolbot"]
        assert "bot.sch1357.ru" not in values["publications"]["schoolbot"]
        assert "monori.alchemmist.xyz" in values["publications"]["monori"]
        if baseline is None:
            baseline = docs, values["publications"]
        assert (docs, values["publications"]) == baseline


def test_replica_cannot_override_host_or_namespace_scope() -> None:
    """Inventory entries only supply placement and IP."""
    catalog = yaml.safe_load(CATALOG.read_text())
    with pytest.raises(ValueError, match="only node and publicIP"):
        replica_values(
            catalog, {**catalog["replicas"]["home"], "watchNamespaces": ["blog"]}, 1
        )
