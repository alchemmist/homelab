"""Offline-only gates for the staged, not activated, unified browser edge."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UnifiedOrigin(unittest.TestCase):
    """Guarded route priority and the inactive unified-origin default."""

    def test_routes_are_guarded_and_exactly_prioritized(self) -> None:
        """Require browser, outpost, evidence, gateway, and isolation contracts."""
        text = subprocess.check_output(
            [
                "helm",
                "template",
                "rustfs",
                str(ROOT / "charts/rustfs"),
                "-n",
                "rustfs",
                "-f",
                str(ROOT / "charts/rustfs/values-foundation-live.yaml"),
                "--set",
                "browserRoutes.unifiedOrigin=true",
            ],
            text=True,
        )
        docs = text.split("---")
        console = next(d for d in docs if "name: rustfs-console-browser" in d)
        assert "argocd-rustfs-browser-auth@kubernetescrd" in console
        assert "service: {name: rustfs-console-http, port: {number: 80}}" in console
        assert "number: 9000" not in console
        middleware = next(d for d in docs if "kind: Middleware" in d)
        assert "namespace: argocd" in middleware
        assert "homelab.alchemmist.xyz/edge-transport: argocd" in middleware
        assert "trustForwardHeader: false" in middleware
        assert (
            "https://rustfs.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/traefik"
            in middleware
        )
        outpost = next(d for d in docs if "name: rustfs-authentik-browser" in d)
        assert "router.priority: '200'" in outpost
        assert "path: /\n" not in outpost
        reader = next(d for d in docs if "name: rustfs-evidence-browser" in d)
        assert "router.priority: '150'" in reader
        assert "path: /spi/v1/" in reader
        assert "host: rustfs.socrat.alchemmist.xyz" in reader
        gateway = next(d for d in docs if "name: gateway\n" in d)
        assert (
            "https://rustfs.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/nginx"
            in gateway
        )
        policy = next(d for d in docs if "name: rustfs-isolation" in d)
        import yaml

        parsed = yaml.safe_load(policy)
        for ingress in parsed["spec"]["ingress"]:
            for peer in ingress["from"]:
                assert (
                    peer.get("podSelector", {})
                    .get("matchLabels", {})
                    .get("app.kubernetes.io/name")
                    != "traefik"
                )
            assert {p["port"] for p in ingress["ports"]} <= {9000, 9001}
        assert "0.0.0.0/0" not in text

    def test_activation_remains_off(self) -> None:
        """Keep the unified browser origin absent unless explicitly enabled."""
        text = subprocess.check_output(
            [
                "helm",
                "template",
                "rustfs",
                str(ROOT / "charts/rustfs"),
                "-n",
                "rustfs",
                "-f",
                str(ROOT / "charts/rustfs/values-foundation-live.yaml"),
                "--set",
                "browserRoutes.unifiedOrigin=false",
            ],
            text=True,
        )
        assert "name: rustfs-browser-auth" not in text
        assert "kind: Middleware" not in text
        assert (
            "https://spi-evidence.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/nginx"
            in text
        )


def test_optional_public_entry_peer_changes_only_reader_ingress() -> None:
    """The transport peer must not gain direct S3 or console access."""
    import yaml

    helm = [
        "helm",
        "template",
        "rustfs",
        str(ROOT / "charts/rustfs"),
        "-f",
        str(ROOT / "charts/rustfs/values-foundation-live.yaml"),
        "--set",
        "browserRoutes.unifiedOrigin=true",
    ]

    def render(*args: str) -> list[dict]:
        return list(
            yaml.safe_load_all(subprocess.check_output([*helm, *args], text=True))
        )

    default = render()
    enabled = render("--set", "browserRoutes.allowPublicEntryReaderPeer=true")
    (policy,) = [
        d
        for d in enabled
        if d
        and d["kind"] == "NetworkPolicy"
        and d["metadata"]["name"] == "rustfs-public-reader"
    ]
    assert policy["metadata"]["namespace"] == "identity"
    (rule,) = policy["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8080}]
    peer = {
        "namespaceSelector": {
            "matchLabels": {"kubernetes.io/metadata.name": "public-entry"}
        },
        "podSelector": {
            "matchLabels": {"homelab.alchemmist.xyz/public-entry-controller": "true"}
        },
    }
    assert rule["from"].count(peer) == 1, "expected exactly one scoped common controller peer"
    rule["from"].remove(peer)
    assert enabled == default
    result = subprocess.run(
        [*helm, "--set-string", "browserRoutes.allowPublicEntryReaderPeer=false"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode and "allowPublicEntryReaderPeer" in result.stderr


def test_reader_schema_rejects_misspelled_browser_switch() -> None:
    result = subprocess.run(["helm", "template", "rustfs", str(ROOT / "charts/rustfs"),
                             "--set", "browserRoutes.unifiedOrigins=true"],
                            capture_output=True, text=True, check=False)
    assert result.returncode and "unifiedOrigins" in result.stderr
