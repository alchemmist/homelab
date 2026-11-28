"""Render and verify password-self-service's narrowly scoped network contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _render(*args: str) -> list[dict]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "password-self-service",
            "charts/password-self-service",
            "--namespace",
            "identity",
            *args,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def _ports(rules: list[dict]) -> set[tuple[str, int]]:
    return {
        (port["protocol"], port["port"]) for rule in rules for port in rule["ports"]
    }


def test_rendered_password_service_network_policy_is_minimal() -> None:
    documents = _render()
    policies = [doc for doc in documents if doc.get("kind") == "NetworkPolicy"]
    assert len(policies) == 1
    policy = policies[0]
    assert policy["metadata"]["namespace"] == "identity"
    assert policy["spec"]["podSelector"]["matchLabels"] == {
        "app": "password-self-service"
    }
    spec = policy["spec"]
    assert set(spec["policyTypes"]) == {"Ingress", "Egress"}

    ingress = spec["ingress"]
    assert len(ingress) == 1
    assert len(ingress[0]["from"]) == 1
    traefik_peer = ingress[0]["from"][0]
    assert traefik_peer["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "kube-system"
    }
    assert traefik_peer["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "traefik"
    }
    assert _ports(ingress) == {("TCP", 8080)}

    egress = spec["egress"]
    assert len(egress) == 2
    authentik, dns = egress
    assert authentik["to"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "identity"
    }
    assert authentik["to"][0]["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "authentik",
        "app.kubernetes.io/instance": "authentik",
        "app.kubernetes.io/component": "server",
    }
    assert len(authentik["to"]) == 1
    assert _ports([authentik]) == {("TCP", 9000)}
    assert dns["to"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "kube-system"
    }
    assert dns["to"][0]["podSelector"]["matchLabels"] == {"k8s-app": "kube-dns"}
    assert _ports([dns]) == {("UDP", 53), ("TCP", 53)}

    # No wildcard peer/range rule can silently grant unrelated callers or destinations.
    assert all("ipBlock" not in str(rule) for rule in ingress + egress)
    assert all(
        "namespaceSelector" in str(rule) and "podSelector" in str(rule)
        for rule in ingress + egress
    )

    service = next(doc for doc in documents if doc.get("kind") == "Service")
    assert service["spec"]["selector"] == spec["podSelector"]["matchLabels"]
    deployment = next(doc for doc in documents if doc.get("kind") == "Deployment")
    assert (
        deployment["spec"]["template"]["metadata"]["labels"]
        == spec["podSelector"]["matchLabels"]
    )

    nginx = (ROOT / "charts/password-self-service/files/nginx.conf").read_text()
    assert "authentik-server.identity.svc.cluster.local" in nginx
    assert "proxy_pass http://authentik-server.identity.svc.cluster.local/" in nginx
    assert "listen 8080;" in nginx


def test_rehearsal_admission_changes_only_the_controller_peer() -> None:
    baseline = _render()
    enabled = _render("--set", "allowPublicEntryPeer=true")
    assert baseline != enabled
    (policy,) = [doc for doc in enabled if doc["kind"] == "NetworkPolicy"]
    (rule,) = policy["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8080}]
    assert len(rule["from"]) == 2
    assert rule["from"].pop() == {
        "namespaceSelector": {
            "matchLabels": {"kubernetes.io/metadata.name": "public-entry"}
        },
        "podSelector": {
            "matchLabels": {"homelab.alchemmist.xyz/public-entry-controller": "true"}
        },
    }
    assert enabled == baseline


@pytest.mark.parametrize("value", ["true", "false", "1"])
def test_peer_flag_rejects_strings(value: str) -> None:
    with pytest.raises(subprocess.CalledProcessError) as exc:
        _render("--set-string", f"allowPublicEntryPeer={value}")
    assert "allowPublicEntryPeer" in exc.value.stderr


@pytest.mark.parametrize(
    "path,status,location,result",
    [
        (
            "/change-password/",
            302,
            "https://auth.socrat.alchemmist.xyz/change-password",
            "matched",
        ),
        (
            "/change-password/",
            302,
            "https://example.invalid/change-password",
            "unexpected-response",
        ),
        (
            "/change-password",
            302,
            "https://auth.socrat.alchemmist.xyz/if/flow/default-authentication-flow/?next=%2Fchange-password",
            "matched",
        ),
        (
            "/change-password",
            302,
            "https://auth.socrat.alchemmist.xyz/change-password",
            "unexpected-response",
        ),
        ("/change-password", 200, "", "unexpected-response"),
        ("/change-password/", 502, "", "http-502"),
    ],
)
def test_anonymous_password_path_witness(monkeypatch, path, status, location, result):
    from types import SimpleNamespace

    from ci.quality import password_route_probe as probe

    def run(args, *, capture_output, timeout):
        assert capture_output is True and timeout == 9
        assert (
            args[-1] == "https://" + probe.HOST + path
            and args[args.index("--proto") + 1] == "=https"
            and args[args.index("--resolve") + 1] == probe.HOST + ":443:192.0.2.1"
            and not {"--location", "--insecure", "--cookie"} & set(args)
        )
        return subprocess.CompletedProcess(
            args, 0, stdout=f"{status}\n{location}".encode()
        )

    monkeypatch.setattr(
        probe,
        "subprocess",
        SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired),
    )
    assert probe.sample(path, ip="192.0.2.1") == result


@pytest.mark.parametrize(
    "last", [{}, {"publicIP": "::1"}, {"publicIP": "192.0.2.1"}, {"publicIP": 123}]
)
def test_password_probe_rejects_whole_invalid_inventory_before_network(
    tmp_path, monkeypatch, capsys, last
):
    from ci.quality import password_route_probe as probe

    catalog = tmp_path / "sites.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "replicas": {
                    "home": {"publicIP": "192.0.2.1"},
                    "nl": {"publicIP": "192.0.2.2"},
                    "moscow": last,
                }
            }
        )
    )
    monkeypatch.setattr(probe, "CATALOG", catalog)
    monkeypatch.setattr(
        probe, "sample", lambda *a, **kw: pytest.fail("unexpected network request")
    )
    assert probe.main() == 1
    assert "invalid-entrance-inventory" in capsys.readouterr().out
