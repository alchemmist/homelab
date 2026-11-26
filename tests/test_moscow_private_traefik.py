"""Render both Moscow Applications together without touching the cluster."""

import pytest
import yaml

from ci.quality.charts import ROOT, argocd_targets, render


def test_moscow_private_rehearsal() -> None:
    """Check the effective opt-ins, fallback defaults, isolation and the entire VPN path."""
    targets, _ = argocd_targets()
    (moscow,) = [t for t in targets if t["release"] == "traefik-moscow"]
    (relay,) = [t for t in targets if t["release"] == "vpn-transit"]
    # No values files, valuesObject or --set parameters: exercise bare chart defaults.
    no_overrides = {"values": [], "inline_values": {}, "parameters": []}
    assert render({**moscow, **no_overrides}) == []
    docs = render(moscow)
    backend = render(relay)
    assert docs and backend
    baseline = render({**relay, **no_overrides})
    assert baseline and len(baseline) == 1
    (legacy,) = baseline
    assert (legacy["kind"], legacy["metadata"]["name"]) == ("Deployment", "vpn-transit")
    assert legacy["spec"]["template"]["spec"]["hostNetwork"] is True
    matching = [
        d
        for d in backend
        if d["kind"] == legacy["kind"]
        and d["metadata"]["namespace"] == legacy["metadata"]["namespace"]
        and d["metadata"]["name"] == legacy["metadata"]["name"]
    ]
    assert matching == [legacy]  # Exactly one public owner, with unchanged content.
    (deployment,) = [d for d in docs if d["kind"] == "Deployment"]
    template = deployment["spec"]["template"]
    pod = template["spec"]
    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-4"}
    assert not pod["hostNetwork"]
    (container,) = pod["containers"]
    assert all("hostPort" not in p for p in container.get("ports", []))
    args = container["args"]
    assert not any(
        "http3" in a or "ingressendpoint" in a or "insecureskipverify" in a.lower()
        for a in args
    )
    assert {arg for arg in args if ".asdefault=" in arg} == {
        "--entrypoints.web.asdefault=true",
        "--entrypoints.websecure.asdefault=true",
    }
    assert "--entrypoints.websecure.http.tls=true" in args
    catalog = yaml.safe_load((ROOT / "deploy/public-web/entrances.yaml").read_text())
    assert catalog["moscowWatchNamespaces"] == ["blog", "cats", "format-quorum"]
    assert "--providers.kubernetesingress.namespaces=blog,cats,format-quorum" in args
    assert "--providers.kubernetescrd.namespaces=vpn-transit" in args
    roles = [d for d in docs if d["kind"] == "Role"]
    assert {d["metadata"]["namespace"] for d in roles} == {
        "blog",
        "cats",
        "format-quorum",
        "vpn-transit",
    }
    for role in roles:
        assert all(set(r["verbs"]) <= {"get", "list", "watch"} for r in role["rules"])
    (svc,) = [d["spec"] for d in docs if d["kind"] == "Service"]
    assert (
        svc["type"] == "ClusterIP" and svc["selector"] == template["metadata"]["labels"]
    )
    (relay_policy,) = [d["spec"] for d in backend if d["kind"] == "NetworkPolicy"]
    (peer,) = relay_policy["ingress"][0]["from"]
    assert (
        peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        == moscow["namespace"]
    )
    assert peer["podSelector"]["matchLabels"] == svc["selector"]
    (relay_service,) = [d for d in backend if d["kind"] == "Service"]
    sockets = {(p["protocol"], p["port"]) for p in relay_service["spec"]["ports"]}
    assert {(p.get("protocol", "TCP"), p["port"]) for p in svc["ports"]} == sockets
    routed = set()
    for d in docs:
        if d["kind"] not in {"IngressRouteTCP", "IngressRouteUDP"}:
            continue
        assert d["metadata"]["namespace"] == relay_service["metadata"]["namespace"]
        assert (
            d["metadata"]["annotations"]["kubernetes.io/ingress.class"]
            == "traefik-moscow"
        )
        assert (
            d["metadata"]["labels"]["homelab.alchemmist.xyz/moscow-rehearsal"] == "true"
        )
        (route,) = d["spec"]["routes"]
        (dest,) = route["services"]
        assert dest["name"] == relay_service["metadata"]["name"] and dest["nativeLB"]
        proto = d["kind"][-3:]
        (backend_port,) = [
            p for p in relay_service["spec"]["ports"] if p["name"] == dest["port"]
        ]
        assert backend_port["protocol"] == proto
        port = backend_port["port"]
        (frontend,) = [
            p
            for p in svc["ports"]
            if (p.get("protocol", "TCP"), p["port"]) == (proto, port)
        ]
        (entry,) = d["spec"]["entryPoints"]
        assert (
            f"--entrypoints.{entry}.address=:{frontend['targetPort']}/{proto.lower()}"
            in args
        )
        assert (proto, port) not in routed
        routed.add((proto, port))
        if (proto, port) == ("TCP", 443):
            assert route["match"] == "HostSNI(`vpn.alchemmist.xyz`)"
            assert d["spec"]["tls"] == {"passthrough": True}
            assert d["spec"]["entryPoints"] == ["websecure"]
        else:
            assert d["spec"]["entryPoints"] == [f"{proto.lower()}-{port}"]
            assert "tls" not in d["spec"] and "middlewares" not in route
            if proto == "TCP":
                assert route["match"] == "HostSNI(`*`)"
    assert routed == sockets - {("TCP", 80)}


@pytest.mark.parametrize(
    "namespace,expected_hosts,secret",
    [
        ("blog", {"alchemmist.xyz", "www.alchemmist.xyz"}, "blog-tls"),
        ("cats", {"cats.alchemmist.xyz"}, "cats-tls"),
        ("format-quorum", {"fq.alchemmist.xyz"}, "format-quorum-tls"),
    ],
)
def test_canary_ingress_tls(
    namespace: str, expected_hosts: set[str], secret: str
) -> None:
    """Render the actual applications; an entrypoint default certificate is not enough."""
    targets, _ = argocd_targets()
    (target,) = [t for t in targets if t["release"] == namespace]
    (ingress,) = [d for d in render(target) if d["kind"] == "Ingress"]
    spec = ingress["spec"]
    assert ingress["metadata"]["namespace"] == namespace
    assert spec["ingressClassName"] == "traefik"
    assert {rule["host"] for rule in spec["rules"]} == expected_hosts
    (tls,) = spec["tls"]
    assert set(tls["hosts"]) == expected_hosts and tls["secretName"] == secret
